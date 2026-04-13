import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { uploadDocument } from '../api/documents'
import { startOntologyExtraction } from '../api/ontology'
import { getTask } from '../api/tasks'
import { useProjectStore } from './project'

export interface UploadedFile {
  id: string
  name: string
  ext: string
  size: string
  pages: string
  chunks: number
  status: string
  statusLabel: string
}

export interface LogEntry {
  time: string
  level: string
  msg: string
}

export interface SessionEntry {
  id: string
  timestamp: string
  topic: string
  purpose: string
  ontologyId: string
  fileCount: number
  entityCount: number
  relationCount: number
}

function wait(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export const useDocumentStore = defineStore('document', () => {
  const projectStore = useProjectStore()

  const files = ref<UploadedFile[]>([])
  const logs = ref<LogEntry[]>([])
  const isExtracting = ref(false)
  const extractionDone = ref(false)
  const extractionProgress = ref(0)
  const extractionTaskId = ref('')
  const ontologyId = ref('')
  const ontologyTopic = ref('')
  const lastOntologyResult = ref<any>(null)
  const currentStep = ref('')
  const sessions = ref<SessionEntry[]>([])

  let _abortController: AbortController | null = null
  let _pollRunId = 0

  const doneFiles = computed(() => files.value.filter(file => file.status === 'done'))

  function addLog(level: string, msg: string) {
    const d = new Date()
    const t = [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map(n => String(n).padStart(2, '0'))
      .join(':')
    logs.value.push({ time: t, level, msg })
  }

  function formatSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1048576).toFixed(1)} MB`
  }

  async function upload(file: File) {
    const ext = file.name.split('.').pop()?.toLowerCase() || ''
    if (!['pdf', 'docx', 'txt', 'md'].includes(ext)) {
      addLog('warn', `지원하지 않는 형식: ${file.name}`)
      return
    }

    const tempId = `temp_${Date.now()}_${file.name}`
    files.value.push({
      id: tempId,
      name: file.name,
      ext,
      size: formatSize(file.size),
      pages: '-',
      chunks: 0,
      status: 'active',
      statusLabel: '업로드중',
    })

    try {
      addLog('info', `업로드 시작: ${file.name}`)
      const res = await uploadDocument(file)
      const idx = files.value.findIndex(f => f.id === tempId)
      if (idx >= 0) {
        files.value[idx] = {
          id: res.id,
          name: res.filename,
          ext: res.ext,
          size: formatSize(res.size),
          pages: res.pages ? String(res.pages) : '-',
          chunks: res.chunks,
          status: 'done',
          statusLabel: '분석완료',
        }
      }
      addLog('info', `완료: ${file.name} (${res.chunks}개 청크, ${res.pages || '?'}p)`)

      const docEntry = {
        id: res.id,
        name: res.filename,
        ext: res.ext,
        size: formatSize(res.size),
        pages: res.pages ? String(res.pages) : '-',
        chunks: res.chunks,
      }
      if (!projectStore.currentProjectId) {
        projectStore.createProject(docEntry)
      } else {
        projectStore.addDocumentToCurrentProject(docEntry)
      }
    } catch (err: any) {
      const idx = files.value.findIndex(f => f.id === tempId)
      if (idx >= 0) {
        files.value[idx].status = 'error'
        files.value[idx].statusLabel = '에러'
      }
      addLog('error', `실패: ${file.name} - ${err.message}`)
    }
  }

  function removeFile(name: string) {
    files.value = files.value.filter(file => file.name !== name)
  }

  async function extractOntology(
    topic: string,
    purpose: string,
    opts: any,
    agent: { provider: string; modelName: string; apiKey: string; baseUrl?: string },
    method: 'hybrid' | 'llm' = 'hybrid',
  ) {
    const docIds = doneFiles.value.map(file => file.id)
    if (docIds.length === 0) {
      addLog('error', '업로드한 문서가 없습니다.')
      return
    }
    if (!agent.apiKey) {
      addLog('error', `${agent.provider} API 키가 비어 있습니다.`)
      return
    }

    isExtracting.value = true
    extractionDone.value = false
    extractionProgress.value = 0
    extractionTaskId.value = ''
    ontologyId.value = ''           // 이전 온톨로지 ID 비우기 → 그래프 뷰에서 이전 데이터 로드 방지
    lastOntologyResult.value = null
    currentStep.value = '지식 그래프 추출 요청 전송 중...'

    const methodLabel = method === 'hybrid' ? 'Hybrid (KoNER + LLM)' : 'LLM direct'
    addLog('info', `지식 그래프 추출 시작 (${methodLabel} / ${agent.provider} / ${agent.modelName})`)

    _abortController = new AbortController()
    const runId = ++_pollRunId

    try {
      const start = await startOntologyExtraction(method, {
        doc_ids: docIds,
        topic,
        purpose,
        llm: {
          provider: agent.provider,
          model: agent.modelName,
          api_key: agent.apiKey,
          base_url: agent.baseUrl || undefined,
        },
        extract_entities: opts.entities,
        extract_relations: opts.relations,
        extract_events: opts.events,
        extract_sentiment: opts.sentiment,
      })

      extractionTaskId.value = start.task_id
      extractionProgress.value = 2
      addLog('info', `추출 task 시작: ${start.task_id.slice(0, 8)}`)

      let result: any = null
      while (runId === _pollRunId) {
        const task = await getTask(start.task_id)
        extractionProgress.value = task.progress ?? extractionProgress.value
        currentStep.value = task.message || currentStep.value

        if (task.status === 'completed') {
          result = task.result
          extractionProgress.value = 100
          break
        }
        if (task.status === 'failed') {
          throw new Error(task.error || task.message || '추출 실패')
        }

        await wait(900)
      }

      if (runId !== _pollRunId) {
        throw new Error('POLLING_ABORTED')
      }
      if (!result) {
        throw new Error('추출 결과를 받지 못했습니다.')
      }

      currentStep.value = '결과 처리 중...'
      addLog('info', `스키마: ${result.entity_types?.length || 0}개 엔티티 타입 / ${result.relation_types?.length || 0}개 관계 타입`)
      addLog('info', `개체: ${result.entities?.length || 0}개`)
      addLog('info', `관계: ${result.relations?.length || 0}개`)
      addLog('info', `지식 그래프 ID: ${result.id}`)

      ontologyId.value = result.id
      ontologyTopic.value = topic
      lastOntologyResult.value = result
      extractionDone.value = true
      extractionProgress.value = 100
      currentStep.value = '완료'

      projectStore.addOntologyVersion({
        id: result.id,
        nodeCount: result.nodes?.length ?? 0,
        edgeCount: result.edges?.length ?? 0,
        entityCount: result.entities?.length ?? 0,
        relationCount: result.relations?.length ?? 0,
        topic,
        purpose,
        model: agent.modelName,
        provider: agent.provider,
        docIds,
      })

      saveSession(topic, purpose, result)
    } catch (err: any) {
      if (err.name === 'AbortError' || err.message === 'POLLING_ABORTED') {
        currentStep.value = '중지됨'
        addLog('warn', '추출 폴링을 중지했습니다. 서버 작업은 계속될 수 있습니다.')
      } else {
        currentStep.value = '에러 발생'
        addLog('error', `추출 실패: ${err.message}`)
      }
    } finally {
      isExtracting.value = false
      _abortController = null
      extractionTaskId.value = ''
    }
  }

  function cancelExtraction() {
    _pollRunId += 1
    _abortController?.abort()
  }

  function saveSession(topic: string, purpose: string, result: any) {
    sessions.value.unshift({
      id: crypto.randomUUID(),
      timestamp: new Date().toLocaleString('ko-KR'),
      topic,
      purpose,
      ontologyId: result.id,
      fileCount: doneFiles.value.length,
      entityCount: result.entities?.length || 0,
      relationCount: result.relations?.length || 0,
    })
    if (sessions.value.length > 20) {
      sessions.value = sessions.value.slice(0, 20)
    }
  }

  function loadSession(sessionId: string) {
    const session = sessions.value.find(item => item.id === sessionId)
    if (session) {
      ontologyId.value = session.ontologyId
      ontologyTopic.value = session.topic
      addLog('info', `세션 복원: ${session.topic} (${session.ontologyId})`)
    }
  }

  function deleteSession(sessionId: string) {
    sessions.value = sessions.value.filter(session => session.id !== sessionId)
  }

  /** 새 프로젝트 시작 시 파일·추출 상태 초기화 (세션 이력은 유지) */
  function resetForNewProject() {
    _pollRunId += 1
    _abortController?.abort()
    _abortController = null

    files.value = []
    logs.value = []
    isExtracting.value = false
    extractionDone.value = false
    extractionProgress.value = 0
    extractionTaskId.value = ''
    ontologyId.value = ''
    ontologyTopic.value = ''
    lastOntologyResult.value = null
    currentStep.value = ''
  }

  /** 프로젝트 전환 시 해당 프로젝트의 문서 목록으로 동기화 */
  function syncWithProject(docs: { id: string; name: string; ext: string; size: string; pages: string; chunks: number }[], activeOntologyId?: string) {
    files.value = docs.map(d => ({
      id: d.id,
      name: d.name,
      ext: d.ext,
      size: d.size,
      pages: d.pages,
      chunks: d.chunks,
      status: 'done',
      statusLabel: '완료',
    }))
    // 활성 온톨로지 ID 동기화
    ontologyId.value = activeOntologyId || ''
    // 추출 상태 초기화
    isExtracting.value = false
    extractionDone.value = false
    extractionProgress.value = 0
    currentStep.value = ''
    lastOntologyResult.value = null
  }

  return {
    files,
    logs,
    isExtracting,
    extractionDone,
    extractionProgress,
    extractionTaskId,
    ontologyId,
    ontologyTopic,
    lastOntologyResult,
    currentStep,
    sessions,
    doneFiles,
    addLog,
    upload,
    removeFile,
    extractOntology,
    cancelExtraction,
    saveSession,
    loadSession,
    deleteSession,
    resetForNewProject,
    syncWithProject,
  }
}, {
  persist: true,
})

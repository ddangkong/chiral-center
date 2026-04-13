import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiStream } from '../api/client'
import { askSimulationQA } from '../api/simulation'
import { useProjectStore } from './project'
import { useSettingsStore } from './settings'
import { useLLMStore } from './llm'

export interface SimAgent {
  id: string; name: string; role: string; stance: string
  initials: string; color: string
}

export interface SimEventItem {
  type: 'round' | 'event' | 'system'
  round?: number
  time?: string
  agentId?: string
  agentName?: string
  action?: string  // post, reply, repost, skip, question, concede, propose, cite, moderator
  content?: string
  eventId?: string
  threadId?: string
  parentEventId?: string
}

export interface QAMessage {
  id: string
  type: 'question' | 'answer'
  content: string
  timestamp: string
  referencedRounds?: number[]
  referencedAgents?: string[]
}

/** 시뮬레이션 실행 시점의 UI 설정 스냅샷 — 히스토리 복원 시 같이 살리기 위함 */
export interface SimConfigSnapshot {
  rounds?: number
  maxPersonas?: number
  topic?: string
  selectedEntityIds?: string[]
  entityMode?: boolean
}

const COLORS = [
  '#5C6BC0', '#26A69A', '#78909C', '#AB47BC', '#EF5350',
  '#FFA726', '#66BB6A', '#42A5F5', '#EC407A', '#8D6E63',
  '#7E57C2', '#29B6F6', '#FF7043', '#9CCC65', '#26C6DA',
]

const LEGACY_ROLE_MAP: Record<string, string> = {
  '마케팅팀장': 'market_analyst',
  '영업팀장': 'market_analyst',
  '재무팀장': 'financial_analyst',
  'R&D팀장': 'tech_reviewer',
  'SCM팀장': 'risk_analyst',
  '구매팀장': 'risk_analyst',
  '품질관리팀장': 'risk_analyst',
  '기획팀장': 'strategy_lead',
}

function normalizeRoleKey(role: string) {
  return LEGACY_ROLE_MAP[role] || role
}

export const useSimulationStore = defineStore('simulation', () => {
  const projectStore = useProjectStore()

  const simId = ref('')
  const isRunning = ref(false)
  const currentRound = ref(0)
  const totalRounds = ref(10)
  const agents = ref<SimAgent[]>([])
  const eventLog = ref<SimEventItem[]>([])
  const platform = ref('discussion')
  const qaMessages = ref<QAMessage[]>([])
  const isQALoading = ref(false)
  let _abortController: AbortController | null = null

  function getAgent(id: string | undefined) {
    return agents.value.find(a => a.id === id)
  }

  function clearLog() {
    eventLog.value = []
    currentRound.value = 0
  }

  /** 새 프로젝트 시작 시 전체 초기화 */
  function resetAll() {
    _abortController?.abort()
    _abortController = null
    simId.value = ''
    isRunning.value = false
    currentRound.value = 0
    totalRounds.value = 10
    agents.value = []
    eventLog.value = []
    qaMessages.value = []
    isQALoading.value = false
  }

  async function runSimulation(
    ontologyId: string,
    topic: string,
    numRounds: number,
    maxPersonas: number,
    llmConfig: { provider: string; model: string; api_key: string; base_url?: string },
    entityPersonas?: string[],
    simOptions?: { temperature?: number; min_chars?: number; max_chars?: number },
  ) {
    isRunning.value = true
    currentRound.value = 0
    totalRounds.value = numRounds
    eventLog.value = []
    agents.value = []
    platform.value = 'discussion'

    _abortController = new AbortController()
    let lastRound = 0

    try {
      const settingsStore = useSettingsStore()
      const agentOverrides = settingsStore.agentPrompts
        .filter(a => a.enabled)
        .reduce<{ role: string; system_prompt: string }[]>((acc, a) => {
          const role = normalizeRoleKey(a.role)
          const systemPrompt = a.systemPrompt.trim()
          if (!systemPrompt) return acc

          const found = acc.find(item => item.role === role)
          if (found) {
            found.system_prompt = `${found.system_prompt}\n\n${systemPrompt}`.trim()
          } else {
            acc.push({ role, system_prompt: systemPrompt })
          }
          return acc
        }, [])
      const disabledRoles = settingsStore.agentPrompts
        .filter(a => !a.enabled)
        .map(a => normalizeRoleKey(a.role))

      // Build custom profiles from profiled agents
      const customProfiles = settingsStore.customAgents
        .filter(a => a.enabled && a.profile)
        .map(a => a.profile!)

      const stream = apiStream('/simulation/run', {
        ontology_id: ontologyId,
        topic,
        num_rounds: numRounds,
        max_personas: maxPersonas,
        platform: 'discussion',
        llm: llmConfig,
        injection_events: [],
        project_id: projectStore.currentProject?.dbId || undefined,
        global_directive: [settingsStore.languageDirective(), settingsStore.globalDirective].filter(Boolean).join('\n\n') || undefined,
        agent_overrides: agentOverrides.length > 0 ? agentOverrides : undefined,
        disabled_roles: disabledRoles.length > 0 ? disabledRoles : undefined,
        custom_profiles: customProfiles.length > 0 ? customProfiles : undefined,
        entity_personas: entityPersonas && entityPersonas.length > 0 ? entityPersonas : undefined,
        temperature: simOptions?.temperature,
        min_chars: simOptions?.min_chars,
        max_chars: simOptions?.max_chars,
      }, _abortController.signal)

      for await (const data of stream) {
        if (data.type === 'start') {
          simId.value = data.sim_id
          // Build agent list from personas
          agents.value = (data.personas || []).map((p: any, i: number) => ({
            id: p.id,
            name: p.name,
            role: p.role || '',
            stance: classifyStance(p.stance || ''),
            initials: p.name.slice(0, 2),
            color: COLORS[i % COLORS.length],
          }))
        } else if (data.type === 'event') {
          // Add round separator if new round
          if (data.round && data.round !== lastRound) {
            lastRound = data.round
            currentRound.value = data.round
            eventLog.value.push({ type: 'round', round: data.round })
          }

          const now = new Date()
          const time = `${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}.${String(Math.floor(now.getMilliseconds() / 10)).padStart(2, '0')}`

          // 모더레이터 / DB 에이전트 이벤트 처리
          const isModerator = data.persona_id === '__moderator__' || data.persona === '⚖️ Moderator'
          const isDbAgent = data.persona_id === '__db_agent__' || data.persona === '🗄️ DB Agent'
          eventLog.value.push({
            type: 'event',
            round: data.round,
            time,
            agentId: isModerator ? '__moderator__' : isDbAgent ? '__db_agent__' : (agents.value.find(a => a.name === data.persona)?.id || ''),
            agentName: data.persona,
            action: data.action,
            content: data.content,
            eventId: data.event_id || '',
            threadId: data.thread_id || undefined,
            parentEventId: data.parent_event_id || undefined,
          })
        } else if (data.type === 'complete') {
          currentRound.value = totalRounds.value

          // Project 연동: 시뮬레이션 버전 추가
          projectStore.addSimulationVersion({
            id: simId.value,
            topic,
            rounds: numRounds,
            agentCount: agents.value.length,
            model: llmConfig.model,
            provider: llmConfig.provider,
            ontologyId,
          })

          // 시뮬레이션 데이터 로컬 저장
          saveToProject()
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        eventLog.value.push({ type: 'system', content: `에러: ${err.message}` })
      }
    } finally {
      isRunning.value = false
      _abortController = null
    }
  }

  function stopSimulation() {
    _abortController?.abort()
  }

  function classifyStance(stance: string): string {
    const s = stance.toLowerCase()
    if (s.includes('지지') || s.includes('찬성') || s.includes('긍정') || s.includes('support') || s.includes('pro')) return 'supportive'
    if (s.includes('반대') || s.includes('비판') || s.includes('부정') || s.includes('oppos') || s.includes('against')) return 'opposing'
    return 'neutral'
  }

  async function askQuestion(question: string) {
    if (!simId.value || isQALoading.value) return

    const llmStore = useLLMStore()
    const agent = llmStore.enabledAgents[0]
    if (!agent?.apiKey) return

    // 질문 카드 추가
    const qId = `qa_${Date.now()}`
    const now = new Date()
    const time = now.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })

    qaMessages.value.push({
      id: qId,
      type: 'question',
      content: question,
      timestamp: time,
    })

    isQALoading.value = true

    try {
      const settingsStore = useSettingsStore()
      const langHint = settingsStore.languageDirective()
      const result = await askSimulationQA({
        sim_id: simId.value,
        question: `${question}\n\n[${langHint}]`,
        provider: agent.provider,
        model: agent.modelName,
        api_key: agent.apiKey,
        base_url: agent.baseUrl || undefined,
      })

      qaMessages.value.push({
        id: `${qId}_answer`,
        type: 'answer',
        content: result.answer,
        timestamp: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
        referencedRounds: result.referenced_rounds,
        referencedAgents: result.referenced_agents,
      })
    } catch (err: any) {
      qaMessages.value.push({
        id: `${qId}_error`,
        type: 'answer',
        content: `오류: ${err.message || '답변 생성에 실패했습니다.'}`,
        timestamp: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
      })
    } finally {
      isQALoading.value = false
      saveToProject()  // Q&A도 저장
    }
  }

  function clearQA() {
    qaMessages.value = []
  }

  // ── 시뮬레이션별 스냅샷 저장/복원 ──
  //
  // 이전 구조: sim_${projectId} — 프로젝트당 1슬롯이라 여러 시뮬 중 마지막 것만 살아남음.
  // 새 구조:  sim_${projectId}_${simId} — 시뮬별로 완전히 격리된 스냅샷.
  // 스냅샷에는 config(rounds, maxPersonas, selectedEntityIds, entityMode, topic) 도 함께 저장해서
  // 히스토리 복원 시 해당 시뮬 실행 당시의 설정이 UI에 그대로 복구되도록 한다.

  const LEGACY_SIM_KEY = (pid: string) => `sim_${pid}`
  const SIM_KEY = (pid: string, sid: string) => `sim_${pid}_${sid}`

  type SimSnapshot = {
    simId: string
    currentRound: number
    totalRounds: number
    agents: SimAgent[]
    eventLog: SimEventItem[]
    platform: string
    qaMessages: QAMessage[]
    config?: SimConfigSnapshot
  }

  // 현재 UI state에서 저장할 config를 추출할 콜백. SimulationView에서 주입.
  // (store가 UI state에 직접 접근하지 않도록 해서 단방향 의존을 유지)
  let _configSnapshotProvider: (() => SimConfigSnapshot) | null = null
  function setConfigSnapshotProvider(fn: () => SimConfigSnapshot) {
    _configSnapshotProvider = fn
  }

  /** 현재 시뮬레이션 데이터를 localStorage에 저장 — 시뮬별 독립 키 */
  function saveToProject(projectId?: string) {
    const pid = projectId || projectStore.currentProjectId
    const sid = simId.value
    if (!pid || !sid) return
    try {
      const data: SimSnapshot = {
        simId: sid,
        currentRound: currentRound.value,
        totalRounds: totalRounds.value,
        agents: agents.value,
        eventLog: eventLog.value,
        platform: platform.value,
        qaMessages: qaMessages.value,
        config: _configSnapshotProvider ? _configSnapshotProvider() : undefined,
      }
      localStorage.setItem(SIM_KEY(pid, sid), JSON.stringify(data))
    } catch { /* quota exceeded 등 무시 */ }
  }

  function _applySnapshot(data: SimSnapshot): SimConfigSnapshot | null {
    simId.value = data.simId || ''
    currentRound.value = data.currentRound || 0
    totalRounds.value = data.totalRounds || 10
    agents.value = data.agents || []
    eventLog.value = data.eventLog || []
    platform.value = data.platform || 'discussion'
    qaMessages.value = data.qaMessages || []
    isRunning.value = false
    isQALoading.value = false
    return data.config || null
  }

  /** 특정 시뮬레이션의 스냅샷을 복원. 복원에 성공하면 SimConfigSnapshot 반환 (없으면 null). */
  function loadSimulation(projectId: string, sid: string): SimConfigSnapshot | null {
    if (!projectId || !sid) {
      resetAll()
      return null
    }
    try {
      // 1순위: 시뮬별 키
      let raw = localStorage.getItem(SIM_KEY(projectId, sid))

      // 2순위: 레거시 단일 키가 있고 해당 simId와 일치하는 경우 — 한 번만 마이그레이션
      if (!raw) {
        const legacyRaw = localStorage.getItem(LEGACY_SIM_KEY(projectId))
        if (legacyRaw) {
          try {
            const legacy = JSON.parse(legacyRaw) as Partial<SimSnapshot>
            if (legacy?.simId === sid) {
              raw = legacyRaw
              // 새 키로 복사 후 레거시는 제거
              localStorage.setItem(SIM_KEY(projectId, sid), legacyRaw)
              localStorage.removeItem(LEGACY_SIM_KEY(projectId))
            }
          } catch { /* ignore */ }
        }
      }

      if (!raw) {
        resetAll()
        return null
      }
      const data = JSON.parse(raw) as SimSnapshot
      return _applySnapshot(data)
    } catch {
      resetAll()
      return null
    }
  }

  /**
   * Deprecated alias for backwards compat. 프로젝트의 활성 시뮬을 복원하거나,
   * 활성 시뮬이 없으면 가장 최근 시뮬 또는 레거시 단일 스냅샷을 복원한다.
   * 신규 코드는 loadSimulation(projectId, simId)를 직접 호출할 것.
   */
  function loadFromProject(projectId: string): boolean {
    if (!projectId) { resetAll(); return false }
    const project = projectStore.projects.find(p => p.id === projectId)
    const activeSimId = project?.activeSimulationId
      || (project?.simulations?.[project.simulations.length - 1]?.id ?? '')

    if (activeSimId) {
      const config = loadSimulation(projectId, activeSimId)
      return config !== null || simId.value !== ''
    }

    // 활성/최근 시뮬이 없는데 레거시 스냅샷이 남아 있으면 그걸 임시로 로드
    try {
      const legacyRaw = localStorage.getItem(LEGACY_SIM_KEY(projectId))
      if (legacyRaw) {
        const data = JSON.parse(legacyRaw) as SimSnapshot
        _applySnapshot(data)
        // 새 키로 보존 (simId가 있는 경우)
        if (data.simId) {
          localStorage.setItem(SIM_KEY(projectId, data.simId), legacyRaw)
          localStorage.removeItem(LEGACY_SIM_KEY(projectId))
        }
        return true
      }
    } catch { /* ignore */ }

    resetAll()
    return false
  }

  /** 프로젝트 삭제 시 저장 데이터도 제거 — 해당 프로젝트의 모든 sim 스냅샷 */
  function removeProjectData(projectId: string) {
    if (!projectId) return
    const prefix = `sim_${projectId}_`
    const toRemove: string[] = []
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i)
        if (!key) continue
        if (key === LEGACY_SIM_KEY(projectId) || key.startsWith(prefix)) {
          toRemove.push(key)
        }
      }
      for (const k of toRemove) localStorage.removeItem(k)
    } catch { /* ignore */ }
  }

  /** 특정 시뮬레이션 스냅샷만 제거 */
  function removeSimulationData(projectId: string, sid: string) {
    if (!projectId || !sid) return
    try { localStorage.removeItem(SIM_KEY(projectId, sid)) } catch {}
  }

  return {
    simId, isRunning, currentRound, totalRounds,
    agents, eventLog, platform,
    qaMessages, isQALoading,
    getAgent, clearLog, resetAll, runSimulation, stopSimulation,
    askQuestion, clearQA,
    saveToProject, loadFromProject, loadSimulation,
    removeProjectData, removeSimulationData,
    setConfigSnapshotProvider,
  }
})

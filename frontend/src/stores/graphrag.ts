import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { indexCollection, queryGraphRAG, getIndexStatus, getIndexByCollection, getCommunities, type LLMConfig } from '../api/graphrag'

export interface CommunityItem {
  id: number
  title: string
  summary: string
  entities: string[]
  weight: number
}

export interface QAEntry {
  id: string
  query: string
  answer: string
  searchType: string
  entities: string[]
  communities: string[]
  timestamp: string
}

export const useGraphRAGStore = defineStore('graphrag', () => {
  const indexId = ref('')
  const collectionId = ref('')
  const status = ref<'idle' | 'indexing' | 'ready' | 'error'>('idle')
  const progress = ref({ stage: '', current: 0, total: 0 })
  const entities = ref(0)
  const relations = ref(0)
  const communitiesCount = ref(0)
  const communities = ref<CommunityItem[]>([])
  const qaHistory = ref<QAEntry[]>([])
  const isQuerying = ref(false)
  const error = ref('')

  let _abortController: AbortController | null = null

  const isReady = computed(() => status.value === 'ready')
  const isIndexing = computed(() => status.value === 'indexing')

  const progressPercent = computed(() => {
    if (progress.value.total === 0) return 0
    const stageWeights: Record<string, [number, number]> = {
      entities: [0, 60],
      communities: [60, 70],
      summaries: [70, 100],
    }
    const w = stageWeights[progress.value.stage] || [0, 100]
    const stageProgress = progress.value.current / progress.value.total
    return Math.round(w[0] + (w[1] - w[0]) * stageProgress)
  })

  async function startIndexing(colId: string, llm: LLMConfig) {
    collectionId.value = colId
    status.value = 'indexing'
    error.value = ''
    progress.value = { stage: 'entities', current: 0, total: 0 }

    _abortController = new AbortController()

    try {
      const stream = indexCollection(colId, llm, _abortController.signal)

      for await (const data of stream) {
        if (data.type === 'progress') {
          progress.value = { stage: data.stage, current: data.current, total: data.total }
        } else if (data.type === 'complete') {
          indexId.value = data.index_id
          entities.value = data.entities
          relations.value = data.relations
          communitiesCount.value = data.communities
          status.value = 'ready'
        } else if (data.type === 'error') {
          error.value = data.error
          status.value = 'error'
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        error.value = err.message
        status.value = 'error'
      }
    } finally {
      _abortController = null
    }
  }

  function cancelIndexing() {
    _abortController?.abort()
    status.value = 'idle'
  }

  async function query(queryText: string, searchType: string, llm: LLMConfig) {
    if (!indexId.value) return

    isQuerying.value = true
    try {
      const res = await queryGraphRAG(indexId.value, queryText, searchType, llm)
      qaHistory.value.unshift({
        id: crypto.randomUUID(),
        query: queryText,
        answer: res.answer,
        searchType: res.search_type,
        entities: res.context_entities || [],
        communities: res.context_communities || [],
        timestamp: new Date().toLocaleString('ko-KR'),
      })
    } catch (err: any) {
      qaHistory.value.unshift({
        id: crypto.randomUUID(),
        query: queryText,
        answer: `오류: ${err.message}`,
        searchType,
        entities: [],
        communities: [],
        timestamp: new Date().toLocaleString('ko-KR'),
      })
    } finally {
      isQuerying.value = false
    }
  }

  async function loadCommunities() {
    if (!indexId.value) return
    try {
      const res = await getCommunities(indexId.value)
      communities.value = res.communities || []
    } catch { /* ignore */ }
  }

  async function checkExistingIndex(colId: string) {
    try {
      const res = await getIndexByCollection(colId)
      if (res.index_id) {
        indexId.value = res.index_id
        collectionId.value = colId
        const statusRes = await getIndexStatus(res.index_id)
        status.value = statusRes.status as any
        entities.value = statusRes.entities
        relations.value = statusRes.relations
        communitiesCount.value = statusRes.communities
        return true
      }
    } catch { /* ignore */ }
    return false
  }

  function reset() {
    indexId.value = ''
    collectionId.value = ''
    status.value = 'idle'
    entities.value = 0
    relations.value = 0
    communitiesCount.value = 0
    communities.value = []
    error.value = ''
  }

  function clearQA() {
    qaHistory.value = []
  }

  return {
    indexId, collectionId, status, progress, entities, relations, communitiesCount,
    communities, qaHistory, isQuerying, error,
    isReady, isIndexing, progressPercent,
    startIndexing, cancelIndexing, query, loadCommunities,
    checkExistingIndex, reset, clearQA,
  }
}, {
  persist: {
    pick: ['indexId', 'collectionId', 'status', 'entities', 'relations', 'communitiesCount', 'qaHistory'],
  },
})

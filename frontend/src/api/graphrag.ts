/**
 * GraphRAG API client — DB 컬렉션 기반
 */
import { api, apiStream } from './client'

export interface LLMConfig {
  provider: string
  model: string
  api_key: string
  base_url?: string
}

export function indexCollection(collectionId: string, llm: LLMConfig, signal?: AbortSignal) {
  return apiStream('/graphrag/index', {
    collection_id: collectionId,
    llm,
  }, signal)
}

export function queryGraphRAG(indexId: string, query: string, searchType: string, llm: LLMConfig) {
  return api('/graphrag/query', {
    method: 'POST',
    body: JSON.stringify({ index_id: indexId, query, search_type: searchType, llm }),
  })
}

export function getIndexStatus(indexId: string) {
  return api(`/graphrag/status/${indexId}`)
}

export function getIndexByCollection(collectionId: string) {
  return api(`/graphrag/by-collection/${collectionId}`)
}

export function getCommunities(indexId: string) {
  return api(`/graphrag/index/${indexId}/communities`)
}

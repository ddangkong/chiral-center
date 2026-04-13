import { api } from './client'

export interface ExtractionRequest {
  doc_ids: string[]
  topic: string
  purpose: string
  llm: {
    provider: string
    model: string
    api_key: string
    base_url?: string
  }
  extract_entities: boolean
  extract_relations: boolean
  extract_events: boolean
  extract_sentiment: boolean
}

export async function startOntologyExtraction(method: 'hybrid' | 'llm', body: ExtractionRequest) {
  const endpoint = method === 'hybrid' ? '/ontology/extract/hybrid/async' : '/ontology/extract/async'
  return api(endpoint, {
    method: 'POST',
    body: JSON.stringify(body),
  }) as Promise<{ task_id: string; status: string }>
}

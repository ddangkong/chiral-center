import { api } from './client'

export interface LLMConfig {
  provider: string; model: string; api_key: string; base_url?: string
}

export async function buildGraph(ontologyId: string, llm: LLMConfig) {
  return api('/graph/build', { method: 'POST', body: JSON.stringify({ ontology_id: ontologyId, llm }) })
}

export async function startGraphBuild(ontologyId: string, llm: LLMConfig) {
  return api('/graph/build/async', {
    method: 'POST',
    body: JSON.stringify({ ontology_id: ontologyId, llm }),
  }) as Promise<{ task_id: string; status: string }>
}

export async function getGraphData(ontologyId: string) {
  return api(`/graph/data?ontology_id=${ontologyId}`)
}

export async function getGraphNodes(ontologyId: string) {
  return api(`/graph/nodes?ontology_id=${ontologyId}`)
}

export async function getGraphEdges(ontologyId: string) {
  return api(`/graph/edges?ontology_id=${ontologyId}`)
}

export async function searchGraph(ontologyId: string, q: string) {
  return api(`/graph/search?ontology_id=${ontologyId}&q=${encodeURIComponent(q)}`)
}

export async function getCommunities(ontologyId: string) {
  return api(`/graph/communities?ontology_id=${ontologyId}`)
}

export async function summarizeCommunities(ontologyId: string, llm: LLMConfig) {
  return api('/graph/communities/summarize', {
    method: 'POST',
    body: JSON.stringify({ ontology_id: ontologyId, llm }),
  })
}

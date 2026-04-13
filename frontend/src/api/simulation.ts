import { api, apiStream } from './client'

export interface SimRunRequest {
  ontology_id: string
  topic: string
  num_rounds: number
  max_personas: number
  llm: { provider: string; model: string; api_key: string; base_url?: string }
  injection_events: { round: number; content: string }[]
}

export function runSimulationStream(req: SimRunRequest) {
  return apiStream('/simulation/run', req)
}

export async function getSimulation(simId: string) {
  return api(`/simulation/${simId}`)
}

export async function stopSimulation(simId: string) {
  return api(`/simulation/stop?sim_id=${simId}`, { method: 'POST' })
}

export async function getSimPersonas(simId: string) {
  return api(`/simulation/${simId}/personas`)
}

export async function askSimulationQA(params: {
  sim_id: string
  question: string
  provider: string
  model: string
  api_key: string
  base_url?: string
}): Promise<{ answer: string; referenced_rounds: number[]; referenced_agents: string[] }> {
  return api('/simulation/qa', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

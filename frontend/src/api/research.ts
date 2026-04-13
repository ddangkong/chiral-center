import { api } from './client'

export async function listResearchSessions(): Promise<any[]> {
  return api('/research/sessions')
}

export async function getResearchSession(sessionId: string): Promise<any> {
  return api(`/research/sessions/${sessionId}`)
}

export async function startResearch(params: {
  query: string
  model?: string
  api_key: string
  session_id?: string
}): Promise<{ session_id: string; response_id: string; status: string }> {
  return api('/research/start', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export async function deleteResearchSession(sessionId: string): Promise<void> {
  await api(`/research/sessions/${sessionId}`, { method: 'DELETE' })
}

export function streamResearch(responseId: string, apiKey: string): EventSource {
  return new EventSource(
    `/api/research/stream/${responseId}?api_key=${encodeURIComponent(apiKey)}`,
    { withCredentials: true },
  )
}

/** SSE stream for the DDG hybrid orchestrator mode (doesn't need api_key param). */
export function streamOrchestrator(sessionId: string): EventSource {
  return new EventSource(
    `/api/research/stream/orchestrator/${sessionId}`,
    { withCredentials: true },
  )
}

import { api } from './client'

export async function generateReport(req: {
  simulation_id: string; ontology_id: string; topic: string
  llm: { provider: string; model: string; api_key: string; base_url?: string }
}) {
  return api('/report/generate', { method: 'POST', body: JSON.stringify(req) })
}

export async function getReport(reportId: string) {
  return api(`/report/${reportId}`)
}

export async function exportReport(reportId: string, format = 'markdown') {
  return api(`/report/${reportId}/export?format=${format}`)
}

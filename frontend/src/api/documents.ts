import { api, apiUpload } from './client'

export async function uploadDocument(file: File) {
  const form = new FormData()
  form.append('file', file)
  return apiUpload('/documents/upload', form)
}

export async function getDocument(docId: string) {
  return api(`/documents/${docId}`)
}

export async function listDocuments() {
  return api('/documents/')
}

export async function fetchResearchSessions() {
  return api('/documents/research/sessions')
}

export async function importResearchDoc(conversationId: string, conversationTitle: string) {
  return api('/documents/research/import', {
    method: 'POST',
    body: JSON.stringify({ conversation_id: conversationId, conversation_title: conversationTitle }),
  })
}

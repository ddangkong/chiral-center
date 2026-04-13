import { api } from './client'

export interface TaskResponse<T = any> {
  id: string
  kind: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  created_at: string
  updated_at: string
  result?: T
  error?: string | null
  meta?: Record<string, any>
}

export async function getTask(taskId: string) {
  return api(`/tasks/${taskId}`) as Promise<TaskResponse>
}

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client'

export interface DbFile {
  name: string
  chunks: number
  uploadedAt: string
}

export interface DBCollection {
  id: string
  name: string
  description: string
  files: DbFile[]
  totalRecords: number
  createdAt: string
  updatedAt: string
}

export const useDatabaseStore = defineStore('database', () => {
  const collections = ref<DBCollection[]>([])
  const currentCollectionId = ref<string | null>(null)
  const isUploading = ref(false)
  const logs = ref<string[]>([])

  const currentCollection = computed(() =>
    collections.value.find(c => c.id === currentCollectionId.value) ?? null
  )

  function addLog(msg: string) {
    const t = new Date().toLocaleTimeString('ko-KR')
    logs.value.push(`[${t}] ${msg}`)
    if (logs.value.length > 50) logs.value = logs.value.slice(-50)
  }

  function createCollection(name: string, description: string): DBCollection {
    const col: DBCollection = {
      id: `db_${Date.now()}`,
      name,
      description,
      files: [],
      totalRecords: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    collections.value.push(col)
    currentCollectionId.value = col.id
    return col
  }

  function updateCollection(id: string, patch: Partial<Pick<DBCollection, 'name' | 'description'>>) {
    const col = collections.value.find(c => c.id === id)
    if (!col) return
    Object.assign(col, patch)
    col.updatedAt = new Date().toISOString()
  }

  async function uploadFile(collectionId: string, file: File): Promise<boolean> {
    isUploading.value = true
    addLog(`업로드 시작: ${file.name}`)
    try {
      const form = new FormData()
      form.append('project_id', collectionId)
      form.append('file', file)

      const res = await fetch('/api/db/upload', { method: 'POST', body: form, credentials: 'include' })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || '업로드 실패')
      }
      const data = await res.json()

      const col = collections.value.find(c => c.id === collectionId)
      if (col) {
        col.files.push({ name: file.name, chunks: data.chunks_added, uploadedAt: new Date().toISOString() })
        col.totalRecords = data.total_records
        col.updatedAt = new Date().toISOString()
      }
      addLog(`완료: ${file.name} (${data.chunks_added}개 레코드)`)
      return true
    } catch (err: any) {
      addLog(`실패: ${file.name} — ${err.message}`)
      return false
    } finally {
      isUploading.value = false
    }
  }

  async function fetchStatus(collectionId: string) {
    try {
      const data = await api(`/db/status/${collectionId}`)
      const col = collections.value.find(c => c.id === collectionId)
      if (col) {
        if (data.total_records > 0) {
          col.totalRecords = data.total_records
        } else if (col.files.length > 0) {
          // 백엔드 인덱스 소실 시 파일 chunks 합계 유지
          col.totalRecords = col.files.reduce((sum, f) => sum + (f.chunks || 0), 0)
        }
      }
    } catch {
      // 백엔드 재시작 등으로 인덱스 소실 시, 파일 chunks 합계로 복원
      const col = collections.value.find(c => c.id === collectionId)
      if (col && col.totalRecords === 0 && col.files.length > 0) {
        col.totalRecords = col.files.reduce((sum, f) => sum + (f.chunks || 0), 0)
      }
    }
  }

  async function clearCollection(collectionId: string) {
    await api(`/db/clear/${collectionId}`, { method: 'DELETE' })
    const col = collections.value.find(c => c.id === collectionId)
    if (col) {
      col.files = []
      col.totalRecords = 0
      col.updatedAt = new Date().toISOString()
    }
    addLog('DB 인덱스 초기화 완료')
  }

  function deleteCollection(collectionId: string) {
    collections.value = collections.value.filter(c => c.id !== collectionId)
    if (currentCollectionId.value === collectionId) {
      currentCollectionId.value = collections.value[0]?.id ?? null
    }
  }

  function setCurrentCollection(id: string | null) {
    currentCollectionId.value = id
    logs.value = []
  }

  return {
    collections, currentCollectionId, currentCollection, isUploading, logs,
    createCollection, updateCollection, uploadFile, fetchStatus,
    clearCollection, deleteCollection, setCurrentCollection, addLog,
  }
}, {
  persist: {
    pick: ['collections', 'currentCollectionId'],
  },
})

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div class="modal-overlay" v-if="visible" @click.self="emit('close')">
        <div class="research-modal">

          <div class="modal-header">
            <div class="modal-title">리서치 결과 가져오기</div>
            <div class="modal-sub">Deep Research에서 완료된 보고서를 문서로 변환합니다</div>
          </div>

          <div v-if="loading" class="state-msg">
            <div class="state-icon spin">↻</div>
            <div class="state-text">세션 목록 로딩 중...</div>
          </div>

          <div v-else-if="error" class="state-msg error">
            <div class="state-icon">!</div>
            <div class="state-text">{{ error }}</div>
          </div>

          <div v-else-if="sessions.length === 0" class="state-msg">
            <div class="state-icon">🔬</div>
            <div class="state-text">완료된 리서치가 없습니다</div>
          </div>

          <div v-else class="session-list">
            <div
              v-for="s in sessions"
              :key="s.id"
              class="session-item"
              :class="{ selected: selectedId === s.id }"
              @click="selectedId = s.id; selectedTitle = s.title"
            >
              <div class="session-info">
                <div class="session-title">{{ s.title || '(제목 없음)' }}</div>
                <div class="session-meta mono">{{ fmtDate(s.updated_at || s.created_at) }}</div>
              </div>
              <div class="session-check" v-if="selectedId === s.id">✓</div>
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn-cancel" @click="emit('close')">닫기</button>
            <button
              class="btn-import"
              :disabled="!selectedId || importing"
              @click="doImport"
            >
              {{ importing ? '가져오는 중...' : '가져오기 →' }}
            </button>
          </div>

        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { listResearchSessions } from '../api/research'
import { importResearchDoc } from '../api/documents'

interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
}

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'imported', doc: any): void
}>()

const loading = ref(false)
const error = ref('')
const sessions = ref<Session[]>([])
const selectedId = ref<string | null>(null)
const selectedTitle = ref('')
const importing = ref(false)

watch(() => props.visible, async (v) => {
  if (!v) return
  selectedId.value = null
  selectedTitle.value = ''
  error.value = ''
  loading.value = true
  try {
    sessions.value = await listResearchSessions()
  } catch (e: any) {
    error.value = e.message || '세션 목록을 불러올 수 없습니다'
    sessions.value = []
  }
  loading.value = false
})

async function doImport() {
  if (!selectedId.value) return
  importing.value = true
  try {
    const doc = await importResearchDoc(selectedId.value, selectedTitle.value)
    emit('imported', doc)
  } catch (e: any) {
    error.value = e.message || '가져오기 실패'
  }
  importing.value = false
}

function fmtDate(iso: string) {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 9999;
  backdrop-filter: blur(4px);
}
.research-modal {
  background: #FFF; border-radius: 16px; width: 520px; max-width: 95vw;
  padding: 28px; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  display: flex; flex-direction: column; gap: 20px;
}
.modal-header { border-bottom: 1px solid #EAEAEA; padding-bottom: 16px; }
.modal-title { font-size: 16px; font-weight: 700; color: #000; }
.modal-sub { font-size: 12px; color: #AAA; margin-top: 4px; }

.state-msg { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px 0; }
.state-msg.error .state-icon { color: #EF4444; }
.state-msg.error .state-text { color: #EF4444; }
.state-icon { font-size: 28px; color: #DDD; }
.state-text { font-size: 13px; color: #AAA; text-align: center; }

.spin { animation: spin 1s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }

.session-list { display: flex; flex-direction: column; gap: 6px; max-height: 350px; overflow-y: auto; }
.session-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; border: 1px solid #EAEAEA; border-radius: 10px;
  cursor: pointer; transition: all 0.15s; background: #FAFAFA;
}
.session-item:hover { border-color: #BBB; background: #FFF; }
.session-item.selected { border-color: #FF5722; background: #FFF9F8; }
.session-info { flex: 1; min-width: 0; }
.session-title { font-size: 13px; font-weight: 600; color: #222; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-meta { font-size: 10px; color: #BBB; margin-top: 3px; }
.session-check { font-size: 14px; font-weight: 700; color: #FF5722; flex-shrink: 0; }

.modal-actions { display: flex; gap: 10px; border-top: 1px solid #EAEAEA; padding-top: 16px; }
.btn-cancel { flex: 1; padding: 10px; border: 1px solid #EAEAEA; border-radius: 8px; background: #FAFAFA; font-size: 13px; color: #888; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.btn-cancel:hover { border-color: #CCC; color: #333; }
.btn-import { flex: 2; padding: 10px; background: #FF5722; color: #FFF; border: none; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.btn-import:hover:not(:disabled) { background: #E64A19; }
.btn-import:disabled { opacity: 0.4; cursor: not-allowed; }

.mono { font-family: 'JetBrains Mono', monospace; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>

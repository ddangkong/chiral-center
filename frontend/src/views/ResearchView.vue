<template>
  <div class="research-view">

    <!-- Left: Session List -->
    <div class="rs-sidebar">
      <div class="rs-sidebar-header">
        <span class="rs-sidebar-title">{{ t('research.title') }}</span>
        <button class="rs-new-btn" @click="startNew">{{ t('research.new') }}</button>
      </div>
      <div class="rs-session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="rs-session-item"
          :class="{ active: currentSessionId === s.id }"
          @click="loadSession(s.id)"
        >
          <div class="rs-session-title">{{ s.title || '(제목 없음)' }}</div>
          <div class="rs-session-meta mono">
            <span>{{ s.model === 'o3-deep-research' ? 'o3' : s.model === 'ddg-hybrid-research' ? 'hybrid' : 'o4-mini' }}</span>
            <span>{{ fmtDate(s.updated_at || s.created_at) }}</span>
          </div>
          <div class="rs-session-status" :class="s.status">{{ statusLabel(s.status) }}</div>
        </div>
        <div v-if="sessions.length === 0 && !sessionsLoading" class="rs-empty">
          {{ t('research.noSessions') }}
        </div>
      </div>
    </div>

    <!-- Right: Research Content -->
    <div class="rs-main">

      <!-- Input Area -->
      <div class="rs-input-area" v-if="!isResearching && !currentContent">
        <div class="rs-input-card">
          <div class="rs-input-title">Deep Research</div>
          <div class="rs-input-desc">{{ t('research.desc') }}</div>
          <textarea
            v-model="queryText"
            class="rs-textarea"
            rows="4"
            :placeholder="t('research.placeholder')"
          ></textarea>
          <div class="rs-input-options">
            <select v-model="selectedModel" class="rs-model-select mono">
              <option value="o4-mini-deep-research">{{ t('research.modelFast') }}</option>
              <option value="o3-deep-research">{{ t('research.modelPrecise') }}</option>
            </select>
            <button class="rs-start-btn" :disabled="!queryText.trim() || !apiKey" @click="doResearch">
              {{ t('research.start') }}
            </button>
          </div>
          <div v-if="!apiKey" class="rs-warn">{{ t('research.warnApiKey') }}</div>
        </div>
      </div>

      <!-- Researching State -->
      <div v-if="isResearching" class="rs-progress-area">
        <div class="rs-progress-card">
          <div class="rs-progress-header">
            <div class="rs-progress-spinner"></div>
            <span class="rs-progress-title">{{ t('research.inProgress') }}</span>
            <span class="rs-progress-model mono">{{ selectedModel }}</span>
          </div>
          <div class="rs-progress-query">{{ queryText }}</div>
          <div class="rs-steps">
            <div v-for="(step, i) in searchSteps" :key="i" class="rs-step">
              <span class="rs-step-icon mono">🔍</span>
              <span class="rs-step-query">{{ step.query }}</span>
            </div>
          </div>
          <div class="rs-progress-meta mono">
            {{ searchSteps.length }}개 검색 수행 중
            <span v-if="elapsedSeconds > 0"> · {{ Math.floor(elapsedSeconds / 60) }}분 {{ elapsedSeconds % 60 }}초 경과</span>
          </div>
          <div v-if="interimSources.length > 0" class="rs-interim-sources">
            <div class="rs-interim-title mono">수집된 소스 ({{ interimSources.length }})</div>
            <div v-for="(src, i) in interimSources" :key="i" class="rs-interim-item">
              <span class="rs-interim-idx mono">{{ i + 1 }}</span>
              <a :href="src.url" target="_blank" rel="noopener" class="rs-interim-link">{{ src.title || src.url }}</a>
            </div>
          </div>
          <button class="rs-cancel-btn" @click="cancelResearch">중단</button>
        </div>
      </div>

      <!-- Result -->
      <div v-if="currentContent && !isResearching" class="rs-result-area">
        <div class="rs-result-header">
          <div class="rs-result-title">{{ currentTitle }}</div>
          <div class="rs-result-actions">
            <button class="rs-action-btn" @click="copyContent">{{ t('research.copy') }}</button>
            <button class="rs-action-btn" @click="importToProject" :disabled="!currentContent">{{ t('research.import') }}</button>
          </div>
        </div>
        <div class="rs-result-content md-content" v-html="renderedContent"></div>
        <div v-if="currentSources.length > 0" class="rs-sources">
          <div class="rs-sources-title mono">{{ t('research.sources') }} ({{ currentSources.length }})</div>
          <div class="rs-sources-list">
            <a v-for="(src, i) in currentSources" :key="i" :href="src.url" target="_blank" rel="noopener" class="rs-source-item">
              <span class="rs-source-idx mono">{{ i + 1 }}</span>
              <span class="rs-source-text">{{ src.title || src.url }}</span>
            </a>
          </div>
        </div>
      </div>

      <!-- Error -->
      <div v-if="error" class="rs-error">{{ error }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useLLMStore } from '../stores/llm'
import { useI18n } from '../composables/useI18n'
import { listResearchSessions, getResearchSession, startResearch, streamResearch, streamOrchestrator } from '../api/research'
import { marked } from 'marked'

const llmStore = useLLMStore()
const { t } = useI18n()

const sessions = ref<any[]>([])
const sessionsLoading = ref(false)
const currentSessionId = ref('')
const queryText = ref('')
const selectedModel = ref('o4-mini-deep-research')
const isResearching = ref(false)
const searchSteps = ref<any[]>([])
const interimSources = ref<{ url: string; title: string }[]>([])
const elapsedSeconds = ref(0)
const currentContent = ref('')
const currentTitle = ref('')
const currentSources = ref<any[]>([])
const error = ref('')
let _currentEventSource: EventSource | null = null

const apiKey = computed(() => {
  const agent = llmStore.agents.find(a => a.provider === 'openai' && a.apiKey)
  return agent?.apiKey || ''
})

const renderedContent = computed(() => {
  if (!currentContent.value) return ''
  try {
    return marked(currentContent.value)
  } catch {
    return currentContent.value
  }
})

// ── localStorage 캐싱 ──
function getCachedSessions(): any[] {
  try { return JSON.parse(localStorage.getItem('research_sessions') || '[]') }
  catch { return [] }
}
function saveCachedSessions(list: any[]) {
  try { localStorage.setItem('research_sessions', JSON.stringify(list)) } catch {}
}
function getCachedSession(id: string): any | null {
  try { return JSON.parse(localStorage.getItem(`research_${id}`) || 'null') }
  catch { return null }
}
function saveCachedSession(session: any) {
  try { localStorage.setItem(`research_${session.id}`, JSON.stringify(session)) } catch {}
}

onMounted(async () => {
  await loadSessions()
  // 진행 중인 세션이 있으면 자동으로 열어서 SSE 재연결
  // (페이지 이동 후 복귀 시 로딩 상태 복구)
  const inProgress = sessions.value.find(s =>
    s.status && !['completed', 'failed'].includes(s.status)
  )
  if (inProgress) {
    await loadSession(inProgress.id)
  }
})

// unmount 시 SSE 연결만 끊고 백엔드 task는 계속 돌게 둔다.
// 다음에 다시 들어오면 onMounted에서 자동 재연결.
onBeforeUnmount(() => {
  if (_currentEventSource) {
    _currentEventSource.close()
    _currentEventSource = null
  }
})

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const remote = await listResearchSessions()
    // 원격 + 로컬 캐시 병합 (ID 중복 제거, 최신순)
    const local = getCachedSessions()
    const map = new Map<string, any>()
    for (const s of [...local, ...remote]) map.set(s.id, s)
    sessions.value = Array.from(map.values()).sort((a, b) =>
      (b.updated_at || b.created_at || '').localeCompare(a.updated_at || a.created_at || '')
    )
    saveCachedSessions(sessions.value)
  } catch {
    // 백엔드 실패 시 로컬 캐시만 사용
    sessions.value = getCachedSessions()
  }
  sessionsLoading.value = false
}

async function loadSession(id: string) {
  currentSessionId.value = id
  error.value = ''
  let data: any = null
  try {
    data = await getResearchSession(id)
  } catch {
    // 백엔드 실패 → 로컬 캐시에서 복원
    data = getCachedSession(id)
  }
  if (!data) { error.value = '세션을 찾을 수 없습니다'; return }
  try {
    currentTitle.value = data.title || ''
    queryText.value = data.query || data.title || ''

    if (data.status === 'completed' || data.status === 'failed') {
      currentContent.value = data.content || ''
      currentSources.value = data.sources || []
      searchSteps.value = data.search_steps || []
      isResearching.value = false
    } else {
      // 대기/진행 중 → 스트리밍 재연결
      currentContent.value = ''
      currentSources.value = []
      searchSteps.value = data.search_steps || []
      isResearching.value = true
      if (data.response_id && apiKey.value) {
        connectStream(data.response_id)
      }
    }
  } catch (e: any) {
    error.value = e.message
  }
}

function startNew() {
  currentSessionId.value = ''
  currentContent.value = ''
  currentTitle.value = ''
  currentSources.value = []
  searchSteps.value = []
  queryText.value = ''
  error.value = ''
  isResearching.value = false
}

function cancelResearch() {
  if (_currentEventSource) {
    _currentEventSource.close()
    _currentEventSource = null
  }
  isResearching.value = false
  error.value = '사용자가 리서치를 중단했습니다.'
}

function connectStream(responseId: string) {
  // DDG hybrid orchestrator mode uses a different endpoint (no api_key in URL)
  const es = responseId.startsWith('orchestrator:')
    ? streamOrchestrator(responseId.slice('orchestrator:'.length))
    : streamResearch(responseId, apiKey.value)
  _currentEventSource = es

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)

      if (data.type === 'search_step') {
        searchSteps.value.push(data.step)
      } else if (data.type === 'interim_sources') {
        // 진행 중 실시간으로 수집되는 소스 URL 표시
        for (const src of (data.sources || [])) {
          if (!interimSources.value.some(s => s.url === src.url)) {
            interimSources.value.push(src)
          }
        }
      } else if (data.type === 'completed') {
        currentContent.value = data.content || ''
        currentSources.value = data.sources || []
        isResearching.value = false
        es.close()
        // localStorage에 완료된 세션 저장
        if (currentSessionId.value) {
          saveCachedSession({
            id: currentSessionId.value,
            title: currentTitle.value,
            query: queryText.value,
            content: currentContent.value,
            sources: currentSources.value,
            search_steps: searchSteps.value,
            status: 'completed',
            model: selectedModel.value,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          })
        }
        loadSessions()
      } else if (data.type === 'failed') {
        error.value = data.content || '리서치 실패'
        isResearching.value = false
        es.close()
      } else if (data.type === 'status') {
        // 경과 시간 업데이트 (폴링 서버에서 1초마다 전송)
        if (typeof data.elapsedSeconds === 'number') {
          elapsedSeconds.value = data.elapsedSeconds
        }
      } else if (data.type === 'error') {
        // 일시적 오류 — 폴링 계속
      } else if (data.type === 'timeout') {
        error.value = '시간 초과 (10분)'
        isResearching.value = false
        es.close()
      }
    } catch {}
  }

  es.onerror = () => {
    // SSE 자동 재연결 시도
  }
}

async function doResearch() {
  if (!queryText.value.trim() || !apiKey.value) return

  isResearching.value = true
  searchSteps.value = []
  interimSources.value = []
  elapsedSeconds.value = 0
  currentContent.value = ''
  currentSources.value = []
  error.value = ''

  try {
    const result = await startResearch({
      query: queryText.value,
      model: selectedModel.value,
      api_key: apiKey.value,
    })

    currentSessionId.value = result.session_id
    currentTitle.value = queryText.value.slice(0, 80)
    connectStream(result.response_id)

  } catch (e: any) {
    error.value = e.message || '리서치 시작 실패'
    isResearching.value = false
  }
}

function copyContent() {
  if (currentContent.value) {
    navigator.clipboard.writeText(currentContent.value)
  }
}

async function importToProject() {
  if (!currentContent.value || !currentSessionId.value) return
  try {
    const { api } = await import('../api/client')
    await api('/documents/research/import', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: currentSessionId.value,
        conversation_title: currentTitle.value,
      }),
    })
    alert('프로젝트에 가져왔습니다')
  } catch (e: any) {
    alert('가져오기 실패: ' + e.message)
  }
}

function fmtDate(iso: string) {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}

function statusLabel(status: string) {
  const map: Record<string, string> = { completed: t('status.done'), in_progress: t('status.active'), failed: t('common.failed'), queued: t('status.pending') }
  return map[status] || status
}
</script>

<style scoped>
.research-view { display: flex; height: 100%; overflow: hidden; }

/* Sidebar */
.rs-sidebar { width: 280px; border-right: 1px solid #EAEAEA; display: flex; flex-direction: column; background: #FFF; flex-shrink: 0; }
.rs-sidebar-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #EAEAEA; }
.rs-sidebar-title { font-size: 14px; font-weight: 700; color: #000; }
.rs-new-btn { padding: 4px 12px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 11px; font-weight: 600; background: #FAFAFA; color: #555; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.rs-new-btn:hover { border-color: #FF5722; color: #FF5722; }

.rs-session-list { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 4px; }
.rs-session-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; transition: all 0.1s; }
.rs-session-item:hover { background: #F7F7F7; }
.rs-session-item.active { background: #FFF3F0; }
.rs-session-title { font-size: 13px; font-weight: 500; color: #222; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rs-session-meta { font-size: 9px; color: #BBB; display: flex; gap: 8px; margin-top: 2px; }
.rs-session-status { display: inline-block; font-size: 9px; font-weight: 600; margin-top: 3px; font-family: 'JetBrains Mono', monospace; }
.rs-session-status.completed { color: #2E7D32; }
.rs-session-status.in_progress { color: #E65100; }
.rs-session-status.failed { color: #C62828; }
.rs-empty { font-size: 12px; color: #CCC; text-align: center; padding: 32px 16px; }

/* Main */
.rs-main { flex: 1; display: flex; flex-direction: column; overflow-y: auto; background: #FAFAFA; }

/* Input */
.rs-input-area { flex: 1; display: flex; align-items: center; justify-content: center; padding: 32px; }
.rs-input-card { width: 100%; max-width: 640px; background: #FFF; border: 1px solid #EAEAEA; border-radius: 16px; padding: 32px; display: flex; flex-direction: column; gap: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); }
.rs-input-title { font-size: 20px; font-weight: 700; color: #000; }
.rs-input-desc { font-size: 13px; color: #888; line-height: 1.6; }
.rs-textarea { border: 1px solid #EAEAEA; border-radius: 10px; padding: 14px 16px; font-size: 14px; font-family: 'Space Grotesk', sans-serif; color: #111; resize: vertical; outline: none; transition: border-color 0.15s; min-height: 100px; }
.rs-textarea:focus { border-color: #FF5722; }
.rs-textarea::placeholder { color: #CCC; }
.rs-input-options { display: flex; gap: 10px; align-items: center; }
.rs-model-select { padding: 8px 12px; border: 1px solid #EAEAEA; border-radius: 8px; font-size: 12px; background: #FAFAFA; color: #333; outline: none; cursor: pointer; }
.rs-start-btn { flex: 1; padding: 12px; background: #000; color: #FFF; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.rs-start-btn:hover:not(:disabled) { background: #FF5722; }
.rs-start-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.rs-warn { font-size: 12px; color: #E65100; background: #FFF3E0; padding: 8px 12px; border-radius: 6px; }

/* Progress */
.rs-progress-area { flex: 1; padding: 32px; display: flex; align-items: flex-start; justify-content: center; }
.rs-progress-card { width: 100%; max-width: 640px; background: #FFF; border: 1px solid #EAEAEA; border-radius: 16px; padding: 28px; display: flex; flex-direction: column; gap: 16px; }
.rs-progress-header { display: flex; align-items: center; gap: 12px; }
.rs-progress-spinner {
  width: 24px; height: 24px; border-radius: 50%;
  border: 3px solid #FFE0CC;
  border-top: 3px solid #FF5722;
  border-right: 3px solid #FFE0CC;
  border-bottom: 3px solid #FFE0CC;
  border-left: 3px solid #FFE0CC;
  animation: spin 0.8s linear infinite;
  box-sizing: border-box;
}
@keyframes spin { to { transform: rotate(360deg); } }
.rs-progress-title { font-size: 16px; font-weight: 700; color: #E65100; }
.rs-progress-model { font-size: 11px; color: #BBB; margin-left: auto; }
.rs-progress-query { font-size: 13px; color: #555; line-height: 1.5; padding: 10px 14px; background: #FAFAFA; border-radius: 8px; }
.rs-steps { display: flex; flex-direction: column; gap: 4px; max-height: 300px; overflow-y: auto; }
.rs-step { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #666; padding: 4px 0; }
.rs-step-icon { font-size: 12px; }
.rs-step-query { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #888; }
.rs-progress-meta { font-size: 11px; color: #BBB; }
.rs-interim-sources {
  margin-top: 12px;
  padding: 10px 14px;
  background: #F7FBF7;
  border: 1px solid #E8F0E8;
  border-radius: 8px;
  max-height: 200px;
  overflow-y: auto;
}
.rs-interim-title {
  font-size: 11px;
  font-weight: 600;
  color: #4CAF50;
  margin-bottom: 6px;
}
.rs-interim-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 2px 0;
  animation: fadeInSource 0.3s ease-in;
}
.rs-interim-idx { font-size: 10px; color: #999; min-width: 16px; }
.rs-interim-link {
  font-size: 11px;
  color: #388E3C;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rs-interim-link:hover { text-decoration: underline; }
@keyframes fadeInSource {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.rs-cancel-btn {
  margin-top: 12px;
  padding: 8px 20px;
  border: 1px solid #EF5350;
  border-radius: 8px;
  background: transparent;
  color: #EF5350;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  font-family: 'Space Grotesk', sans-serif;
}
.rs-cancel-btn:hover { background: #EF5350; color: #FFF; }

/* Result */
.rs-result-area { flex: 1; display: flex; flex-direction: column; }
.rs-result-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 24px; border-bottom: 1px solid #EAEAEA; background: #FFF; flex-shrink: 0; }
.rs-result-title { font-size: 15px; font-weight: 700; color: #000; }
.rs-result-actions { display: flex; gap: 8px; }
.rs-action-btn { padding: 6px 14px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 12px; background: #FFF; color: #555; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.rs-action-btn:hover { border-color: #FF5722; color: #FF5722; }
.rs-action-btn:disabled { opacity: 0.4; }
.rs-result-content { padding: 24px; font-size: 14px; line-height: 1.8; color: #333; overflow-y: auto; flex: 1; }
.rs-result-content :deep(h1) { font-size: 20px; font-weight: 700; margin: 24px 0 12px; color: #000; }
.rs-result-content :deep(h2) { font-size: 17px; font-weight: 700; margin: 20px 0 10px; color: #111; }
.rs-result-content :deep(h3) { font-size: 15px; font-weight: 600; margin: 16px 0 8px; color: #222; }
.rs-result-content :deep(p) { margin: 8px 0; }
.rs-result-content :deep(ul), .rs-result-content :deep(ol) { padding-left: 20px; margin: 8px 0; }
.rs-result-content :deep(li) { margin: 4px 0; }
.rs-result-content :deep(strong) { color: #000; }
.rs-result-content :deep(table) { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
.rs-result-content :deep(th) { background: #F5F5F5; padding: 8px 12px; text-align: left; font-weight: 600; border: 1px solid #EAEAEA; }
.rs-result-content :deep(td) { padding: 8px 12px; border: 1px solid #EAEAEA; }

/* Sources */
.rs-sources { border-top: 1px solid #EAEAEA; padding: 16px 24px; flex-shrink: 0; }
.rs-sources-title { font-size: 11px; font-weight: 700; color: #999; letter-spacing: 0.5px; margin-bottom: 8px; }
.rs-sources-list { display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow-y: auto; }
.rs-source-item { display: flex; align-items: center; gap: 8px; text-decoration: none; padding: 4px 8px; border-radius: 4px; transition: background 0.1s; }
.rs-source-item:hover { background: #F7F7F7; }
.rs-source-idx { font-size: 10px; color: #BBB; min-width: 16px; }
.rs-source-text { font-size: 12px; color: #3498db; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.rs-error { padding: 16px 24px; color: #C62828; font-size: 13px; background: #FFEBEE; }

.mono { font-family: 'JetBrains Mono', monospace; }
</style>

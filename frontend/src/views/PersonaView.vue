<template>
  <div class="persona-view">
    <!-- Left: Agent List -->
    <div class="pv-sidebar">
      <div class="pvs-header">
        <span class="pvs-title">{{ t('persona.title') }}</span>
        <button class="pvs-add" @click="addAgent()" :title="t('persona.step1')">+</button>
      </div>

      <div v-if="settings.customAgents.length === 0" class="pvs-empty">
        <div class="pvs-empty-steps">
          <div class="pvs-step"><span class="pvs-sn mono">1</span> {{ t('persona.step1') }}</div>
          <div class="pvs-step"><span class="pvs-sn mono">2</span> {{ t('persona.step2') }}</div>
          <div class="pvs-step"><span class="pvs-sn mono">3</span> {{ t('persona.step3') }}</div>
          <div class="pvs-step"><span class="pvs-sn mono">4</span> {{ t('persona.step4') }}</div>
        </div>
      </div>

      <div class="pvs-list">
        <button
          v-for="ca in settings.customAgents"
          :key="ca.id"
          class="pvs-item"
          :class="{ active: selectedId === ca.id }"
          @click="selectAgent(ca.id)"
        >
          <span class="pvs-dot" :style="{ background: dotColor(ca) }" />
          <div class="pvs-item-body">
            <span class="pvs-item-name">{{ ca.name || '이름 없음' }}</span>
            <span class="pvs-item-sub mono">
              <template v-if="ca.profile && ca.enabled">참여 중</template>
              <template v-else-if="ca.profile">프로파일됨</template>
              <template v-else-if="ca._crawlChunks">{{ ca._crawlChunks }}건</template>
              <template v-else>미수집</template>
            </span>
          </div>
        </button>
      </div>
    </div>

    <!-- Right: Main -->
    <div class="pv-main">
      <!-- Empty -->
      <div v-if="!selected" class="pv-empty">
        <span class="pv-empty-icon">👤</span>
        <span class="pv-empty-title">{{ settings.customAgents.length ? t('persona.selectPerson') : t('persona.addPerson') }}</span>
        <span class="pv-empty-desc">{{ t('persona.emptyDesc') }}</span>
        <button v-if="!settings.customAgents.length" class="pv-empty-btn" @click="addAgent()">{{ t('persona.addNew') }}</button>
      </div>

      <template v-if="selected">
        <!-- Top Bar: name + options + actions in one row -->
        <div class="pv-topbar">
          <input
            v-model="selected.name"
            class="topbar-name"
            placeholder="인물 이름"
            :disabled="!!selected.profile"
          />
          <span v-if="selected.profile" class="topbar-role mono">{{ selected.profile.role }}</span>

          <template v-if="!selected.profile">
            <div class="topbar-sep" />
            <button
              class="topbar-pill"
              :class="{ on: sourceOptions[selected.id]?.web !== false }"
              @click="toggleSource(selected.id, 'web')"
            >웹</button>
            <button
              class="topbar-pill"
              :class="{ on: sourceOptions[selected.id]?.youtube !== false }"
              @click="toggleSource(selected.id, 'youtube')"
            >YouTube</button>
            <div class="topbar-sep" />
            <input type="date" v-model="dateFrom[selected.id]" class="topbar-date" />
            <span class="topbar-date-sep">~</span>
            <input type="date" v-model="dateTo[selected.id]" class="topbar-date" />
          </template>

          <div class="topbar-spacer" />
          <button v-if="!selected.profile" class="topbar-btn primary" :disabled="!selected.name.trim() || selected._collecting" @click="startCollect(selected)">
            <span v-if="selected._collecting" class="btn-spinner"></span>
            {{ selected._collecting ? t('persona.collecting') : t('persona.autoCollect') }}
          </button>
          <button v-if="selected._searchResults?.length" class="topbar-btn ghost" @click="showSources[selected.id] = !showSources[selected.id]">
            {{ showSources[selected.id] ? '원본 닫기' : `원본 ${selected._searchResults.length}건` }}
          </button>
          <button class="topbar-btn ghost danger" @click="removeAgent(selected.id)">{{ t('common.delete') }}</button>
        </div>

        <!-- 원본 소스 패널 -->
        <div v-if="showSources[selected.id] && selected._searchResults?.length" class="sources-panel">
          <div class="sources-title">크롤링 원본 데이터 <span class="sources-count">{{ selected._searchResults.length }}건</span></div>
          <div class="sources-list">
            <a
              v-for="(r, i) in selected._searchResults"
              :key="i"
              :href="r.url"
              target="_blank"
              rel="noopener"
              class="source-item"
            >
              <span class="source-badge mono" :class="r.source_type">{{ r.source_type === 'youtube' ? 'YT' : 'WEB' }}</span>
              <div class="source-info">
                <div class="source-title">{{ r.title }}</div>
                <div class="source-url">{{ r.url }}</div>
              </div>
            </a>
          </div>
        </div>

        <!-- Collect Progress (below topbar) -->
        <div v-if="!selected.profile && (selected._collectLog?.length || selected._searchResults?.length || selected._crawlChunks || selected._crawlError)" class="pv-collect">
          <div v-if="selected._collectLog?.length" class="collect-log">
            <div v-for="(entry, i) in selected._collectLog" :key="i" class="collect-log-item" :class="entry.type">
              <span class="log-icon mono">{{ entry.type === 'ok' ? '✓' : entry.type === 'fail' ? '✕' : '…' }}</span>
              <span class="log-text">{{ entry.text }}</span>
            </div>
          </div>

          <div v-if="selected._searchResults?.length" class="search-results">
            <div class="sr-label mono">검색 결과 {{ selected._searchResults.length }}건</div>
            <div class="sr-list">
              <div v-for="(r, i) in selected._searchResults" :key="i" class="sr-item">
                <span class="sr-badge mono" :class="r.source_type">{{ r.source_type === 'youtube' ? 'YT' : 'WEB' }}</span>
                <span class="sr-text">{{ r.title }}</span>
              </div>
            </div>
          </div>

          <div v-if="selected._crawlChunks && !selected.profile" class="collect-done">
            <span class="collect-done-text">{{ selected._crawlChunks }}건 수집 완료</span>
            <button class="topbar-btn primary" :disabled="profileLoading[selected.id]" @click="doProfile(selected)">
              {{ profileLoading[selected.id] ? '분석 중…' : 'LLM 프로파일링' }}
            </button>
          </div>

          <div v-if="selected._crawlError" class="pv-error">{{ selected._crawlError }}</div>
        </div>

        <!-- Profile Detail -->
        <div v-if="selected.profile" class="pv-profile-wrap">
          <div class="profile-toggle" @click="showProfile[selected.id] = !showProfile[selected.id]">
            <span class="profile-toggle-label">{{ t('persona.profile') }}</span>
            <span class="profile-toggle-arrow">{{ showProfile[selected.id] ? '▲' : '▼' }}</span>
          </div>
        <div v-show="showProfile[selected.id]" class="pv-profile">
          <div class="profile-section">
            <div class="profile-row">
              <div class="profile-field"><span class="pf-label">성격</span><span class="pf-value">{{ selected.profile.personality }}</span></div>
              <div class="profile-field"><span class="pf-label">의사결정 스타일</span><span class="pf-value">{{ selected.profile.decision_style }}</span></div>
            </div>
            <div class="profile-row">
              <div class="profile-field"><span class="pf-label">말투 / 커뮤니케이션</span><span class="pf-value">{{ selected.profile.speech_style }}</span></div>
              <div class="profile-field"><span class="pf-label">포지션</span><span class="pf-value">{{ selected.profile.stance }}</span></div>
            </div>
            <div class="profile-row">
              <div class="profile-field full"><span class="pf-label">설명</span><span class="pf-value">{{ selected.profile.description }}</span></div>
            </div>
            <div class="profile-row">
              <div class="profile-field">
                <span class="pf-label">핵심 가치관</span>
                <div class="pf-tags">
                  <span v-for="v in (selected.profile.core_values || [])" :key="v" class="pf-tag">{{ v }}</span>
                </div>
              </div>
              <div class="profile-field">
                <span class="pf-label">전문 분야</span>
                <div class="pf-tags">
                  <span v-for="k in (selected.profile.knowledge || [])" :key="k" class="pf-tag">{{ k }}</span>
                </div>
              </div>
            </div>
            <div class="profile-row">
              <div class="profile-field">
                <span class="pf-label">추구 목표</span>
                <div class="pf-list">
                  <div v-for="g in (selected.profile.goals || [])" :key="g" class="pf-list-item">{{ g }}</div>
                </div>
              </div>
              <div class="profile-field">
                <span class="pf-label">약점 / 편향</span>
                <div class="pf-list">
                  <div v-for="b in (selected.profile.blind_spots || [])" :key="b" class="pf-list-item warn">{{ b }}</div>
                </div>
              </div>
            </div>
            <div v-if="selected.profile.known_stances && Object.keys(selected.profile.known_stances).length" class="profile-row">
              <div class="profile-field full">
                <span class="pf-label">주요 입장</span>
                <div class="pf-stances">
                  <div v-for="(val, key) in selected.profile.known_stances" :key="key" class="pf-stance">
                    <span class="stance-topic">{{ key }}</span>
                    <span class="stance-val">{{ val }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="profile-meta">
              소스 {{ selected.profile.source_count || 0 }}건 · {{ (selected.profile.sources || []).length }}개 출처
            </div>
          </div>
        </div>
        </div>

        <!-- Chat -->
        <div class="pv-chat" v-if="selected.profile">
          <div class="chat-bar">
            <span class="chat-bar-title">{{ selected.name }} 대화</span>
            <span class="chat-bar-hint">프로파일 기반 응답</span>
          </div>

          <div class="chat-messages" ref="chatMessagesRef">
            <div v-if="!selected._chatMessages?.length" class="chat-empty">
              <span class="chat-empty-text">질문을 입력해서 {{ selected.name }}의 반응을 확인하세요</span>
              <div class="chat-suggests">
                <button class="chat-sug" @click="sendSuggestion(selected, '이 사업에 대해 어떻게 생각하세요?')">이 사업에 대해 어떻게 생각하세요?</button>
                <button class="chat-sug" @click="sendSuggestion(selected, '가장 중요한 의사결정 기준이 뭔가요?')">의사결정 기준이 뭔가요?</button>
                <button class="chat-sug" @click="sendSuggestion(selected, '경쟁사 대비 우리의 강점은?')">경쟁사 대비 우리의 강점은?</button>
              </div>
            </div>

            <div v-for="(msg, idx) in selected._chatMessages || []" :key="idx" class="chat-msg" :class="msg.role">
              <span class="msg-who">{{ msg.role === 'user' ? 'User' : selected.name }}</span>
              <div v-if="msg.role === 'assistant'" class="msg-bubble md-content" v-html="renderMd(msg.content)"></div>
              <div v-else class="msg-bubble">{{ msg.content }}</div>
            </div>

            <div v-if="chatLoading[selected.id]" class="chat-msg assistant">
              <span class="msg-who">{{ selected.name }}</span>
              <div class="msg-bubble typing">응답 생성 중...</div>
            </div>
          </div>

          <div class="chat-input-bar">
            <select v-model="selected._chatDbId" class="chat-db-select" :title="selected._chatDbId ? 'DB 연동됨' : 'DB 없음'">
              <option value="">DB 없음</option>
              <option v-for="col in dbStore.collections" :key="col.id" :value="col.id">📂 {{ col.name }}</option>
            </select>
            <input
              v-model="chatInput[selected.id]"
              class="chat-input"
              :placeholder="selected._chatDbId ? `${selected.name}에게 질문 (DB 연동)...` : `${selected.name}에게 질문...`"
              @keydown.enter="sendChat(selected)"
              :disabled="chatLoading[selected.id]"
            />
            <button class="chat-send" @click="sendChat(selected)" :disabled="!chatInput[selected.id]?.trim() || chatLoading[selected.id]">{{ t('common.send') }}</button>
          </div>
        </div>

        <!-- Bottom -->
        <div class="pv-bottom" v-if="selected.profile">
          <div class="bottom-info">
            <span v-if="selected.enabled" class="bottom-status">{{ t('persona.participating') }}</span>
            <span v-else class="bottom-hint">프로파일 완료. 시뮬레이션에 참여시키려면 버튼을 클릭하세요.</span>
          </div>
          <button class="bottom-btn" :class="{ active: selected.enabled }" @click="selected.enabled = !selected.enabled">
            {{ selected.enabled ? t('persona.leaveSim') : t('persona.joinSim') }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, nextTick } from 'vue'
import { useSettingsStore, type CustomAgent } from '../stores/settings'
import { useLLMStore } from '../stores/llm'
import { useDatabaseStore } from '../stores/database'
import { useI18n } from '../composables/useI18n'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

function renderMd(text: string): string {
  return marked.parse(text) as string
}

const settings = useSettingsStore()
const llmStore = useLLMStore()
const dbStore = useDatabaseStore()
const { t } = useI18n()

const selectedId = ref('')
const selected = computed(() => settings.customAgents.find(a => a.id === selectedId.value) || null)

// Options state
const sourceOptions = reactive<Record<string, { web: boolean; youtube: boolean }>>({})
const dateFrom = reactive<Record<string, string>>({})
const dateTo = reactive<Record<string, string>>({})

// Collect state — agent 객체에 직접 저장해서 페이지 이동해도 유지
const profileLoading = reactive<Record<string, boolean>>({})

// Chat state — chatMessages와 chatDbId는 agent 객체에 영속 저장
const chatInput = reactive<Record<string, string>>({})
const chatLoading = reactive<Record<string, boolean>>({})
const showSources = reactive<Record<string, boolean>>({})
const showProfile = reactive<Record<string, boolean>>({})
const chatMessagesRef = ref<HTMLElement>()

function dotColor(ca: CustomAgent) {
  if (ca.profile && ca.enabled) return '#000'
  if (ca.profile) return '#888'
  if (ca._crawlChunks) return '#bbb'
  return '#ddd'
}

function selectAgent(id: string) {
  selectedId.value = id
}

function addAgent() {
  settings.addCustomAgent()
  nextTick(() => {
    const last = settings.customAgents[settings.customAgents.length - 1]
    if (last) {
      selectedId.value = last.id
      sourceOptions[last.id] = { web: true, youtube: true }
    }
  })
}

function removeAgent(id: string) {
  settings.removeCustomAgent(id)
  if (selectedId.value === id) selectedId.value = settings.customAgents[0]?.id || ''
}

function toggleSource(id: string, src: 'web' | 'youtube') {
  if (!sourceOptions[id]) sourceOptions[id] = { web: true, youtube: true }
  sourceOptions[id][src] = !sourceOptions[id][src]
}

// Auto collect — agent 객체에 상태를 저장하여 페이지 이동해도 백그라운드 유지
async function startCollect(ca: CustomAgent) {
  if (!ca.name.trim()) return

  const agent = llmStore.enabledAgents[0]
  if (!agent?.apiKey) { ca._crawlError = 'LLM API 키를 설정하세요 (상단 LLM Model 버튼)'; return }

  ca._collecting = true
  ca._crawlError = ''
  ca._collectLog = [{ type: 'info', text: `"${ca.name}" 적응형 프로파일링 시작 — 필요한 정보가 채워질 때까지 자동 반복 검색` }]
  ca._searchResults = []

  const opts = sourceOptions[ca.id] || { web: true, youtube: true }
  const sources: string[] = []
  if (opts.web) sources.push('web')
  if (opts.youtube) sources.push('youtube')
  if (!sources.length) sources.push('web', 'youtube')

  try {
    // SSE 비동기 모드: /start → 즉시 응답 + /stream SSE로 진행 상황 수신
    ca._collectLog.push({ type: 'info', text: '검색 키워드 생성 + 초기 데이터 수집 중...' })
    const startRes = await fetch('/api/persona/auto-profile/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        person_name: ca.name,
        sources,
        date_from: dateFrom[ca.id] || null,
        date_to: dateTo[ca.id] || null,
        llm: { provider: agent.provider, model: agent.modelName, api_key: agent.apiKey, base_url: agent.baseUrl },
        max_iterations: 3,
      }),
    })
    if (!startRes.ok) {
      const errData = await startRes.json().catch(() => ({ detail: startRes.statusText }))
      throw new Error(errData.detail || '프로파일링 시작 실패')
    }
    const { task_id } = await startRes.json()

    // SSE 스트림 연결
    const data: any = await new Promise((resolve, reject) => {
      const es = new EventSource(`/api/persona/auto-profile/stream/${task_id}`, { withCredentials: true })
      es.onmessage = (event) => {
        try {
          const d = JSON.parse(event.data)
          if (d.type === 'progress') {
            if (!ca._collectLog) ca._collectLog = []
            ca._collectLog.push({ type: 'info', text: d.msg || '진행 중...' })
          } else if (d.type === 'completed') {
            es.close()
            resolve(d.result)
          } else if (d.type === 'failed') {
            es.close()
            reject(new Error(d.error || '프로파일링 실패'))
          } else if (d.type === 'timeout') {
            es.close()
            reject(new Error('프로파일링 시간 초과'))
          }
        } catch {}
      }
      es.onerror = () => {
        // SSE 재연결 시도 (브라우저 기본 동작)
      }
    })

    // 반복 이력 로그 표시
    ca._collectLog = []
    const iterations = data.iterations || []
    for (const iter of iterations) {
      const pct = Math.round((iter.coverage || 0) * 100)
      if (iter.phase === 'initial') {
        ca._collectLog.push({ type: 'ok', text: `[초기] ${iter.chunks}건 수집 → 커버리지 ${pct}%` })
      } else if (iter.phase === 'no_new_data') {
        ca._collectLog.push({ type: 'info', text: `[${iter.iteration}차] 추가 데이터 없음 — 종료` })
      } else {
        const missing = iter.missing?.length ? ` (부족: ${iter.missing.join(', ')})` : ''
        ca._collectLog.push({ type: 'ok', text: `[${iter.iteration}차 보충] +${iter.chunks}건 → 커버리지 ${pct}%${missing}` })
      }
    }

    const coveragePct = Math.round((data.coverage || 0) * 100)
    ca._collectLog.push({ type: 'ok', text: `✓ 프로파일 완료 — 총 ${data.total_chunks}건 수집, 커버리지 ${coveragePct}%` })

    // 크롤링 원본 데이터 저장
    ca._searchResults = data.search_results || []

    // 프로파일 자동 적용
    if (data.profile) {
      ca.profile = data.profile
      ca.role = data.profile.role || ca.role
      ca.persona = data.profile.personality || ca.persona
      ca._crawlChunks = data.total_chunks || 0
    }
  } catch (e: any) {
    ca._crawlError = (e as Error).message
    if (!ca._collectLog) ca._collectLog = []
    ca._collectLog.push({ type: 'fail', text: (e as Error).message })
  } finally {
    ca._collecting = false
  }
}

async function doProfile(ca: CustomAgent) {
  const agent = llmStore.enabledAgents[0]
  if (!agent?.apiKey) { ca._crawlError = 'LLM API 키를 설정하세요'; return }

  profileLoading[ca.id] = true
  ca._crawlError = ''

  try {
    const res = await fetch('/api/persona/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        person_name: ca.name,
        llm: { provider: agent.provider, model: agent.modelName, api_key: agent.apiKey, base_url: agent.baseUrl },
      }),
    })
    const text = await res.text()
    if (!text) throw new Error('서버 응답이 비어있습니다')
    let data: any
    try { data = JSON.parse(text) } catch { throw new Error('서버 응답 파싱 실패') }
    if (!res.ok) throw new Error(data.detail || '프로파일링 실패')
    ca.profile = data.profile
    ca.role = data.profile.role || ca.role
    ca.persona = data.profile.personality || ca.persona
  } catch (e: any) {
    ca._crawlError = (e as Error).message
  } finally {
    profileLoading[ca.id] = false
  }
}

// Chat
function scrollChat() {
  nextTick(() => { if (chatMessagesRef.value) chatMessagesRef.value.scrollTop = chatMessagesRef.value.scrollHeight })
}

async function sendSuggestion(ca: CustomAgent, text: string) {
  chatInput[ca.id] = text
  await sendChat(ca)
}

async function sendChat(ca: CustomAgent) {
  const text = (chatInput[ca.id] || '').trim()
  if (!text || chatLoading[ca.id]) return

  const agent = llmStore.enabledAgents[0]
  if (!agent?.apiKey) { ca._crawlError = 'LLM API 키를 설정하세요'; return }

  if (!ca._chatMessages) ca._chatMessages = []
  ca._chatMessages.push({ role: 'user', content: text })
  chatInput[ca.id] = ''
  chatLoading[ca.id] = true
  scrollChat()

  try {
    const res = await fetch('/api/persona/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        person_name: ca.name,
        profile: ca.profile,
        messages: ca._chatMessages,
        llm: { provider: agent.provider, model: agent.modelName, api_key: agent.apiKey, base_url: agent.baseUrl },
        db_project_id: ca._chatDbId || null,
      }),
    })
    const text = await res.text()
    if (!text) throw new Error('서버 응답이 비어있습니다')
    let data: any
    try { data = JSON.parse(text) } catch { throw new Error('응답 파싱 실패') }
    if (!res.ok) throw new Error(data.detail || '대화 실패')
    ca._chatMessages.push({ role: 'assistant', content: data.response })
  } catch (e: any) {
    if (!ca._chatMessages) ca._chatMessages = []
    ca._chatMessages.push({ role: 'assistant', content: `오류: ${(e as Error).message}` })
  } finally {
    chatLoading[ca.id] = false
    scrollChat()
  }
}
</script>

<style scoped>
button, input, select, textarea {
  font-family: 'Space Grotesk', sans-serif;
}

.persona-view { display: flex; height: 100%; }

/* ── Sidebar ── */
.pv-sidebar {
  width: 240px; flex-shrink: 0;
  border-right: 1px solid #EAEAEA;
  display: flex; flex-direction: column;
  background: #FAFAFA;
}

.pvs-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 16px 16px;
}

.pvs-title { font-size: 14px; font-weight: 700; color: #000; }

.pvs-add {
  width: 26px; height: 26px;
  border: 1px solid #EAEAEA; border-radius: 6px;
  background: #fff; font-size: 15px; color: #888;
  cursor: pointer; display: grid; place-items: center;
  transition: all 0.15s;
}
.pvs-add:hover { border-color: #000; color: #000; }

.pvs-empty { padding: 16px; }
.pvs-empty-steps { display: flex; flex-direction: column; gap: 8px; }
.pvs-step { font-size: 11px; color: #AAA; display: flex; align-items: center; gap: 8px; font-family: 'Space Grotesk', sans-serif; }
.pvs-sn {
  width: 16px; height: 16px; border-radius: 50%;
  background: #000; color: #fff; font-size: 9px; font-weight: 700;
  display: grid; place-items: center; flex-shrink: 0;
}

.pvs-list { flex: 1; overflow-y: auto; padding: 4px 8px; display: flex; flex-direction: column; gap: 1px; }

.pvs-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px;
  cursor: pointer; transition: all 0.12s;
  border: 1px solid transparent;
  background: transparent; text-align: left; width: 100%;
}
.pvs-item:hover { background: #F0F0F0; }
.pvs-item.active { background: #fff; border-color: #EAEAEA; }

.pvs-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.pvs-item-body { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.pvs-item-name { font-size: 13px; font-weight: 600; color: #222; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pvs-item-sub { font-size: 10px; color: #BBB; }

/* ── Main ── */
.pv-main { flex: 1; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }

.pv-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 8px; }
.pv-empty-icon { font-size: 40px; opacity: 0.3; }
.pv-empty-title { font-size: 14px; color: #888; font-weight: 600; }
.pv-empty-desc { font-size: 12px; color: #BBB; max-width: 360px; text-align: center; line-height: 1.6; }
.pv-empty-btn {
  margin-top: 12px; padding: 10px 24px;
  border: 1px solid #EAEAEA; border-radius: 8px;
  background: #fff; font-size: 13px; font-weight: 600; color: #888;
  cursor: pointer; transition: all 0.15s;
}
.pv-empty-btn:hover { border-color: #000; color: #000; }

/* ── Top Bar (unified row) ── */
.pv-topbar {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 24px; border-bottom: 1px solid #EAEAEA; flex-shrink: 0;
  flex-wrap: wrap;
}

.topbar-name {
  border: none; border-bottom: 1px solid #EAEAEA;
  padding: 4px 0; font-size: 16px; font-weight: 700;
  outline: none; color: #000; background: transparent;
  width: 180px; flex-shrink: 0;
}
.topbar-name:focus { border-bottom-color: #000; }
.topbar-name:disabled { border-bottom-color: transparent; color: #000; }

.topbar-role { font-size: 11px; color: #888; font-family: 'JetBrains Mono', monospace; }

.topbar-sep { width: 1px; height: 20px; background: #EAEAEA; flex-shrink: 0; }
.topbar-spacer { flex: 1; }

.topbar-pill {
  padding: 5px 12px; border: 1px solid #EAEAEA; border-radius: 6px;
  background: #fff; font-size: 12px; font-weight: 500; color: #CCC;
  cursor: pointer; transition: all 0.15s;
  text-decoration: line-through;
}
.topbar-pill.on { border-color: #222; color: #222; background: #222; color: #fff; text-decoration: none; }
.topbar-pill:hover { border-color: #888; }

.topbar-date {
  border: 1px solid #EAEAEA; border-radius: 6px;
  padding: 5px 8px; font-size: 11px; color: #555;
  font-family: 'JetBrains Mono', monospace;
  outline: none; transition: border-color 0.15s;
}
.topbar-date:focus { border-color: #000; }
.topbar-date-sep { color: #CCC; font-size: 11px; }

.topbar-btn {
  padding: 6px 16px; border-radius: 6px;
  font-size: 12px; font-weight: 600; cursor: pointer;
  transition: all 0.15s; white-space: nowrap;
}
.topbar-btn.primary { border: 1px solid #222; background: #222; color: #fff; }
.topbar-btn.primary:hover { background: #444; }
.topbar-btn.primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-spinner {
  display: inline-block; width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff;
  border-radius: 50%; animation: spin 0.8s linear infinite;
  vertical-align: middle; margin-right: 4px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.topbar-btn.ghost { border: 1px solid #EAEAEA; background: #fff; color: #BBB; }
.topbar-btn.ghost:hover { color: #E53935; border-color: #FFCDD2; }

/* ── Collect Section ── */
.pv-collect {
  padding: 14px 24px; border-bottom: 1px solid #EAEAEA;
  display: flex; flex-direction: column; gap: 12px; flex-shrink: 0;
}

.collect-log { display: flex; flex-direction: column; gap: 3px; }
.collect-log-item { font-size: 12px; color: #555; display: flex; align-items: center; gap: 6px; padding: 2px 0; }
.collect-log-item .log-icon { font-size: 11px; width: 14px; text-align: center; flex-shrink: 0; }
.collect-log-item .log-text { font-family: 'Space Grotesk', sans-serif; }
.collect-log-item.ok .log-icon { color: #222; }
.collect-log-item.fail .log-icon { color: #E53935; }
.collect-log-item.info .log-icon { color: #AAA; }

.search-results { display: flex; flex-direction: column; gap: 6px; }
.sr-label { font-size: 10px; color: #AAA; font-weight: 600; letter-spacing: 0.3px; }
.sr-list { display: flex; flex-direction: column; gap: 3px; }
.sr-item { display: flex; align-items: center; gap: 8px; padding: 2px 0; }
.sr-badge { padding: 1px 5px; border-radius: 3px; font-size: 9px; font-weight: 700; }
.sr-badge.web { background: #222; color: #fff; }
.sr-badge.youtube { background: #888; color: #fff; }
.sr-text { font-size: 12px; color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.collect-done {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 14px; background: #FAFAFA; border: 1px solid #EAEAEA; border-radius: 8px;
}
.collect-done-text { font-size: 12px; color: #555; }

.pv-error { font-size: 12px; color: #E53935; padding: 6px 10px; background: #FFF5F5; border-radius: 6px; }

/* ── Profile ── */
.pv-profile-wrap { border-bottom: 1px solid #EAEAEA; flex-shrink: 0; }
.profile-toggle {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 24px; cursor: pointer; transition: background 0.1s;
}
.profile-toggle:hover { background: #F7F7F7; }
.profile-toggle-label { font-size: 11px; font-weight: 700; color: #999; letter-spacing: 0.5px; text-transform: uppercase; }
.profile-toggle-arrow { font-size: 10px; color: #CCC; }
.pv-profile {
  padding: 0 24px 16px; overflow-y: auto; max-height: 220px;
}

.profile-section { display: flex; flex-direction: column; gap: 12px; }
.profile-row { display: flex; gap: 16px; }
.profile-field { flex: 1; display: flex; flex-direction: column; gap: 3px; }
.profile-field.full { flex: unset; width: 100%; }
.pf-label { font-size: 11px; font-weight: 700; color: #999; letter-spacing: 0.2px; font-family: 'Space Grotesk', sans-serif; }
.pf-value { font-size: 13px; color: #333; line-height: 1.6; font-family: 'Space Grotesk', sans-serif; }

.pf-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.pf-tag { padding: 3px 10px; background: #F0F0F0; border-radius: 4px; font-size: 12px; color: #444; font-family: 'Space Grotesk', sans-serif; }

.pf-list { display: flex; flex-direction: column; gap: 2px; margin-top: 2px; }
.pf-list-item { font-size: 12px; color: #444; padding-left: 10px; position: relative; font-family: 'Space Grotesk', sans-serif; }
.pf-list-item::before { content: '·'; position: absolute; left: 0; color: #CCC; }
.pf-list-item.warn { color: #888; }

.pf-stances { display: flex; flex-direction: column; gap: 4px; margin-top: 2px; }
.pf-stance { display: flex; gap: 8px; align-items: baseline; }
.stance-topic { font-size: 12px; color: #222; font-weight: 700; flex-shrink: 0; font-family: 'Space Grotesk', sans-serif; }
.stance-val { font-size: 12px; color: #555; font-family: 'Space Grotesk', sans-serif; }

.profile-meta { font-size: 11px; color: #BBB; margin-top: 4px; font-family: 'Space Grotesk', sans-serif; }

/* ── Chat ── */
.pv-chat { flex: 1; display: flex; flex-direction: column; min-height: 0; }

.chat-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 24px; border-bottom: 1px solid #F0F0F0; flex-shrink: 0;
}
.chat-bar-title { font-size: 13px; font-weight: 600; color: #222; font-family: 'Space Grotesk', sans-serif; }
.chat-bar-hint { font-size: 11px; color: #BBB; font-family: 'Space Grotesk', sans-serif; }

.chat-messages { flex: 1; overflow-y: auto; padding: 16px 24px; display: flex; flex-direction: column; gap: 14px; }
.chat-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 14px; }
.chat-empty-text { font-size: 13px; color: #BBB; font-family: 'Space Grotesk', sans-serif; }

.chat-suggests { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; max-width: 480px; }
.chat-sug {
  padding: 7px 14px; border: 1px solid #EAEAEA; border-radius: 20px;
  background: #fff; font-size: 12px; color: #888;
  cursor: pointer; transition: all 0.15s;
}
.chat-sug:hover { border-color: #000; color: #000; }

.chat-msg { max-width: 75%; }
.chat-msg.user { align-self: flex-end; }
.chat-msg.assistant { align-self: flex-start; }

.msg-who { font-size: 11px; color: #999; margin-bottom: 3px; display: block; font-family: 'Space Grotesk', sans-serif; font-weight: 600; }
.chat-msg.user .msg-who { text-align: right; }

.msg-bubble { padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.6; font-family: 'Space Grotesk', sans-serif; }
.chat-msg.user .msg-bubble { background: #222; color: #fff; border-bottom-right-radius: 4px; }
.chat-msg.assistant .msg-bubble { background: #F5F5F5; color: #333; border-bottom-left-radius: 4px; }
.msg-bubble.typing { color: #AAA; font-style: italic; }

.chat-input-bar { display: flex; gap: 8px; padding: 12px 24px; border-top: 1px solid #EAEAEA; flex-shrink: 0; align-items: center; }
.chat-db-select {
  flex-shrink: 0; border: 1px solid #EAEAEA; border-radius: 6px;
  padding: 8px 8px; font-size: 11px; color: #666; background: #FAFAFA;
  outline: none; cursor: pointer; max-width: 120px;
  font-family: 'Space Grotesk', sans-serif;
}
.chat-db-select:focus { border-color: #000; }
.chat-input {
  flex: 1; border: 1px solid #EAEAEA; border-radius: 8px;
  padding: 10px 14px; font-size: 13px; outline: none; color: #333;
  transition: border-color 0.15s;
}
.chat-input:focus { border-color: #000; }

.chat-send {
  padding: 10px 20px; border: none; border-radius: 8px;
  background: #000; color: #fff; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.15s;
}
.chat-send:hover { background: #333; }
.chat-send:disabled { opacity: 0.3; cursor: not-allowed; }

/* ── Bottom ── */
.pv-bottom {
  padding: 12px 24px; border-top: 1px solid #EAEAEA;
  display: flex; align-items: center; justify-content: space-between;
  flex-shrink: 0; background: #FAFAFA;
}
.bottom-info { display: flex; flex-direction: column; gap: 2px; }
.bottom-status { font-size: 12px; font-weight: 600; color: #222; font-family: 'Space Grotesk', sans-serif; }
.bottom-hint { font-size: 12px; color: #AAA; font-family: 'Space Grotesk', sans-serif; }

.bottom-btn {
  padding: 9px 24px; border: none; border-radius: 8px;
  font-size: 13px; font-weight: 700; cursor: pointer;
  transition: all 0.15s; white-space: nowrap;
  background: #000; color: #fff;
}
.bottom-btn:hover { background: #333; }
.bottom-btn.active { background: #FAFAFA; color: #AAA; border: 1px solid #EAEAEA; }
.bottom-btn.active:hover { color: #E53935; border-color: #FFCDD2; }

/* ── Sources Panel ── */
.sources-panel {
  padding: 12px 24px; border-bottom: 1px solid #EAEAEA; background: #FAFAFA;
  max-height: 280px; overflow-y: auto;
}
.sources-title { font-size: 12px; font-weight: 700; color: #555; margin-bottom: 8px; }
.sources-count { color: #999; font-weight: 400; }
.sources-list { display: flex; flex-direction: column; gap: 6px; }
.source-item {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 8px 12px; border: 1px solid #EAEAEA; border-radius: 8px;
  background: #fff; text-decoration: none; color: inherit;
  transition: border-color 0.15s;
}
.source-item:hover { border-color: #999; }
.source-badge {
  flex-shrink: 0; padding: 2px 6px; border-radius: 4px;
  font-size: 9px; font-weight: 700; margin-top: 2px;
}
.source-badge.web { background: #222; color: #fff; }
.source-badge.youtube { background: #c00; color: #fff; }
.source-info { flex: 1; min-width: 0; }
.source-title { font-size: 13px; color: #333; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.source-url { font-size: 11px; color: #aaa; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }

.topbar-btn.danger { color: #E53935; }
.topbar-btn.danger:hover { background: #FFF5F5; border-color: #FFCDD2; }

.mono { font-family: 'JetBrains Mono', monospace; }

/* ── Markdown 렌더링 ── */
.md-content :deep(h1) { font-size: 15px; font-weight: 700; margin: 8px 0 4px; color: #111; }
.md-content :deep(h2) { font-size: 14px; font-weight: 700; margin: 8px 0 4px; color: #222; }
.md-content :deep(h3) { font-size: 13px; font-weight: 700; margin: 6px 0 3px; color: #333; }
.md-content :deep(p) { margin: 3px 0; line-height: 1.6; }
.md-content :deep(ul), .md-content :deep(ol) { margin: 3px 0; padding-left: 18px; }
.md-content :deep(li) { margin: 2px 0; line-height: 1.5; }
.md-content :deep(strong) { font-weight: 700; color: #111; }
.md-content :deep(code) { background: rgba(0,0,0,0.06); padding: 1px 5px; border-radius: 3px; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.md-content :deep(table) { width: 100%; border-collapse: collapse; margin: 6px 0; font-size: 12px; }
.md-content :deep(th), .md-content :deep(td) { border: 1px solid #e0e0e0; padding: 4px 8px; text-align: left; }
.md-content :deep(th) { background: #f5f5f5; font-weight: 600; }
</style>

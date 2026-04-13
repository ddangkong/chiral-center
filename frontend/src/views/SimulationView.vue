<template>
  <div class="simulation-view">

    <!-- Config Bar -->
    <div class="config-bar">
      <div class="config-left">
        <span class="config-label">{{ t('sim.rounds') }}</span>
        <div class="round-control">
          <button class="round-btn" @click="rounds = Math.max(1, rounds - 1)">−</button>
          <span class="round-num mono">{{ rounds }}</span>
          <button class="round-btn" @click="rounds++">+</button>
        </div>
        <span class="config-label" :title="t('sim.dynamicRolesTooltip')">{{ t('sim.dynamicRoles') }}</span>
        <div class="round-control">
          <button class="round-btn" @click="maxPersonas = Math.max(0, maxPersonas - 1)">−</button>
          <span class="round-num mono">{{ maxPersonas }}</span>
          <button class="round-btn" @click="maxPersonas++">+</button>
        </div>
        <span class="agent-breakdown mono" :title="breakdownTitle">
          = {{ t('sim.totalAgents') }} {{ totalParticipants }}{{ t('sim.people') }}
          <span class="agent-breakdown-detail">({{ t('sim.fixed') }} {{ fixedSpeakerCount }} + {{ t('sim.dynamic') }} {{ maxPersonas }}{{ entityCount ? ' + ' + t('sim.entity') + ' ' + entityCount : '' }}{{ customCount ? ' + ' + t('sim.custom') + ' ' + customCount : '' }})</span>
        </span>
        <span class="config-label">{{ t('sim.current') }}</span>
        <span class="current-round mono">{{ currentRound }} / {{ displayedTotalRounds }}</span>
      </div>
      <div class="config-right">
        <!-- 온톨로지 버전 선택 -->
        <div v-if="projectStore.currentProject && projectStore.currentProject.ontologies.length > 1" class="onto-picker">
          <span class="onto-picker-label mono">{{ t('sim.ontology') }}</span>
          <select class="onto-picker-select" v-model="selectedOntologyId">
            <option v-for="o in projectStore.currentProject.ontologies" :key="o.id" :value="o.id">
              v{{ o.version }} · {{ o.nodeCount }}n/{{ o.edgeCount }}e · {{ o.model }}
            </option>
          </select>
        </div>
        <div class="sim-options-wrap">
          <button class="btn-sim-opts" @click="showSimOpts = !showSimOpts" title="시뮬레이션 옵션">⚙</button>
          <div v-if="showSimOpts" class="sim-opts-popup">
            <div class="sim-opts-title">{{ t('sim.options') }}</div>
            <div class="sim-opts-row">
              <span class="sim-opts-label">{{ t('sim.creativity') }}</span>
              <div class="sim-opts-pills">
                <button v-for="t in tempOptions" :key="t.value" class="sim-opts-pill"
                  :class="{ active: simTemperature === t.value }" @click="simTemperature = t.value">{{ t.label }}</button>
              </div>
            </div>
            <div class="sim-opts-row">
              <span class="sim-opts-label">{{ t('sim.minChars') }}</span>
              <input type="number" v-model.number="simMinChars" class="sim-opts-input mono" min="100" max="5000" step="100" />
            </div>
            <div class="sim-opts-row">
              <span class="sim-opts-label">{{ t('sim.maxChars') }}</span>
              <input type="number" v-model.number="simMaxChars" class="sim-opts-input mono" min="500" max="10000" step="500" />
            </div>
            <div class="sim-opts-hint mono">창의성: 낮음=보수적, 중간=균형, 높음=자유로운 답변</div>
          </div>
        </div>
        <button class="btn-sim" :class="{ running: isRunning }" @click="toggleSim">
          {{ isRunning ? t('sim.stop') : t('sim.start') }}
        </button>
      </div>
    </div>

    <!-- Topic Bar -->
    <div class="topic-bar">
      <span class="topic-label">{{ t('sim.topic') }}</span>
      <input
        class="topic-input"
        v-model="topicText"
        :placeholder="docStore.ontologyTopic || t('sim.topicPlaceholder')"
        :disabled="isRunning"
      />
      <span v-if="isRunning && !topicText" class="topic-display">{{ docStore.ontologyTopic }}</span>
      <div v-if="simHistory.length > 0 && !isRunning" class="sim-history-wrap">
        <select class="sim-history-select" @change="onLoadHistory($event)">
          <option value="" disabled selected>이전 대화</option>
          <option v-for="h in simHistory" :key="h.id" :value="h.id">
            {{ h.topic?.slice(0, 30) || '(주제 없음)' }} · {{ h.rounds }}R · {{ h.version }}
          </option>
        </select>
      </div>
    </div>

    <div class="sim-layout">

      <!-- Left: Agent List -->
      <div class="agent-panel">
        <div class="panel-header">
          <span class="panel-title">{{ t('sim.agentList') }}</span>
          <div style="display:flex;align-items:center;gap:8px;">
            <span class="panel-count mono">{{ agents.length }}</span>
            <button v-if="activeAgent" class="btn-clear-agent" @click="activeAgent = ''">전체</button>
          </div>
        </div>

        <!-- Entity Participants Selector -->
        <div v-if="!isRunning" class="entity-selector">
          <div class="entity-toggle">
            <span class="entity-toggle-icon">🔗</span>
            <span class="entity-toggle-label" @click="entityListOpen = !entityListOpen">{{ t('sim.entityParticipants') }}</span>
            <span v-if="entityMode && selectedEntityIds.length > 0" class="entity-sel-count mono" @click="entityListOpen = !entityListOpen">{{ selectedEntityIds.length }}개</span>
            <span class="entity-toggle-switch" :class="{ on: entityMode }" @click.stop="entityMode = !entityMode">{{ entityMode ? 'ON' : 'OFF' }}</span>
          </div>
          <div v-if="entityMode && entityListOpen" class="entity-expand">
            <div v-if="entityLoading" class="entity-empty mono">엔티티 로딩 중...</div>
            <div v-else-if="entityCandidates.length === 0" class="entity-empty mono">
              지식그래프를 먼저 추출하세요
            </div>
            <div v-else class="entity-list">
              <div
                v-for="ent in entityCandidates"
                :key="ent.id"
                class="entity-item"
                @click="toggleEntity(ent.id)"
              >
                <input type="checkbox" :checked="selectedEntityIds.includes(ent.id)" class="entity-check" @click.stop="toggleEntity(ent.id)" />
                <div class="entity-item-info">
                  <span class="entity-item-name">{{ ent.name }}</span>
                  <span class="entity-item-type mono">{{ ent.type }}</span>
                </div>
                <span class="entity-degree mono">{{ ent.degree }}r</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Loading State -->
        <div v-if="isRunning && agents.length === 0" class="agent-loading">
          <div class="agent-loading-spinner"></div>
          <div class="agent-loading-text">{{ t('sim.generatingPersonas') }}</div>
          <div class="agent-loading-desc">LLM이 에이전트를 생성하고 있습니다</div>
        </div>

        <!-- Empty State -->
        <div v-else-if="!isRunning && agents.length === 0" class="agent-empty">
          <div class="agent-empty-icon">👥</div>
          <div class="agent-empty-text" v-html="t('sim.emptyAgents').replace('\\n', '<br>')"></div>
        </div>

        <div class="agent-list" v-else>
          <div
            v-for="agent in agents"
            :key="agent.id"
            class="agent-card"
            :class="{ active: activeAgent === agent.id }"
            @click="activeAgent = agent.id"
          >
            <div class="agent-avatar" :style="{ background: agent.color }">
              {{ agent.initials }}
            </div>
            <div class="agent-info">
              <div class="agent-name">{{ agent.name }}</div>
              <div class="agent-role">{{ agent.role }}</div>
            </div>
            <div class="stance-badge" :class="agent.stance">
              {{ stanceLabel(agent.stance) }}
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Event Feed -->
      <div class="event-panel">

        <div class="tw-header">
          <div class="tw-header-left">
            <span class="tw-header-title">{{ t('sim.discussion') }}</span>
          </div>
          <button class="event-ctrl-btn tw-clear" @click="clearLog">{{ t('sim.clear') }}</button>
        </div>

        <!-- ── Feed ── -->
        <div class="event-feed" ref="feedEl">
          <template v-for="(item, idx) in eventLog" :key="idx">

            <!-- Round Separator -->
            <div v-if="item.type === 'round'" class="round-separator">
              <span class="round-sep-line"></span>
              <span class="round-sep-label mono">Round {{ item.round }}</span>
              <span class="round-sep-line"></span>
            </div>

            <!-- ── Moderator Card ── -->
            <div v-else-if="item.agentId === '__moderator__'" class="moderator-card"
              :class="{ dimmed: activeAgent }">
              <div class="mod-icon">⚖️</div>
              <div class="mod-body">
                <div class="mod-label mono">MODERATOR · Round {{ item.round }}</div>
                <div class="mod-content">{{ item.content }}</div>
              </div>
            </div>

            <!-- ── DB Agent Card ── -->
            <div v-else-if="item.agentId === '__db_agent__'" class="db-agent-card"
              :class="{ dimmed: activeAgent }">
              <div class="db-agent-icon">🗄️</div>
              <div class="db-agent-body">
                <div class="db-agent-label mono">DB AGENT · Round {{ item.round }}</div>
                <div class="db-agent-content">{{ item.content }}</div>
              </div>
            </div>

            <div v-else class="disc-card"
              :class="{ highlighted: activeAgent && item.agentId === activeAgent, dimmed: activeAgent && item.agentId !== activeAgent }"
              @click="activeAgent = activeAgent === item.agentId ? '' : (item.agentId || '')">
              <div class="disc-header">
                <div class="disc-avatar" :style="{ background: getAgent(item.agentId)?.color || '#FF5722' }">
                  {{ getAgent(item.agentId)?.initials || '?' }}
                </div>
                <div class="disc-meta">
                  <span class="disc-name">{{ item.agentName }}</span>
                  <span class="disc-role" v-if="getAgent(item.agentId)?.role">{{ getAgent(item.agentId)?.role }}</span>
                </div>
                <span class="disc-action-badge" :class="item.action">{{ {post:'발언',reply:'응답',question:'질문',concede:'양보',propose:'제안',cite:'인용',moderator:'진행',skip:'패스',repost:'공유'}[item.action || ''] || item.action }}</span>
                <span class="disc-time mono">{{ item.time }}</span>
              </div>
              <div class="disc-content">{{ item.content }}</div>
            </div>

          </template>
          <div v-if="isRunning" class="event-cursor mono">▋</div>

          <!-- ── Q&A Section (시뮬레이션 완료 후) ── -->
          <template v-if="qaMessages.length > 0 || (!isRunning && eventLog.length > 0)">
            <div v-if="qaMessages.length > 0" class="qa-separator">
              <span class="qa-sep-line"></span>
              <span class="qa-sep-label mono">{{ t('sim.qaTitle') }}</span>
              <span class="qa-sep-line"></span>
            </div>

            <template v-for="msg in qaMessages" :key="msg.id">
              <!-- 질문 카드 -->
              <div v-if="msg.type === 'question'" class="qa-card qa-question">
                <div class="qa-header">
                  <div class="qa-avatar qa-user-avatar">Q</div>
                  <div class="qa-meta">
                    <span class="qa-sender">사용자 질문</span>
                    <span class="qa-time mono">{{ msg.timestamp }}</span>
                  </div>
                </div>
                <div class="qa-content">{{ msg.content }}</div>
              </div>

              <!-- 답변 카드 -->
              <div v-else class="qa-card qa-answer">
                <div class="qa-header">
                  <div class="qa-avatar qa-ai-avatar">AI</div>
                  <div class="qa-meta">
                    <span class="qa-sender">분석 AI</span>
                    <span class="qa-time mono">{{ msg.timestamp }}</span>
                  </div>
                  <div v-if="msg.referencedAgents && msg.referencedAgents.length > 0" class="qa-refs">
                    <span v-for="name in msg.referencedAgents" :key="name" class="qa-ref-badge mono">{{ name }}</span>
                  </div>
                </div>
                <div class="qa-content" v-html="formatQAAnswer(msg.content)"></div>
              </div>
            </template>

            <!-- 로딩 인디케이터 -->
            <div v-if="simStore.isQALoading" class="qa-loading">
              <div class="qa-loading-spinner"></div>
              <span class="qa-loading-text">{{ t('sim.qaLoading') }}</span>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- DB Setup Modal -->
    <DBSetupModal
      :visible="showDbModal"
      :project-id="projectStore.currentProjectId ?? ''"
      @skip="runSimWithDb(null)"
      @confirm="runSimWithDb"
    />

    <!-- Progress Bar: 실행 중에만 표시. 종료 후에는 qa-input-bar에게 공간 양보. -->
    <div v-if="isRunning" class="progress-bar-outer">
      <div class="progress-info">
        <span class="mono">Round {{ currentRound }} / {{ displayedTotalRounds }}</span>
        <span class="mono">{{ Math.round((currentRound / Math.max(1, displayedTotalRounds)) * 100) }}%</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: (currentRound / Math.max(1, displayedTotalRounds)) * 100 + '%' }"></div>
      </div>
    </div>

    <!-- Q&A Input Bar -->
    <div v-if="!isRunning && eventLog.length > 0" class="qa-input-bar">
      <textarea
        ref="qaInputEl"
        class="qa-input"
        v-model="qaInput"
        :placeholder="t('sim.qaPlaceholder')"
        rows="1"
        :disabled="simStore.isQALoading"
        @keydown="onQAKeydown"
        @input="autoResizeQAInput"
      ></textarea>
      <button
        class="qa-send-btn"
        :disabled="!qaInput.trim() || simStore.isQALoading"
        @click="sendQA"
      >→</button>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useLLMStore } from '../stores/llm'
import { useDocumentStore } from '../stores/document'
import { useSimulationStore } from '../stores/simulation'
import { useProjectStore } from '../stores/project'
import { useSettingsStore } from '../stores/settings'
import { useI18n } from '../composables/useI18n'
import DBSetupModal from '../components/DBSetupModal.vue'

const llmStore = useLLMStore()
const docStore = useDocumentStore()
const simStore = useSimulationStore()
const projectStore = useProjectStore()
const { t } = useI18n()

const showDbModal = ref(false)
const showSimOpts = ref(false)
const simTemperature = ref(parseFloat(localStorage.getItem('simTemperature') || '0.7'))
const simMinChars = ref(parseInt(localStorage.getItem('simMinChars') || '1500'))
const simMaxChars = ref(parseInt(localStorage.getItem('simMaxChars') || '5000'))

watch(simTemperature, v => localStorage.setItem('simTemperature', String(v)))
watch(simMinChars, v => localStorage.setItem('simMinChars', String(v)))
watch(simMaxChars, v => localStorage.setItem('simMaxChars', String(v)))
const tempOptions = computed(() => [
  { label: t('sim.low'), value: 0.3 },
  { label: t('sim.mid'), value: 0.7 },
  { label: t('sim.high'), value: 1.0 },
])

// 기반 온톨로지 선택
const selectedOntologyId = computed({
  get: () => projectStore.currentProject?.activeOntologyId ?? docStore.ontologyId,
  set: (v) => { if (projectStore.currentProject) projectStore.setActiveOntology(v) },
})

// rounds / maxPersonas / topicText 는 새로고침에도 유지되도록 localStorage에 저장.
// 이전에는 순수 ref()였기에 HMR 리로드·뒤로가기 등에서 사용자가 조정한 값이 사라졌다.
function _readNum(key: string, def: number, min: number, max: number): number {
  const raw = localStorage.getItem(key)
  if (raw === null) return def
  const n = Number(raw)
  if (!Number.isFinite(n)) return def
  return Math.min(max, Math.max(min, Math.trunc(n)))
}
const rounds = ref<number>(_readNum('sim_rounds', 10, 1, 100))
const maxPersonas = ref<number>(_readNum('sim_max_personas', 10, 0, 50))
const topicText = ref<string>(localStorage.getItem('sim_topic_text') || '')

watch(rounds, (v) => localStorage.setItem('sim_rounds', String(v)))
watch(maxPersonas, (v) => localStorage.setItem('sim_max_personas', String(v)))
watch(topicText, (v) => localStorage.setItem('sim_topic_text', v))
const currentRound = computed(() => simStore.currentRound)
const isRunning = computed(() => simStore.isRunning)
const agents = computed(() => simStore.agents)
const eventLog = computed(() => simStore.eventLog)
const activeAgent = ref('')
const feedEl = ref<HTMLElement | null>(null)

// 라운드 표시는 단일 소스 — 시뮬 복원 상태가 있으면 그걸 우선, 없으면 로컬 rounds를 사용.
// 이전에는 로컬 rounds만 사용해서 히스토리 복원 시 mismatch 발생했음.
const displayedTotalRounds = computed(() => {
  const t = simStore.totalRounds
  // 복원된 시뮬이 있고 그 라운드 수가 의미 있으면 그걸 우선
  if (simStore.simId && t && t > 0) return t
  return rounds.value
})

// 백엔드에서 start broadcast에 포함되는 고정 역할만 카운트.
// create_fixed_role_agents(): 5 core (must_speak=true) + must_speak support(악마의 변호인, 진행자).
// db_agent, price_research는 must_speak=false라 start 목록에 안 들어가고 조건부 발언만 함.
const FIXED_BROADCAST_ROLES = new Set([
  'market_analyst',
  'financial_analyst',
  'tech_reviewer',
  'risk_analyst',
  'strategy_lead',
  'devils_advocate',
  'moderator',
])

const fixedSpeakerCount = computed(() => {
  const s = useSettingsStore()
  return s.agentPrompts.filter(a => a.enabled && FIXED_BROADCAST_ROLES.has(a.role)).length
})

const entityCount = computed(() => entityMode.value ? selectedEntityIds.value.length : 0)
const customCount = computed(() => {
  const s = useSettingsStore()
  return s.customAgents.filter(a => a.enabled && a.profile).length
})

const totalParticipants = computed(
  () => fixedSpeakerCount.value + maxPersonas.value + entityCount.value + customCount.value,
)

const breakdownTitle = computed(() =>
  `${t('sim.fixed')} ${fixedSpeakerCount.value}${t('sim.people')} + ${t('sim.dynamic')} ${maxPersonas.value}${t('sim.people')} + ${t('sim.entity')} ${entityCount.value}${t('sim.people')} + ${t('sim.custom')} ${customCount.value}${t('sim.people')} = ${t('sim.totalAgents')} ${totalParticipants.value}${t('sim.people')}\n\n${t('sim.fixedRoleToggle')}`,
)

// Auto-scroll: 사용자가 하단 근처에 있을 때만 (읽는 중이면 방해 안 함)
function isNearBottom(): boolean {
  const el = feedEl.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 150
}

watch(() => simStore.eventLog.length, () => {
  if (isNearBottom()) {
    nextTick(() => { if (feedEl.value) feedEl.value.scrollTop = feedEl.value.scrollHeight })
  }
})
watch(() => simStore.qaMessages.length, () => {
  if (isNearBottom()) {
    nextTick(() => { if (feedEl.value) feedEl.value.scrollTop = feedEl.value.scrollHeight })
  }
})

// 이전 시뮬레이션 히스토리
const simHistory = computed(() => {
  const p = projectStore.currentProject
  if (!p) return []
  return [...p.simulations].reverse()
})

function onLoadHistory(e: Event) {
  const selectedSimId = (e.target as HTMLSelectElement).value
  if (!selectedSimId) return
  const p = projectStore.currentProject
  if (!p) return
  const sim = p.simulations.find(s => s.id === selectedSimId)
  if (sim) {
    projectStore.setActiveSimulation(selectedSimId)
    // 시뮬별 독립 스냅샷을 복원. config가 있으면 UI 입력값도 같이 복구.
    const config = simStore.loadSimulation(p.id, selectedSimId)
    if (config) {
      if (typeof config.rounds === 'number') rounds.value = config.rounds
      if (typeof config.maxPersonas === 'number') maxPersonas.value = config.maxPersonas
      if (typeof config.topic === 'string') topicText.value = config.topic
      if (typeof config.entityMode === 'boolean') entityMode.value = config.entityMode
      if (Array.isArray(config.selectedEntityIds)) selectedEntityIds.value = config.selectedEntityIds
    } else {
      // 레거시 스냅샷: config가 없으면 simStore.totalRounds 기준으로 라운드만 복원
      if (simStore.totalRounds) rounds.value = simStore.totalRounds
      topicText.value = sim.topic || ''
    }
  }
  // 드롭다운 리셋
  ;(e.target as HTMLSelectElement).value = ''
}

function stanceLabel(stance: string): string {
  const map: Record<string, string> = { supportive: t('sim.supportive'), opposing: t('sim.opposing'), neutral: t('sim.neutral') }
  return map[stance] || stance
}

function getAgent(id: string | undefined) {
  return simStore.getAgent(id)
}

// 시뮬레이션 시작 시점에 엔티티 선택 상태를 캡처
const _capturedEntityIds = ref<string[]>([])

function toggleSim() {
  if (isRunning.value) {
    simStore.stopSimulation()
    return
  }

  // Validate
  const ontId = selectedOntologyId.value
  if (!ontId) {
    alert('온톨로지가 없습니다. 분할 탭에서 먼저 문서를 업로드하고 추출해주세요.')
    return
  }
  const agent = llmStore.enabledAgents[0]
  if (!agent || !agent.apiKey) {
    alert('LLM 모델과 API 키를 상단 LLM Model에서 설정해주세요.')
    return
  }

  // 엔티티 선택 상태 캡처 (DB 모달 중에 리셋되지 않도록)
  _capturedEntityIds.value = entityMode.value && selectedEntityIds.value.length > 0
    ? [...selectedEntityIds.value]
    : []

  showDbModal.value = true
}

async function runSimWithDb(dbId: string | null) {
  showDbModal.value = false
  const ontId = selectedOntologyId.value
  const agent = llmStore.enabledAgents[0]
  if (!ontId || !agent) return

  const entityIds = _capturedEntityIds.value.length > 0 ? _capturedEntityIds.value : undefined
  console.log('[SIM] entity_personas:', entityIds, 'entityMode:', entityMode.value, 'selected:', selectedEntityIds.value)

  await simStore.runSimulation(
    ontId,
    topicText.value.trim() || docStore.ontologyTopic || '',
    rounds.value,
    maxPersonas.value,
    {
      provider: agent.provider,
      model: agent.modelName,
      api_key: agent.apiKey,
      base_url: agent.baseUrl || undefined,
    },
    entityIds,
    { temperature: simTemperature.value, min_chars: simMinChars.value, max_chars: simMaxChars.value },
  )
}

// ── Entity Participants (localStorage에 상태 유지) ──
const entityListOpen = ref(false)
const entityMode = ref(localStorage.getItem('entityMode') === 'true')
const selectedEntityIds = ref<string[]>(JSON.parse(localStorage.getItem('selectedEntityIds') || '[]'))
const entityCandidates = ref<{ id: string; name: string; type: string; degree: number }[]>([])
const entityLoading = ref(false)

watch(entityMode, (v) => localStorage.setItem('entityMode', String(v)))
watch(selectedEntityIds, (v) => localStorage.setItem('selectedEntityIds', JSON.stringify(v)), { deep: true })

// 온톨로지 변경 시 엔티티 후보 로드
async function loadEntityCandidates(ontologyId: string) {
  if (!ontologyId) { entityCandidates.value = []; return }
  entityLoading.value = true
  try {
    const { getGraphData } = await import('../api/graph')
    const data = await getGraphData(ontologyId)
    const nodes = data.nodes || []
    const edges = data.edges || []
    // degree 계산
    const degreeMap: Record<string, number> = {}
    for (const e of edges) {
      degreeMap[e.source_id] = (degreeMap[e.source_id] || 0) + 1
      degreeMap[e.target_id] = (degreeMap[e.target_id] || 0) + 1
    }
    entityCandidates.value = nodes
      .map((n: any) => ({ id: n.id, name: n.name, type: n.type, degree: degreeMap[n.id] || 0 }))
      .filter((n: any) => n.degree >= 2)
      .sort((a: any, b: any) => b.degree - a.degree)
      .slice(0, 15)
    // localStorage에 저장된 선택이 없으면 상위 3개 자동 선택
    const saved = selectedEntityIds.value.filter(id => entityCandidates.value.some(e => e.id === id))
    selectedEntityIds.value = saved
  } catch {
    entityCandidates.value = []
  } finally {
    entityLoading.value = false
  }
}

watch(selectedOntologyId, (id, prevId) => {
  if (id && prevId && id !== prevId) {
    selectedEntityIds.value = []
    entityListOpen.value = false
  }
  if (id) loadEntityCandidates(id)
}, { immediate: true })

function toggleEntity(id: string) {
  const idx = selectedEntityIds.value.indexOf(id)
  if (idx >= 0) {
    selectedEntityIds.value = selectedEntityIds.value.filter(x => x !== id)
  } else {
    selectedEntityIds.value = [...selectedEntityIds.value, id]
  }
}

function clearLog() { simStore.clearLog(); simStore.clearQA() }

// ── Q&A ──
const qaMessages = computed(() => simStore.qaMessages)
const qaInput = ref('')
const qaInputEl = ref<HTMLTextAreaElement | null>(null)

function onQAKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendQA()
  }
}

async function sendQA() {
  const q = qaInput.value.trim()
  if (!q || simStore.isQALoading) return
  qaInput.value = ''
  // 입력창 높이 리셋
  if (qaInputEl.value) qaInputEl.value.style.height = 'auto'
  await simStore.askQuestion(q)
  // 답변 후 피드 맨 아래로 스크롤
  nextTick(() => {
    if (feedEl.value) feedEl.value.scrollTop = feedEl.value.scrollHeight
  })
}

function autoResizeQAInput() {
  const el = qaInputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 80) + 'px'
}

function formatQAAnswer(content: string): string {
  // 간단한 마크다운 변환: **bold**, 줄바꿈
  return content
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>')
}

// 시뮬 저장 시점에 현재 UI 입력값(rounds, maxPersonas, topic, entity 선택)을 스냅샷에 같이 실어보낸다.
// store가 UI state에 직접 의존하지 않도록 콜백 주입 방식을 사용.
onMounted(() => {
  simStore.setConfigSnapshotProvider(() => ({
    rounds: rounds.value,
    maxPersonas: maxPersonas.value,
    topic: topicText.value,
    selectedEntityIds: [...selectedEntityIds.value],
    entityMode: entityMode.value,
  }))
})
</script>

<style scoped>
.simulation-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* Config Bar */
.config-bar {
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid #EAEAEA;
  background: #FFF;
  flex-shrink: 0;
  gap: 24px;
}
.config-left, .config-center, .config-right { display: flex; align-items: center; gap: 10px; }
.config-label { font-size: 11px; color: #AAA; font-weight: 500; white-space: nowrap; }
.round-control { display: flex; align-items: center; gap: 6px; }
.round-btn {
  width: 24px; height: 24px; border: 1px solid #EAEAEA; border-radius: 4px;
  background: #FAFAFA; font-size: 14px; color: #555; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.15s;
}
.round-btn:hover { border-color: #FF5722; color: #FF5722; }
.round-num { font-size: 14px; font-weight: 700; color: #000; min-width: 20px; text-align: center; }
.agent-count, .current-round { font-size: 13px; font-weight: 600; color: #000; }
.agent-warn { font-size: 11px; color: #FF5722; font-weight: 600; }
.agent-breakdown {
  font-size: 11px;
  color: #555;
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  cursor: help;
}
.agent-breakdown-detail { color: #999; font-size: 10px; }
.mode-pill {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #EAEAEA;
  border-radius: 999px;
  background: #FAFAFA;
  color: #111;
  font-size: 12px;
  font-weight: 600;
}
.onto-picker { display: flex; align-items: center; gap: 6px; }
.onto-picker-label { font-size: 10px; color: #AAA; letter-spacing: 0.5px; }
.onto-picker-select { padding: 5px 8px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 11px; font-family: 'JetBrains Mono', monospace; background: #FFF; color: #333; outline: none; cursor: pointer; }
.onto-picker-select:focus { border-color: #FF5722; }
.sim-options-wrap { position: relative; }
.btn-sim-opts {
  width: 32px; height: 32px; border: 1px solid #EAEAEA; border-radius: 6px;
  background: #FAFAFA; font-size: 14px; cursor: pointer; transition: all 0.15s;
  display: flex; align-items: center; justify-content: center;
}
.btn-sim-opts:hover { border-color: #FF5722; color: #FF5722; }
.sim-opts-popup {
  position: absolute; top: 40px; right: 0; z-index: 100;
  width: 280px; background: #FFF; border: 1px solid #EAEAEA; border-radius: 12px;
  padding: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.12);
  display: flex; flex-direction: column; gap: 14px;
}
.sim-opts-title { font-size: 12px; font-weight: 700; color: #000; border-bottom: 1px solid #F0F0F0; padding-bottom: 8px; }
.sim-opts-row { display: flex; flex-direction: column; gap: 6px; }
.sim-opts-label { font-size: 11px; font-weight: 600; color: #666; }
.sim-opts-pills { display: flex; gap: 4px; }
.sim-opts-pill {
  flex: 1; padding: 6px 0; border: 1px solid #EAEAEA; border-radius: 6px;
  background: #FAFAFA; font-size: 12px; color: #888; cursor: pointer; transition: all 0.15s;
  font-family: 'Space Grotesk', sans-serif; text-align: center;
}
.sim-opts-pill.active { background: #000; color: #FFF; border-color: #000; }
.sim-opts-pill:hover:not(.active) { border-color: #FF5722; color: #FF5722; }
.sim-opts-input {
  width: 100%; padding: 6px 10px; border: 1px solid #EAEAEA; border-radius: 6px;
  font-size: 12px; color: #333; outline: none; background: #FAFAFA;
}
.sim-opts-input:focus { border-color: #FF5722; }
.sim-opts-hint { font-size: 9px; color: #BBB; line-height: 1.4; }

.btn-sim {
  padding: 8px 20px; background: #000; color: #FFF; border: none; border-radius: 6px;
  font-size: 13px; font-weight: 600; font-family: 'Space Grotesk', sans-serif; cursor: pointer; transition: all 0.15s;
}
.btn-sim:hover { background: #FF5722; transform: translateY(-1px); }
.btn-sim.running { background: #F44336; }

/* Topic Bar */
.topic-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 24px;
  position: relative;
  border-bottom: 1px solid #EAEAEA;
  background: #FAFAFA;
  flex-shrink: 0;
}
.topic-label {
  font-size: 12px;
  font-weight: 600;
  color: #555;
  white-space: nowrap;
  flex-shrink: 0;
}
.topic-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #E0E0E0;
  border-radius: 6px;
  font-size: 13px;
  font-family: 'Space Grotesk', sans-serif;
  color: #111;
  background: #FFF;
  outline: none;
  transition: border-color 0.15s;
}
.topic-input:focus { border-color: #FF5722; }
.topic-input:disabled { background: #F5F5F5; color: #999; cursor: not-allowed; }
.topic-input::placeholder { color: #BBB; }
.sim-history-wrap { flex-shrink: 0; }
.sim-history-select {
  padding: 6px 10px; border: 1px solid #EAEAEA; border-radius: 6px;
  font-size: 11px; background: #FAFAFA; color: #555; outline: none; cursor: pointer;
  font-family: 'Space Grotesk', sans-serif; max-width: 200px;
}
.sim-history-select:hover { border-color: #FF5722; }
.topic-display {
  position: absolute; left: 100px; right: 24px;
  font-size: 13px; color: #555; pointer-events: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* Layout */
.sim-layout { display: flex; flex: 1; overflow: hidden; }

/* Agent Panel */
.agent-panel {
  width: 260px;
  flex-shrink: 0;
  border-right: 1px solid #EAEAEA;
  display: flex;
  flex-direction: column;
  background: #FFF;
  overflow: hidden;
}
.panel-header {
  height: 40px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px; border-bottom: 1px solid #EAEAEA; flex-shrink: 0;
}
.panel-title { font-size: 12px; font-weight: 600; color: #333; }
.panel-count { font-size: 11px; color: #AAA; }
.agent-list { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 4px; }
.agent-card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 10px; border: 1px solid transparent; border-radius: 8px;
  cursor: pointer; transition: all 0.15s;
}
.agent-card:hover { background: #F7F7F7; }
.agent-card.active { background: #FFF3F0; border-color: rgba(255,87,34,0.2); }
.agent-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; color: #FFF; flex-shrink: 0; font-family: 'JetBrains Mono', monospace;
}
.agent-info { flex: 1; min-width: 0; }
.agent-name { font-size: 13px; font-weight: 600; color: #000; }
.agent-role { font-size: 10px; color: #999; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stance-badge {
  padding: 3px 8px; border-radius: 10px; font-size: 10px; font-weight: 600;
  font-family: 'Space Grotesk', sans-serif; flex-shrink: 0; white-space: nowrap;
}
.stance-badge.supportive { background: #E8F5E9; color: #1B5E20; }
.stance-badge.opposing   { background: #FFEBEE; color: #B71C1C; }
.stance-badge.neutral    { background: #F0F0F0; color: #424242; }

/* ═══════════════════════════════════════════════
   Event Panel (밝은 테마)
═══════════════════════════════════════════════ */
.event-panel {
  flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #F3F4F6;
}

.event-feed {
  flex: 1; overflow-y: auto;
  display: flex; flex-direction: column; gap: 8px; padding: 12px 16px;
}

.event-cursor { color: #FF5722; font-size: 14px; padding: 8px 16px; animation: blink 1s infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }

/* Round Separator */
.round-separator {
  display: flex; align-items: center; gap: 10px; margin: 4px 0;
}
.round-sep-line { flex: 1; height: 1px; background: #DDD; }
.round-sep-label { font-size: 10px; color: #999; white-space: nowrap; }

/* ═══════════════════════════════════════════════
   헤더 (밝은 테마)
═══════════════════════════════════════════════ */
.tw-header {
  height: 40px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px; border-bottom: 1px solid #E5E7EB; flex-shrink: 0;
  background: #FFF;
  position: sticky; top: 0; z-index: 10;
}
.tw-header-left { display: flex; align-items: center; gap: 12px; }
.tw-x-logo { width: 22px; height: 22px; color: #111; }
.tw-header-title { font-size: 15px; font-weight: 700; color: #111; }
.event-ctrl-btn.tw-clear {
  background: none; border: 1px solid #E5E7EB; border-radius: 20px;
  padding: 4px 14px; font-size: 12px; color: #999; cursor: pointer; transition: all 0.15s;
}
.event-ctrl-btn.tw-clear:hover { border-color: #FF5722; color: #FF5722; }

.tw-card {
  display: flex; gap: 12px; padding: 14px 16px;
  border-bottom: 1px solid #2F3336; cursor: pointer;
  transition: background 0.15s;
}
.tw-card:hover { background: rgba(255,255,255,0.03); }
.tw-card.highlighted { background: rgba(29,161,242,0.06); }
.tw-card.dimmed { opacity: 0.3; }

.tw-avatar {
  width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: #FFF; font-family: 'JetBrains Mono', monospace;
}
.tw-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.tw-meta { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.tw-name { font-weight: 700; font-size: 14px; color: #FFF; }
.tw-handle { font-size: 13px; color: #71767B; }
.tw-dot { color: #71767B; font-size: 13px; }
.tw-time { font-size: 13px; color: #71767B; }
.tw-action-pill {
  margin-left: auto; padding: 1px 7px; border-radius: 10px;
  font-size: 9px; font-weight: 700; font-family: 'JetBrains Mono', monospace;
}
.tw-action-pill.post   { background: rgba(29,161,242,0.15); color: #1DA1F2; }
.tw-action-pill.reply  { background: rgba(0,186,124,0.15);  color: #00BA7C; }
.tw-action-pill.repost { background: rgba(0,186,124,0.15);  color: #00BA7C; }
.tw-content { font-size: 14px; color: #FFFFFF; line-height: 1.6; word-break: break-word; }
.tw-actions {
  display: flex; gap: 20px; margin-top: 8px;
}
.tw-act-btn { font-size: 12px; color: #71767B; cursor: pointer; transition: color 0.15s; }
.tw-act-btn:hover { color: #1DA1F2; }

/* ═══════════════════════════════════════════════
   모더레이터 카드 (밝은 테마)
═══════════════════════════════════════════════ */
.moderator-card {
  display: flex; gap: 10px; padding: 14px 16px;
  background: #FFFBEB; border: 1px solid #FDE68A;
  border-radius: 10px;
}
.moderator-card.dimmed { opacity: 0.3; }
.mod-icon { font-size: 20px; flex-shrink: 0; }
.mod-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.mod-label { font-size: 9px; color: #B45309; letter-spacing: 1px; text-transform: uppercase; font-weight: 600; }
.mod-content { font-size: 13px; color: #92400E; line-height: 1.7; word-break: break-word; }

/* ═══════════════════════════════════════════════
   DB 에이전트 카드 (밝은 테마)
═══════════════════════════════════════════════ */
.db-agent-card {
  display: flex; gap: 10px; padding: 14px 16px;
  background: #EFF6FF; border: 1px solid #BFDBFE;
  border-radius: 10px;
}
.db-agent-card.dimmed { opacity: 0.3; }
.db-agent-icon { font-size: 20px; flex-shrink: 0; }
.db-agent-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.db-agent-label { font-size: 9px; color: #1D4ED8; letter-spacing: 1px; text-transform: uppercase; font-weight: 600; }
.db-agent-content { font-size: 13px; color: #1E40AF; line-height: 1.7; word-break: break-word; }

/* ═══════════════════════════════════════════════
   Entity Selector
═══════════════════════════════════════════════ */
.entity-selector {
  border-bottom: 1px solid #EAEAEA; flex-shrink: 0;
}
.entity-toggle {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; cursor: pointer; transition: background 0.15s;
}
.entity-toggle:hover { background: #F7F7F7; }
.entity-toggle-icon { font-size: 14px; }
.entity-toggle-label { font-size: 11px; font-weight: 600; color: #555; flex: 1; cursor: pointer; }
.entity-toggle-label:hover { color: #FF5722; }
.entity-toggle-switch {
  padding: 2px 8px; border-radius: 10px; font-size: 9px; font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  background: #F0F0F0; color: #999; transition: all 0.15s;
}
.entity-toggle-switch.on { background: #FF5722; color: #FFF; }
.entity-list {
  padding: 4px 8px 8px; display: flex; flex-direction: column; gap: 2px;
  max-height: 200px; overflow-y: auto;
}
.entity-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 6px; cursor: pointer; transition: background 0.1s;
}
.entity-item:hover { background: #F7F7F7; }
.entity-check { accent-color: #FF5722; width: 14px; height: 14px; cursor: pointer; flex-shrink: 0; }
.entity-item-info { flex: 1; min-width: 0; }
.entity-item-name { font-size: 12px; font-weight: 600; color: #222; }
.entity-item-type { font-size: 9px; color: #999; margin-left: 4px; }
.entity-degree { font-size: 9px; color: #BBB; flex-shrink: 0; }
.entity-sel-count { font-size: 9px; color: #FF5722; font-weight: 600; }
.entity-expand { border-top: 1px solid #F0F0F0; }
.entity-empty { font-size: 11px; color: #CCC; padding: 12px 16px; text-align: center; }

/* ═══════════════════════════════════════════════
   Progress Bar & 공통
═══════════════════════════════════════════════ */
.progress-bar-outer {
  padding: 8px 24px 10px;
  background: #FFF; border-top: 1px solid #EAEAEA; flex-shrink: 0;
}
.progress-info { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 10px; color: #AAA; }
.progress-track { height: 4px; background: #F0F0F0; border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; background: #FF5722; border-radius: 2px; transition: width 0.5s ease; }
.mono { font-family: 'JetBrains Mono', monospace; }

/* Agent Loading */
.agent-loading {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 40px 20px; gap: 12px; flex: 1;
}
.agent-loading-spinner {
  width: 32px; height: 32px; border: 3px solid #EAEAEA;
  border-top-color: #FF5722; border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg) } }
.agent-loading-text { font-size: 13px; font-weight: 600; color: #333; }
.agent-loading-desc { font-size: 11px; color: #AAA; }

/* Agent Empty */
.agent-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 40px 20px; gap: 8px; flex: 1;
}
.agent-empty-icon { font-size: 32px; opacity: 0.3; }
.agent-empty-text { font-size: 12px; color: #CCC; text-align: center; line-height: 1.6; }

/* Clear agent filter button */
.btn-clear-agent {
  font-size: 9px; padding: 1px 6px; border: 1px solid #EAEAEA;
  border-radius: 3px; background: none; color: #999; cursor: pointer; transition: all 0.15s;
}
.btn-clear-agent:hover { border-color: #FF5722; color: #FF5722; }

/* Discussion (회의실) 모드 카드 — 밝은 카드형 */
.disc-card {
  padding: 16px 20px;
  background: #FFF;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid #E5E7EB;
}
.disc-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-color: #D1D5DB; }
.disc-card.highlighted { background: #FFF7ED; border-color: #FF5722; border-left: 3px solid #FF5722; }
.disc-card.dimmed { opacity: 0.35; }
.disc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.disc-avatar {
  width: 34px; height: 34px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #FFF; flex-shrink: 0;
}
.disc-meta { flex: 1; }
.disc-name { font-weight: 700; font-size: 14px; color: #111; }
.disc-role { font-size: 11px; color: #888; margin-left: 6px; }
.disc-time { font-size: 11px; color: #BBB; font-family: 'JetBrains Mono', monospace; }
.disc-action-badge {
  padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 600;
  background: #F0F0F0; color: #666;
}
.disc-action-badge.post { background: #E3F2FD; color: #1565C0; }
.disc-action-badge.reply { background: #E8F5E9; color: #2E7D32; }
.disc-action-badge.question { background: #FFF3E0; color: #E65100; }
.disc-action-badge.concede { background: #F3E5F5; color: #7B1FA2; }
.disc-action-badge.propose { background: #E0F7FA; color: #00695C; }
.disc-action-badge.cite { background: #FBE9E7; color: #BF360C; }
.disc-action-badge.moderator { background: #FFF9C4; color: #F57F17; }
.disc-content {
  font-size: 14px; line-height: 1.8; color: #333;
  white-space: pre-wrap; word-break: break-word;
}

/* ═══════════════════════════════════════════════
   Q&A Section
═══════════════════════════════════════════════ */
.qa-separator {
  display: flex; align-items: center; gap: 10px; margin: 16px 0 8px;
}
.qa-sep-line { flex: 1; height: 1px; background: #FF5722; opacity: 0.3; }
.qa-sep-label { font-size: 11px; color: #FF5722; white-space: nowrap; font-weight: 600; }

.qa-card {
  padding: 14px 18px; border-radius: 10px; border: 1px solid #E5E7EB;
  transition: all 0.15s;
}
.qa-question {
  background: #F0F7FF; border-left: 3px solid #3498db;
}
.qa-answer {
  background: #FFF9F6; border-left: 3px solid #FF5722;
}
.qa-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap;
}
.qa-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; color: #FFF; flex-shrink: 0;
  font-family: 'JetBrains Mono', monospace;
}
.qa-user-avatar { background: #3498db; }
.qa-ai-avatar { background: #FF5722; }
.qa-meta { flex: 1; display: flex; align-items: center; gap: 6px; }
.qa-sender { font-size: 12px; font-weight: 700; color: #333; }
.qa-time { font-size: 10px; color: #AAA; }
.qa-refs { display: flex; gap: 4px; flex-wrap: wrap; }
.qa-ref-badge {
  padding: 1px 6px; border-radius: 8px; font-size: 9px; font-weight: 600;
  background: rgba(255,87,34,0.1); color: #FF5722;
}
.qa-content {
  font-size: 13px; line-height: 1.8; color: #333; word-break: break-word;
}
.qa-answer .qa-content :deep(strong) { color: #111; }

.qa-loading {
  display: flex; align-items: center; gap: 10px; padding: 12px 18px;
}
.qa-loading-spinner {
  width: 18px; height: 18px;
  border: 2px solid #FFE0CC; border-top-color: #FF5722;
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
.qa-loading-text { font-size: 12px; color: #E65100; font-weight: 500; }

/* Q&A Input Bar — AppSidebar의 .sidebar-bottom과 서브픽셀까지 정렬.
   sidebar-bottom은 natural content 높이 67.428px가 나오므로 같은 값으로 하드코딩. */
.qa-input-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 0 24px;
  height: 67.428571px; box-sizing: border-box;
  background: #FFF; border-top: 1px solid #EAEAEA; flex-shrink: 0;
}
.qa-input {
  flex: 1; padding: 10px 14px; border: 1px solid #E0E0E0; border-radius: 10px;
  font-size: 13px; font-family: 'Space Grotesk', sans-serif; color: #111;
  background: #FAFAFA; outline: none; resize: none;
  line-height: 1.5; min-height: 38px; max-height: 80px;
  transition: border-color 0.15s;
}
.qa-input:focus { border-color: #FF5722; background: #FFF; }
.qa-input:disabled { background: #F0F0F0; color: #999; cursor: not-allowed; }
.qa-input::placeholder { color: #BBB; }
.qa-send-btn {
  width: 38px; height: 38px; border: none; border-radius: 10px;
  background: #FF5722; color: #FFF; font-size: 18px; font-weight: 700;
  cursor: pointer; transition: all 0.15s;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.qa-send-btn:hover:not(:disabled) { background: #E64A19; transform: translateY(-1px); }
.qa-send-btn:disabled { background: #DDD; cursor: not-allowed; }
</style>

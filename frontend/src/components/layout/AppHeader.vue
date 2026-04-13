<template>
  <header class="app-header">

    <!-- Left: Brand -->
    <div class="header-left">
      <RouterLink to="/" class="brand">
        <span class="brand-name">Chiral Center</span>
        <span class="brand-tag">The center between real and simulated communities.</span>
      </RouterLink>
    </div>

    <!-- Center: View Switcher -->
    <nav class="view-switcher">
      <RouterLink to="/upload" class="switcher-tab">
        <span class="tab-icon">↑</span> {{ t('tab.upload') }}
      </RouterLink>
      <RouterLink to="/ontology" class="switcher-tab">
        <span class="tab-icon">⬡</span> {{ t('tab.graph') }}
      </RouterLink>
      <RouterLink to="/simulation" class="switcher-tab">
        <span class="tab-icon">◈</span> {{ t('tab.workbench') }}
      </RouterLink>
    </nav>

    <!-- Right: LLM Model 버튼 -->
    <div class="header-right">
      <button class="llm-btn" @click="toggleModal">
        <span class="llm-icon">⬡</span>
        <span class="llm-label">LLM Model</span>
        <span class="llm-summary">{{ llmStore.summary }}</span>
        <span class="llm-count" v-if="llmStore.multiAgentMode && llmStore.enabledAgents.length > 1">
          ×{{ llmStore.enabledAgents.length }}
        </span>
        <span class="status-dot" :class="llmStore.enabledAgents.length > 0 ? 'on' : 'off'"></span>
      </button>
    </div>

    <!-- Modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div class="modal-overlay" v-if="showModal" @click.self="closeModal">
          <div class="modal">

            <!-- Header -->
            <div class="modal-header">
              <div class="modal-title">
                <span class="modal-title-icon">⬡</span>
                {{ t('llm.title') }}
              </div>
              <button class="modal-close" @click="closeModal">✕</button>
            </div>

            <!-- 멀티 에이전트 토글 -->
            <div class="multi-toggle-row">
              <div class="multi-toggle-info">
                <span class="multi-toggle-label">{{ t('llm.multiAgent') }}</span>
                <span class="multi-toggle-desc">{{ t('llm.multiAgentDesc') }}</span>
              </div>
              <button class="toggle-btn" :class="{ active: llmStore.multiAgentMode }"
                @click="llmStore.multiAgentMode = !llmStore.multiAgentMode">
                <span class="toggle-knob"></span>
              </button>
            </div>

            <!-- Agent 목록 -->
            <div class="agent-list">
              <div v-for="(agent, idx) in llmStore.agents" :key="agent.id"
                class="agent-card" :class="{ disabled: !agent.enabled }">

                <!-- 카드 헤더 -->
                <div class="agent-card-header">
                  <span class="agent-index">Agent {{ idx + 1 }}</span>
                  <div class="agent-card-actions">
                    <button class="agent-toggle" :class="{ active: agent.enabled }"
                      @click="agent.enabled = !agent.enabled">
                      {{ agent.enabled ? 'ON' : 'OFF' }}
                    </button>
                    <button class="agent-remove" @click="llmStore.removeAgent(agent.id)"
                      :disabled="llmStore.agents.length <= 1">✕</button>
                  </div>
                </div>

                <!-- Provider 선택 -->
                <div class="field-row">
                  <label class="field-label">Provider</label>
                  <div class="provider-tabs">
                    <button v-for="p in providers" :key="p.value"
                      class="provider-tab"
                      :class="{ active: agent.provider === p.value }"
                      @click="onProviderChange(agent, p.value)">
                      <span class="provider-logo" v-html="p.logo"></span>
                      {{ p.label }}
                    </button>
                  </div>
                </div>

                <!-- Model 콤보박스 -->
                <div class="field-row">
                  <label class="field-label">Model</label>
                  <div class="combo-wrap" :class="{ open: openCombo === agent.id }">
                    <div class="combo-input-row">
                      <input
                        class="field-input combo-input"
                        v-model="agent.modelName"
                        :placeholder="modelPlaceholder(agent.provider)"
                        @click.stop="toggleCombo(agent.id)"
                        autocomplete="off"
                      />
                      <button
                        v-if="modelGroups(agent.provider).length > 0"
                        class="combo-arrow-btn"
                        @click.stop="toggleCombo(agent.id)"
                      >▾</button>
                    </div>
                    <!-- 제안 드롭다운 -->
                    <div class="combo-dropdown" v-if="openCombo === agent.id && modelGroups(agent.provider).length > 0">
                      <div v-for="group in modelGroups(agent.provider)" :key="group.label">
                        <div class="combo-group-label">{{ group.label }}</div>
                        <div
                          v-for="m in group.models" :key="m.id"
                          class="combo-option"
                          :class="{ selected: agent.modelName === m.id }"
                          @click.stop="selectModel(agent, m.id)"
                        >
                          <span class="combo-opt-name">{{ m.name }}</span>
                          <span class="combo-opt-ctx">{{ m.ctx }}</span>
                        </div>
                      </div>
                    </div>
                    <!-- 컨텍스트 힌트 -->
                    <div class="model-desc" v-if="selectedModelDesc(agent)">ctx {{ selectedModelDesc(agent) }}</div>
                  </div>
                </div>

                <!-- API Key -->
                <div class="field-row">
                  <label class="field-label">API Key</label>
                  <div class="key-input-wrap">
                    <template v-if="keyLocked[agent.id] && agent.apiKey">
                      <div class="key-masked">●●●●●●●● {{ t('llm.saved') }}</div>
                      <button class="key-reset-btn" @click="resetKey(agent)">{{ t('llm.reenter') }}</button>
                    </template>
                    <template v-else>
                      <input class="field-input" type="password" v-model="agent.apiKey"
                        :placeholder="keyPlaceholder(agent.provider)"
                        @blur="lockKey(agent)" />
                    </template>
                  </div>
                </div>


                <!-- 가중치 (멀티 에이전트 모드) -->
                <div class="field-row weight-row" v-if="llmStore.multiAgentMode">
                  <label class="field-label">{{ t('llm.weight') }}</label>
                  <div class="weight-control">
                    <input type="range" min="1" max="10" v-model.number="agent.weight" class="weight-slider" />
                    <span class="weight-value">{{ agent.weight }}</span>
                  </div>
                  <span class="weight-pct">{{ weightPct(agent) }}%</span>
                </div>

              </div>
            </div>

            <!-- 추가 버튼 -->
            <button class="add-agent-btn" @click="llmStore.addAgent()">{{ t('llm.addModel') }}</button>

            <!-- 비율 시각화 -->
            <div class="multi-viz" v-if="llmStore.multiAgentMode && llmStore.enabledAgents.length > 1">
              <div class="multi-viz-title">{{ t('llm.ratio') }}</div>
              <div class="multi-viz-bar">
                <div v-for="(a, i) in llmStore.enabledAgents" :key="a.id"
                  class="viz-segment"
                  :style="{ width: weightPct(a) + '%', background: segColors[i % segColors.length] }"
                  :title="`${a.modelName}: ${weightPct(a)}%`"></div>
              </div>
              <div class="multi-viz-legend">
                <span v-for="(a, i) in llmStore.enabledAgents" :key="a.id" class="legend-item">
                  <span class="legend-dot" :style="{ background: segColors[i % segColors.length] }"></span>
                  {{ a.modelName || a.provider }}
                </span>
              </div>
            </div>

            <!-- 토큰 사용량 -->
            <div class="usage-section">
              <div class="usage-header" @click="toggleUsage">
                <span class="usage-title">Token Usage</span>
                <span class="usage-arrow">{{ showUsage ? '▾' : '▸' }}</span>
              </div>

              <div class="usage-body" v-if="showUsage">
                <!-- 기간 선택 -->
                <div class="usage-period-row">
                  <button v-for="p in usagePeriods" :key="p.days"
                    class="period-btn" :class="{ active: usagePeriod === p.days }"
                    @click="loadUsage(p.days)">
                    {{ p.label }}
                  </button>
                </div>

                <!-- 로딩 -->
                <div class="usage-loading" v-if="usageLoading">loading...</div>

                <!-- 요약 -->
                <div class="usage-summary" v-else-if="usageData">
                  <div class="usage-stat-grid">
                    <div class="usage-stat">
                      <span class="stat-value">{{ formatNum(usageData.total_tokens) }}</span>
                      <span class="stat-label">Total Tokens</span>
                    </div>
                    <div class="usage-stat">
                      <span class="stat-value">{{ formatNum(usageData.total_input) }}</span>
                      <span class="stat-label">Input</span>
                    </div>
                    <div class="usage-stat">
                      <span class="stat-value">{{ formatNum(usageData.total_output) }}</span>
                      <span class="stat-label">Output</span>
                    </div>
                    <div class="usage-stat">
                      <span class="stat-value">{{ usageData.call_count }}</span>
                      <span class="stat-label">API Calls</span>
                    </div>
                  </div>

                  <!-- 모델별 -->
                  <div class="usage-breakdown" v-if="Object.keys(usageData.by_model || {}).length">
                    <div class="breakdown-title">Model</div>
                    <div class="breakdown-table">
                      <div class="bt-row bt-header">
                        <span class="bt-cell bt-name">Model</span>
                        <span class="bt-cell">Calls</span>
                        <span class="bt-cell">Input</span>
                        <span class="bt-cell">Output</span>
                        <span class="bt-cell">Total</span>
                      </div>
                      <div class="bt-row" v-for="(v, k) in usageData.by_model" :key="k">
                        <span class="bt-cell bt-name">{{ k }}</span>
                        <span class="bt-cell">{{ v.calls }}</span>
                        <span class="bt-cell">{{ formatNum(v.input) }}</span>
                        <span class="bt-cell">{{ formatNum(v.output) }}</span>
                        <span class="bt-cell">{{ formatNum(v.total) }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 기능별 -->
                  <div class="usage-breakdown" v-if="Object.keys(usageData.by_feature || {}).length">
                    <div class="breakdown-title">Feature</div>
                    <div class="breakdown-table">
                      <div class="bt-row bt-header">
                        <span class="bt-cell bt-name">Feature</span>
                        <span class="bt-cell">Calls</span>
                        <span class="bt-cell">Total Tokens</span>
                      </div>
                      <div class="bt-row" v-for="(v, k) in usageData.by_feature" :key="k">
                        <span class="bt-cell bt-name">{{ featureLabel(String(k)) }}</span>
                        <span class="bt-cell">{{ v.calls }}</span>
                        <span class="bt-cell">{{ formatNum(v.total) }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 일별 -->
                  <div class="usage-breakdown" v-if="Object.keys(usageData.by_date || {}).length">
                    <div class="breakdown-title">Daily</div>
                    <div class="breakdown-table daily-table">
                      <div class="bt-row bt-header">
                        <span class="bt-cell bt-name">Date</span>
                        <span class="bt-cell">Calls</span>
                        <span class="bt-cell">Total Tokens</span>
                      </div>
                      <div class="bt-row" v-for="(v, k) in usageData.by_date" :key="k">
                        <span class="bt-cell bt-name">{{ k }}</span>
                        <span class="bt-cell">{{ v.calls }}</span>
                        <span class="bt-cell">{{ formatNum(v.total) }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="usage-empty" v-else>No usage data</div>
              </div>
            </div>

            <!-- 저장 -->
            <div class="modal-footer">
              <button class="save-btn" @click="closeModal">{{ t('llm.save') }}</button>
            </div>

          </div>
        </div>
      </Transition>
    </Teleport>

  </header>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useLLMStore } from '../../stores/llm'
import { PROVIDERS, MODEL_CATALOG, getModelGroups, getDefaultModel, getModelPlaceholder, getModelCtx } from '../../composables/useModelCatalog'
import { useI18n } from '../../composables/useI18n'

const route = useRoute()
const { t } = useI18n()
const llmStore = useLLMStore()
const showModal = ref(false)
const showKey = reactive<Record<string, boolean>>({})
// 키 잠금 상태: true면 masked+재입력, false면 input
// 모달이 열릴 때마다 저장된 키가 있으면 잠금, 없으면 input
const keyLocked = reactive<Record<string, boolean>>({})

watch(showModal, (isOpen) => {
  if (!isOpen) return
  for (const agent of llmStore.agents) {
    keyLocked[agent.id] = !!agent.apiKey
  }
})

// 새로 추가된 에이전트는 초기 unlocked
watch(
  () => llmStore.agents.map(a => a.id).join(','),
  () => {
    for (const agent of llmStore.agents) {
      if (keyLocked[agent.id] === undefined) {
        keyLocked[agent.id] = !!agent.apiKey
      }
    }
  }
)

function resetKey(agent: any) {
  agent.apiKey = ''
  keyLocked[agent.id] = false
}

function lockKey(agent: any) {
  if (agent.apiKey) keyLocked[agent.id] = true
}
const openCombo = ref<string | null>(null)

// ── Token Usage ──
const showUsage = ref(false)
const usageLoading = ref(false)
const usagePeriod = ref(7)
const usageData = ref<any>(null)

const usagePeriods = [
  { label: 'Today', days: 1 },
  { label: '7D', days: 7 },
  { label: '30D', days: 30 },
  { label: 'All', days: 0 },
]

const featureLabels: Record<string, string> = {
  simulation: 'Simulation',
  db_chat: 'DB Chat',
  persona_chat: 'Persona Chat',
  persona_profile: 'Persona Profile',
  persona_search: 'Persona Search',
  ontology: 'Ontology',
  report: 'Report',
  graph_extract: 'Graph Extract',
  unknown: 'Other',
}
function featureLabel(key: string) { return featureLabels[key] || key }

function formatNum(n: number): string {
  if (!n) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString()
}

async function toggleUsage() {
  showUsage.value = !showUsage.value
  if (showUsage.value && !usageData.value) {
    await loadUsage(usagePeriod.value)
  }
}

async function loadUsage(days: number) {
  usagePeriod.value = days
  usageLoading.value = true
  try {
    const params = days > 0 ? `?days=${days}` : ''
    const res = await fetch(`/api/tokens/summary${params}`, { credentials: 'include' })
    usageData.value = await res.json()
  } catch (e) {
    console.error('Failed to load usage', e)
    usageData.value = null
  } finally {
    usageLoading.value = false
  }
}

function toggleCombo(id: string) {
  openCombo.value = openCombo.value === id ? null : id
}
function selectModel(agent: any, modelId: string) {
  agent.modelName = modelId
  openCombo.value = null
}

function onDocClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.combo-wrap')) openCombo.value = null
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

function toggleModal() { showModal.value = !showModal.value }
function closeModal() { showModal.value = false }

// ── Provider / 모델 카탈로그 (공유 composable) ──
const providers = PROVIDERS

function modelGroups(provider: string) { return getModelGroups(provider) }
function modelPlaceholder(provider: string) { return getModelPlaceholder(provider) }
function selectedModelDesc(agent: any): string {
  const ctx = getModelCtx(agent.provider, agent.modelName)
  return ctx ? `ctx ${ctx}` : ''
}

function onProviderChange(agent: any, provider: string) {
  agent.provider = provider
  // 첫 번째 모델로 자동 선택
  const groups = MODEL_CATALOG[provider] ?? []
  if (groups.length > 0 && groups[0].models.length > 0) {
    agent.modelName = groups[0].models[0].id
  } else {
    agent.modelName = ''
  }
}

function keyPlaceholder(provider: string) {
  const map: Record<string, string> = {
    openai: 'sk-...',
    anthropic: 'sk-ant-...',
  }
  return map[provider] ?? 'api-key'
}

function weightPct(agent: any) {
  const total = llmStore.enabledAgents.reduce((s, a) => s + a.weight, 0)
  if (total === 0) return 0
  return Math.round((agent.weight / total) * 100)
}

const segColors = ['#FF5722', '#3498db', '#2ecc71', '#9b59b6', '#f39c12', '#1abc9c']
</script>

<style scoped>
/* ── Header ─────────────────────────────── */
.app-header {
  height: 60px; background: #FFF;
  border-bottom: 1px solid #EAEAEA;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 24px;
  position: sticky; top: 0; z-index: 100;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  flex-shrink: 0;
}
.brand { display: flex; align-items: baseline; gap: 8px; text-decoration: none; }
.brand-name { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 16px; letter-spacing: 1px; color: #000; }
.brand-tag { font-family: 'JetBrains Mono', monospace; font-size: 9px; color: #999; white-space: nowrap; }

.view-switcher { display: flex; gap: 2px; background: #F7F7F7; padding: 4px; border-radius: 8px; border: 1px solid #EAEAEA; }
.switcher-tab { display: flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 5px; font-size: 13px; font-weight: 500; color: #666; text-decoration: none; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.switcher-tab:hover, .switcher-tab.router-link-active { background: #FFF; color: #FF5722; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.tab-icon { font-size: 11px; opacity: 0.7; }

/* LLM 버튼 */
.header-right { display: flex; align-items: center; }
.llm-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 14px; background: #FAFAFA;
  border: 1px solid #EAEAEA; border-radius: 20px;
  cursor: pointer; transition: all 0.15s;
  font-family: 'JetBrains Mono', monospace;
}
.llm-btn:hover { background: #FFF; border-color: #FF5722; box-shadow: 0 2px 8px rgba(255,87,34,0.12); }
.llm-icon { font-size: 12px; color: #FF5722; }
.llm-label { font-size: 10px; color: #999; font-weight: 500; letter-spacing: 0.5px; }
.llm-summary { font-size: 11px; color: #333; font-weight: 600; }
.llm-count { font-size: 10px; background: #FF5722; color: #FFF; padding: 1px 5px; border-radius: 10px; font-weight: 700; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; }
.status-dot.on { background: #4CAF50; box-shadow: 0 0 4px rgba(76,175,80,0.5); }
.status-dot.off { background: #CCC; }

/* ── Modal ─────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.35);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex; align-items: center; justify-content: center;
}
.modal {
  width: 780px; max-width: calc(100vw - 48px);
  height: calc(100vh - 80px); max-height: 820px;
  background: #FFF; border: 1px solid #EAEAEA;
  border-radius: 16px; box-shadow: 0 16px 60px rgba(0,0,0,0.18);
  display: flex; flex-direction: column; overflow: hidden;
}
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px 14px; border-bottom: 1px solid #EAEAEA; flex-shrink: 0; }
.modal-title { display: flex; align-items: center; gap: 8px; font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: #000; }
.modal-title-icon { color: #FF5722; }
.modal-close { background: none; border: none; cursor: pointer; color: #999; font-size: 14px; padding: 4px 8px; border-radius: 4px; transition: all 0.15s; }
.modal-close:hover { background: #F5F5F5; color: #000; }

/* 멀티 토글 */
.multi-toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 12px 20px; background: #FAFAFA; border-bottom: 1px solid #EAEAEA; flex-shrink: 0; }
.multi-toggle-info { display: flex; flex-direction: column; gap: 2px; }
.multi-toggle-label { font-family: 'Space Grotesk', sans-serif; font-size: 13px; font-weight: 600; color: #000; }
.multi-toggle-desc { font-size: 11px; color: #999; }
.toggle-btn { width: 44px; height: 24px; background: #E0E0E0; border: none; border-radius: 12px; cursor: pointer; position: relative; transition: background 0.2s; flex-shrink: 0; }
.toggle-btn.active { background: #FF5722; }
.toggle-knob { position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; background: #FFF; border-radius: 50%; transition: left 0.2s; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
.toggle-btn.active .toggle-knob { left: 23px; }

/* Agent 목록 */
.agent-list { flex: 1; overflow-y: auto; padding: 16px 20px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; align-content: start; }
.agent-card { border: 1px solid #EAEAEA; border-radius: 8px; padding: 14px; background: #FAFAFA; transition: all 0.15s; }
.agent-card:hover { border-color: #DDD; background: #FFF; }
.agent-card.disabled { opacity: 0.45; }

.agent-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.agent-index { font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700; color: #FF5722; letter-spacing: 0.5px; }
.agent-card-actions { display: flex; align-items: center; gap: 6px; }
.agent-toggle { padding: 2px 8px; border-radius: 10px; border: 1px solid #DDD; background: #EEE; font-size: 10px; font-weight: 700; cursor: pointer; color: #999; transition: all 0.15s; font-family: 'JetBrains Mono', monospace; }
.agent-toggle.active { background: #E8F5E9; border-color: #4CAF50; color: #2E7D32; }
.agent-remove { background: none; border: none; cursor: pointer; color: #CCC; font-size: 12px; padding: 2px 6px; border-radius: 4px; transition: all 0.15s; }
.agent-remove:hover:not(:disabled) { background: #FEE; color: #F44336; }
.agent-remove:disabled { cursor: not-allowed; opacity: 0.3; }

/* 필드 */
.field-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.field-row:last-child { margin-bottom: 0; }
.field-label { font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600; color: #999; letter-spacing: 0.5px; width: 52px; flex-shrink: 0; }
.field-input { flex: 1; padding: 6px 10px; border: 1px solid #E0E0E0; border-radius: 6px; font-family: 'JetBrains Mono', monospace; font-size: 12px; background: #FFF; color: #333; outline: none; transition: border-color 0.15s; }
.field-input:focus { border-color: #FF5722; }

/* Provider 탭 */
.provider-tabs { display: flex; gap: 3px; flex: 1; flex-wrap: wrap; }
.provider-tab { flex: 1; min-width: 60px; padding: 5px 4px; border: 1px solid #E0E0E0; border-radius: 5px; background: #FFF; font-size: 11px; font-weight: 500; color: #666; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; display: flex; align-items: center; justify-content: center; gap: 3px; }
.provider-tab.active { background: #000; color: #FFF; border-color: #000; }
.provider-tab:hover:not(.active) { border-color: #FF5722; color: #FF5722; }
.provider-logo { font-size: 10px; }

/* 콤보박스 */
.combo-wrap { flex: 1; position: relative; display: flex; flex-direction: column; gap: 4px; }
.combo-input-row { display: flex; gap: 0; }
.combo-input { flex: 1; border-radius: 6px 0 0 6px !important; border-right: none !important; }
.combo-wrap:not(:has(.combo-arrow-btn)) .combo-input { border-radius: 6px !important; border-right: 1px solid #E0E0E0 !important; }
.combo-arrow-btn {
  padding: 0 10px; border: 1px solid #E0E0E0; border-left: none;
  border-radius: 0 6px 6px 0; background: #F7F7F7;
  cursor: pointer; font-size: 10px; color: #999;
  transition: all 0.15s;
}
.combo-arrow-btn:hover { background: #EAEAEA; color: #333; }
.combo-wrap.open .combo-arrow-btn { border-color: #FF5722; color: #FF5722; }
.combo-wrap.open .combo-input { border-color: #FF5722; }

.combo-dropdown {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0;
  background: #FFF; border: 1px solid #EAEAEA;
  border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.1);
  z-index: 200; max-height: 220px; overflow-y: auto;
  padding: 4px 0;
}
.combo-group-label {
  padding: 6px 12px 3px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px; font-weight: 700;
  color: #BBB; letter-spacing: 0.8px; text-transform: uppercase;
}
.combo-option {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 12px; cursor: pointer;
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  color: #333; transition: background 0.1s;
}
.combo-option:hover { background: #FFF9F8; }
.combo-option.selected { background: #FFF3F0; color: #FF5722; }
.combo-opt-name { font-weight: 500; }
.combo-opt-ctx { font-size: 9px; color: #BBB; margin-left: 8px; }
.model-desc { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #FF5722; letter-spacing: 0.3px; }

/* API Key */
.key-input-wrap { flex: 1; display: flex; gap: 6px; }
.key-input-wrap .field-input { flex: 1; }
.key-toggle { padding: 4px 8px; border: 1px solid #E0E0E0; border-radius: 6px; background: #FFF; cursor: pointer; font-size: 12px; transition: all 0.15s; }
.key-toggle:hover { border-color: #FF5722; }
.key-masked {
  flex: 1; padding: 8px 12px; border: 1px solid #E0E0E0; border-radius: 6px;
  background: #F5F5F5; font-size: 12px; color: #888;
  font-family: 'JetBrains Mono', monospace;
}
.key-reset-btn {
  padding: 6px 12px; border: 1px solid #EAEAEA; border-radius: 6px;
  background: #FFF; font-size: 11px; font-weight: 600; color: #555; cursor: pointer;
  transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; flex-shrink: 0;
}
.key-reset-btn:hover { border-color: #FF5722; color: #FF5722; }

/* 가중치 */
.weight-row { align-items: center; }
.weight-control { display: flex; align-items: center; gap: 8px; flex: 1; }
.weight-slider { flex: 1; accent-color: #FF5722; }
.weight-value { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; color: #333; width: 16px; text-align: center; }
.weight-pct { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #FF5722; width: 36px; text-align: right; flex-shrink: 0; }

/* 추가 버튼 */
.add-agent-btn { margin: 0 20px 12px; padding: 10px; border: 1px dashed #DDD; border-radius: 8px; background: none; cursor: pointer; font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #999; width: calc(100% - 40px); transition: all 0.15s; flex-shrink: 0; }
.add-agent-btn:hover { border-color: #FF5722; color: #FF5722; background: #FFF9F8; }

/* 비율 시각화 */
.multi-viz { margin: 0 20px 12px; padding: 12px; border: 1px solid #EAEAEA; border-radius: 8px; background: #FAFAFA; flex-shrink: 0; }
.multi-viz-title { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #999; margin-bottom: 8px; letter-spacing: 0.5px; }
.multi-viz-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; gap: 1px; margin-bottom: 8px; }
.viz-segment { height: 100%; transition: width 0.3s ease; border-radius: 2px; }
.multi-viz-legend { display: flex; flex-wrap: wrap; gap: 8px; }
.legend-item { display: flex; align-items: center; gap: 4px; font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #666; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

/* ── Token Usage ─────────────────────── */
.usage-section { margin: 0 20px 12px; border: 1px solid #EAEAEA; border-radius: 8px; background: #FAFAFA; flex-shrink: 0; overflow: hidden; }
.usage-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; cursor: pointer; user-select: none; transition: background 0.15s; }
.usage-header:hover { background: #F0F0F0; }
.usage-title { font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700; color: #666; letter-spacing: 0.5px; }
.usage-arrow { font-size: 10px; color: #999; }

.usage-body { padding: 0 14px 14px; }
.usage-period-row { display: flex; gap: 4px; margin-bottom: 12px; }
.period-btn { padding: 4px 12px; border: 1px solid #E0E0E0; border-radius: 12px; background: #FFF; font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600; color: #666; cursor: pointer; transition: all 0.15s; }
.period-btn.active { background: #000; color: #FFF; border-color: #000; }
.period-btn:hover:not(.active) { border-color: #FF5722; color: #FF5722; }

.usage-loading { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #999; padding: 8px 0; }
.usage-empty { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #BBB; padding: 8px 0; }

.usage-stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
.usage-stat { display: flex; flex-direction: column; align-items: center; padding: 8px 4px; background: #FFF; border: 1px solid #EAEAEA; border-radius: 6px; }
.stat-value { font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: #FF5722; }
.stat-label { font-family: 'JetBrains Mono', monospace; font-size: 9px; color: #999; margin-top: 2px; letter-spacing: 0.3px; }

.usage-breakdown { margin-bottom: 10px; }
.breakdown-title { font-family: 'JetBrains Mono', monospace; font-size: 9px; font-weight: 700; color: #BBB; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 4px; }
.breakdown-table { background: #FFF; border: 1px solid #EAEAEA; border-radius: 6px; overflow: hidden; }
.daily-table { max-height: 120px; overflow-y: auto; }
.bt-row { display: flex; padding: 5px 10px; border-bottom: 1px solid #F5F5F5; font-family: 'JetBrains Mono', monospace; font-size: 10px; }
.bt-row:last-child { border-bottom: none; }
.bt-row.bt-header { background: #F9F9F9; font-weight: 700; color: #999; }
.bt-cell { flex: 1; text-align: right; color: #333; }
.bt-cell.bt-name { flex: 2; text-align: left; font-weight: 500; color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 푸터 */
.modal-footer { padding: 14px 20px; border-top: 1px solid #EAEAEA; flex-shrink: 0; }
.save-btn { width: 100%; padding: 10px; background: #000; color: #FFF; border: none; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700; cursor: pointer; transition: all 0.15s; }
.save-btn:hover { background: #FF5722; transform: translateY(-1px); }

/* Transition */
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>

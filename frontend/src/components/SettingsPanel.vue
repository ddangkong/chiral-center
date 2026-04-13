<template>
  <Teleport to="body">
    <div v-if="settings.isOpen" class="settings-overlay" @click.self="settings.close()">
      <div class="settings-panel">
        <div class="sp-header">
          <div class="sp-title">{{ t('settings.title') }}</div>
          <button class="sp-close" @click="settings.close()">×</button>
        </div>

        <div class="sp-body">
          <div class="sp-section">
            <div class="sp-section-label mono">{{ t('settings.language') }}</div>
            <div class="sp-section-desc">{{ t('settings.langDesc') }}</div>
            <div class="lang-pills">
              <button
                v-for="lang in languageOptions"
                :key="lang.value"
                class="lang-pill"
                :class="{ active: settings.outputLanguage === lang.value }"
                @click="settings.outputLanguage = lang.value"
              >{{ lang.label }}</button>
            </div>
          </div>

          <div class="sp-section">
            <div class="sp-section-label mono">{{ t('settings.directive') }}</div>
            <div class="sp-section-desc">{{ t('settings.directiveDesc') }}</div>
            <textarea
              v-model="settings.globalDirective"
              class="sp-textarea"
              rows="3"
              :placeholder="t('settings.directivePlaceholder')"
            />
          </div>

          <div class="sp-section">
            <div class="sp-section-label mono">{{ t('settings.roles') }}</div>
            <div class="sp-section-desc">{{ t('settings.rolesDesc') }}</div>
          </div>

          <template v-for="agent in coreAgents" :key="agent.role">
            <div class="agent-card" :class="{ disabled: !agent.enabled }">
              <div class="agent-card-header">
                <div class="agent-role-row">
                  <span class="agent-dot" :style="{ background: roleColor(agent.role) }" />
                  <span class="agent-role-name">{{ labelFor(agent) }}</span>
                </div>
                <label class="agent-toggle">
                  <input type="checkbox" v-model="agent.enabled" />
                  <span class="toggle-label mono">{{ agent.enabled ? t('settings.join') : t('settings.exclude') }}</span>
                </label>
              </div>
              <textarea
                v-if="agent.enabled"
                v-model="agent.systemPrompt"
                class="sp-textarea agent-textarea"
                rows="2"
                :placeholder="placeholders[agent.role] || '추가 시스템 프롬프트'"
              />
            </div>
          </template>

          <div class="sp-section" style="margin-top: 12px;">
            <div class="sp-section-label mono">지원 에이전트</div>
            <div class="sp-section-desc">전용 역할 — 필요 시에만 발언. 꺼두면 해당 기능이 동작하지 않습니다.</div>
          </div>

          <template v-for="agent in supportAgents" :key="agent.role">
            <div class="agent-card" :class="{ disabled: !agent.enabled }">
              <div class="agent-card-header">
                <div class="agent-role-row">
                  <span class="agent-dot" :style="{ background: roleColor(agent.role) }" />
                  <span class="agent-role-name">{{ labelFor(agent) }}</span>
                  <span class="agent-role-hint mono">{{ supportHints[agent.role] || '' }}</span>
                </div>
                <label class="agent-toggle">
                  <input type="checkbox" v-model="agent.enabled" />
                  <span class="toggle-label mono">{{ agent.enabled ? t('settings.join') : t('settings.exclude') }}</span>
                </label>
              </div>
              <textarea
                v-if="agent.enabled && !nonCustomizable.has(agent.role)"
                v-model="agent.systemPrompt"
                class="sp-textarea agent-textarea"
                rows="2"
                :placeholder="placeholders[agent.role] || '추가 시스템 프롬프트'"
              />
            </div>
          </template>

          <div class="sp-section" style="margin-top: 8px;">
            <div class="sp-section-label mono">{{ t('settings.customPersonas') }}</div>
            <div class="sp-section-desc">
              {{ settings.customAgents.length > 0 ? settings.customAgents.length + t('settings.personasRegistered') : t('settings.noPersonas') }}
              · {{ t('settings.manageSidebar') }}
            </div>
          </div>
        </div>

        <div class="sp-footer">
          <button class="sp-btn-reset" @click="settings.resetAll()">{{ t('settings.reset') }}</button>
          <button class="sp-btn-done" @click="settings.close()">{{ t('settings.done') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useSettingsStore, LANGUAGE_OPTIONS, type AgentPromptOverride } from '../stores/settings'
import { useI18n } from '../composables/useI18n'

const settings = useSettingsStore()
const { t } = useI18n()
const languageOptions = LANGUAGE_OPTIONS

const CORE_ROLES = new Set([
  'market_analyst',
  'financial_analyst',
  'tech_reviewer',
  'risk_analyst',
  'strategy_lead',
])

const coreAgents = computed(() =>
  settings.agentPrompts.filter(a => CORE_ROLES.has(a.role))
)
const supportAgents = computed(() =>
  settings.agentPrompts.filter(a => !CORE_ROLES.has(a.role))
)

// 커스텀 프롬프트 입력을 지원하지 않는 에이전트 (내부에서 동적 프롬프트 생성)
const nonCustomizable = new Set(['db_agent', 'price_research', 'moderator'])

const ROLE_COLORS: Record<string, string> = {
  market_analyst: '#5C6BC0',
  financial_analyst: '#42A5F5',
  tech_reviewer: '#AB47BC',
  risk_analyst: '#EF5350',
  strategy_lead: '#26A69A',
  devils_advocate: '#FF7043',
  moderator: '#78909C',
  db_agent: '#66BB6A',
  price_research: '#FFA726',
}

const I18N_KEY: Record<string, string> = {
  market_analyst: 'market',
  financial_analyst: 'finance',
  tech_reviewer: 'tech',
  risk_analyst: 'risk',
  strategy_lead: 'strategy',
}

const placeholders: Record<string, string> = {
  market_analyst: '예: 시장 규모와 경쟁사 수치를 먼저 제시하고, 고객 세그먼트별 차이를 분리해서 말할 것',
  financial_analyst: '예: ROI, 회수기간, 민감도 분석 없이 결론 내리지 말 것',
  tech_reviewer: '예: 구현 난이도, 선행 의존성, 개발 일정 리스크를 항상 분리해서 설명할 것',
  risk_analyst: '예: 실패 시나리오와 완화책을 반드시 한 쌍으로 제시할 것',
  strategy_lead: '예: 각 역할의 주장을 인용한 뒤 go/no-go 판단과 실행 순서를 명확히 정리할 것',
  devils_advocate: '예: 합의가 형성될 때마다 숨겨진 가정을 하나 이상 드러낼 것',
}

const supportHints: Record<string, string> = {
  devils_advocate: '매 라운드 말미에 반론 제기',
  moderator: '라운드 요약 및 다음 방향 제시',
  db_agent: '데이터 요청 시 내부 DB 검색',
  price_research: '가격/시장 조사 요청 응답',
}

function roleColor(role: string) {
  return ROLE_COLORS[role] || '#999'
}

function labelFor(agent: AgentPromptOverride) {
  const key = I18N_KEY[agent.role]
  if (key) return t('settings.role.' + key, agent.label || agent.role)
  return agent.label || agent.role
}
</script>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}

.settings-panel {
  width: 480px;
  max-width: 90vw;
  height: 100vh;
  background: #fff;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.1);
  animation: slideIn 0.2s ease;
}

@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.sp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid #eaeaea;
  flex-shrink: 0;
}

.sp-title {
  font-size: 16px;
  font-weight: 700;
  color: #000;
}

.sp-close {
  width: 32px;
  height: 32px;
  border: 1px solid #eaeaea;
  border-radius: 8px;
  background: #fff;
  font-size: 14px;
  color: #888;
  cursor: pointer;
  display: grid;
  place-items: center;
}

.sp-close:hover {
  background: #f5f5f5;
  color: #000;
}

.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sp-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sp-section-label {
  font-size: 11px;
  font-weight: 700;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sp-section-desc {
  font-size: 11px;
  color: #aaa;
}

.lang-pills { display: flex; gap: 6px; margin-top: 8px; }
.lang-pill {
  padding: 6px 16px; border: 1px solid #EAEAEA; border-radius: 8px;
  background: #FAFAFA; font-size: 13px; font-weight: 600; color: #888;
  cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif;
}
.lang-pill.active { background: #000; color: #FFF; border-color: #000; }
.lang-pill:hover:not(.active) { border-color: #FF5722; color: #FF5722; }

.sp-textarea {
  border: 1px solid #eaeaea;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  color: #333;
  font-family: 'Space Grotesk', sans-serif;
  outline: none;
  resize: vertical;
  transition: border-color 0.15s;
}

.sp-textarea:focus {
  border-color: #ff5722;
}

.sp-textarea::placeholder {
  color: #ccc;
  font-size: 11px;
}

.agent-card {
  border: 1px solid #eaeaea;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.15s;
}

.agent-card:hover {
  border-color: #ddd;
}

.agent-card.disabled {
  opacity: 0.5;
  background: #fafafa;
}

.agent-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.agent-role-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.agent-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.agent-role-name {
  font-size: 14px;
  font-weight: 600;
  color: #222;
}

.agent-role-hint {
  font-size: 10px;
  color: #9a9a9a;
  margin-left: 4px;
}

.agent-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.agent-toggle input[type="checkbox"] {
  accent-color: #ff5722;
  width: 14px;
  height: 14px;
}

.toggle-label {
  font-size: 10px;
  color: #888;
}

.agent-textarea {
  font-size: 11px;
}

.sp-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  border-top: 1px solid #eaeaea;
  flex-shrink: 0;
}

.sp-btn-reset {
  padding: 8px 16px;
  border: 1px solid #eaeaea;
  border-radius: 8px;
  font-size: 12px;
  background: #fff;
  color: #888;
  cursor: pointer;
}

.sp-btn-reset:hover {
  color: #e53935;
  border-color: #ffcdd2;
}

.sp-btn-done {
  padding: 8px 24px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  background: #ff5722;
  color: #fff;
  cursor: pointer;
}

.sp-btn-done:hover {
  background: #f4511e;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}
</style>

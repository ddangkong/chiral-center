import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface AgentPromptOverride {
  role: string
  label?: string
  enabled: boolean
  systemPrompt: string
}

export interface CustomAgent {
  id: string
  name: string
  role: string
  persona: string
  enabled: boolean
  profile?: Record<string, any>
  _collecting?: boolean
  _collectLog?: { type: string; text: string }[]
  _searchResults?: any[]
  _crawlChunks?: number
  _crawlError?: string
  _chatMessages?: { role: string; content: string }[]
  _chatDbId?: string
}

const DEFAULT_AGENT_PROMPTS: AgentPromptOverride[] = [
  // Core agents (매 라운드 전원 발언)
  { role: 'market_analyst', label: '시장분석관', enabled: true, systemPrompt: '' },
  { role: 'financial_analyst', label: '재무분석관', enabled: true, systemPrompt: '' },
  { role: 'tech_reviewer', label: '기술검토관', enabled: true, systemPrompt: '' },
  { role: 'risk_analyst', label: '리스크분석관', enabled: true, systemPrompt: '' },
  { role: 'strategy_lead', label: '전략총괄', enabled: true, systemPrompt: '' },
  // Support agents (조건부 / 전용 역할)
  { role: 'devils_advocate', label: '악마의 변호인', enabled: true, systemPrompt: '' },
  { role: 'moderator', label: '진행자', enabled: true, systemPrompt: '' },
  { role: 'db_agent', label: '데이터 브리핑', enabled: true, systemPrompt: '' },
  { role: 'price_research', label: '시장가격 조사', enabled: true, systemPrompt: '' },
]

export type OutputLanguage = 'KR' | 'EN' | 'JP' | 'CH'

export const LANGUAGE_OPTIONS: { value: OutputLanguage; label: string; prompt: string }[] = [
  { value: 'KR', label: '한국어', prompt: '모든 답변과 분석을 한국어로 작성하세요.' },
  { value: 'EN', label: 'English', prompt: 'Write all responses and analysis in English.' },
  { value: 'JP', label: '日本語', prompt: 'すべての回答と分析を日本語で記述してください。' },
  { value: 'CH', label: '中文', prompt: '请用中文撰写所有回答和分析。' },
]

function mergeAgentPrompts(existing: AgentPromptOverride[]): AgentPromptOverride[] {
  // 기존 localStorage 데이터 + 새로 추가된 기본값을 병합.
  // 기존 역할은 설정 유지, 누락된 역할만 default로 추가.
  const byRole = new Map(existing.map(a => [a.role, a]))
  const merged: AgentPromptOverride[] = []
  for (const def of DEFAULT_AGENT_PROMPTS) {
    const found = byRole.get(def.role)
    merged.push(found ? { ...def, ...found } : { ...def })
  }
  // DEFAULT에 없는 사용자 정의 항목은 끝에 보존
  for (const a of existing) {
    if (!DEFAULT_AGENT_PROMPTS.some(d => d.role === a.role)) {
      merged.push(a)
    }
  }
  return merged
}

export const useSettingsStore = defineStore('settings', () => {
  const isOpen = ref(false)
  const agentPrompts = ref<AgentPromptOverride[]>(structuredClone(DEFAULT_AGENT_PROMPTS))
  const globalDirective = ref('')
  const customAgents = ref<CustomAgent[]>([])
  const outputLanguage = ref<OutputLanguage>('KR')

  // 한 번만 동작하는 마이그레이션: 이전 버전은 5개 core만 저장되어 있었다.
  // persist 복원 직후 누락된 support agents(devils_advocate, moderator, db_agent,
  // price_research)를 기본값으로 보강한다.
  watch(agentPrompts, (list) => {
    const hasAllDefaults = DEFAULT_AGENT_PROMPTS.every(def =>
      list.some(a => a.role === def.role),
    )
    if (!hasAllDefaults) {
      agentPrompts.value = mergeAgentPrompts(list)
    }
  }, { immediate: true, deep: false })

  /** 현재 선택된 언어의 LLM 프롬프트 지시문 */
  function languageDirective(): string {
    const opt = LANGUAGE_OPTIONS.find(o => o.value === outputLanguage.value)
    return opt?.prompt || LANGUAGE_OPTIONS[0].prompt
  }

  function open() { isOpen.value = true }
  function close() { isOpen.value = false }
  function toggle() { isOpen.value = !isOpen.value }

  function updatePrompt(role: string, systemPrompt: string) {
    const found = agentPrompts.value.find(a => a.role === role)
    if (found) found.systemPrompt = systemPrompt
  }

  function toggleAgent(role: string) {
    const found = agentPrompts.value.find(a => a.role === role)
    if (found) found.enabled = !found.enabled
  }

  function addCustomAgent() {
    customAgents.value.push({
      id: crypto.randomUUID(),
      name: '',
      role: '',
      persona: '',
      enabled: true,
    })
  }

  function removeCustomAgent(id: string) {
    customAgents.value = customAgents.value.filter(a => a.id !== id)
  }

  function resetAll() {
    agentPrompts.value = structuredClone(DEFAULT_AGENT_PROMPTS)
    globalDirective.value = ''
    customAgents.value = []
  }

  return {
    isOpen, agentPrompts, globalDirective, customAgents, outputLanguage,
    open, close, toggle, languageDirective,
    updatePrompt, toggleAgent,
    addCustomAgent, removeCustomAgent, resetAll,
  }
}, {
  persist: {
    pick: ['agentPrompts', 'globalDirective', 'customAgents', 'outputLanguage'],
  },
})

import { defineStore } from 'pinia'
import { ref, computed, watch, onMounted } from 'vue'
import { encrypt, decrypt } from '../utils/crypto'

export interface LLMAgent {
  id: string
  provider: 'openai' | 'anthropic'
  modelName: string
  apiKey: string
  baseUrl?: string
  enabled: boolean
  weight: number // 랜덤 선택 가중치 1~10
}

export const useLLMStore = defineStore('llm', () => {
  const agents = ref<LLMAgent[]>([
    {
      id: crypto.randomUUID(),
      provider: 'openai',
      modelName: 'gpt-4o',
      apiKey: '',
      enabled: true,
      weight: 5,
    }
  ])

  const multiAgentMode = ref(false)

  const enabledAgents = computed(() => agents.value.filter(a => a.enabled))

  const summary = computed(() => {
    const enabled = enabledAgents.value
    if (enabled.length === 0) return 'No Model'
    if (enabled.length === 1) return `${enabled[0].provider} / ${enabled[0].modelName}`
    return `${enabled.length} Models`
  })

  function addAgent() {
    agents.value.push({
      id: crypto.randomUUID(),
      provider: 'openai',
      modelName: '',
      apiKey: '',
      enabled: true,
      weight: 5,
    })
  }

  function removeAgent(id: string) {
    if (agents.value.length <= 1) return
    agents.value = agents.value.filter(a => a.id !== id)
  }

  // 가중치 기반 랜덤 에이전트 선택
  function pickRandom(): LLMAgent | null {
    const pool = enabledAgents.value
    if (pool.length === 0) return null
    if (!multiAgentMode.value || pool.length === 1) return pool[0]
    const total = pool.reduce((s, a) => s + a.weight, 0)
    let r = Math.random() * total
    for (const a of pool) {
      r -= a.weight
      if (r <= 0) return a
    }
    return pool[pool.length - 1]
  }

  // API 키 암호화 저장/복원
  async function saveEncrypted() {
    try {
      const data = { agents: agents.value, multiAgentMode: multiAgentMode.value }
      // apiKey만 암호화
      const encrypted = {
        ...data,
        agents: await Promise.all(data.agents.map(async a => ({
          ...a,
          apiKey: a.apiKey ? await encrypt(a.apiKey) : '',
        }))),
      }
      localStorage.setItem('llm_encrypted', JSON.stringify(encrypted))
    } catch {}
  }

  async function loadEncrypted() {
    try {
      const raw = localStorage.getItem('llm_encrypted')
      if (!raw) return
      const data = JSON.parse(raw)
      if (data.agents) {
        agents.value = await Promise.all(data.agents.map(async (a: any) => ({
          ...a,
          apiKey: a.apiKey ? await decrypt(a.apiKey) : '',
        })))
      }
      if (data.multiAgentMode !== undefined) multiAgentMode.value = data.multiAgentMode
    } catch {}
  }

  // 변경 시 자동 암호화 저장
  watch([agents, multiAgentMode], () => saveEncrypted(), { deep: true })

  // 초기 로드 + 평문 마이그레이션
  async function init() {
    // 1. 암호화 데이터가 있으면 로드
    if (localStorage.getItem('llm_encrypted')) {
      await loadEncrypted()
    }
    // 2. 기존 평문 persist 데이터 마이그레이션
    const legacy = localStorage.getItem('llm')
    if (legacy) {
      try {
        const data = JSON.parse(legacy)
        if (data.agents && data.agents.some((a: any) => a.apiKey?.startsWith('sk-'))) {
          agents.value = data.agents
          if (data.multiAgentMode !== undefined) multiAgentMode.value = data.multiAgentMode
          await saveEncrypted()  // 암호화 저장
          localStorage.removeItem('llm')  // 평문 삭제
        }
      } catch {}
    }
  }
  init()

  return { agents, multiAgentMode, enabledAgents, summary, addAgent, removeAgent, pickRandom }
}, {
  persist: false,  // 기본 persist 비활성화 (암호화 저장으로 대체)
})

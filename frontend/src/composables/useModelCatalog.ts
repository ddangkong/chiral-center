export interface ModelInfo {
  id: string
  name: string
  ctx: string
}

export interface ModelGroup {
  label: string
  models: ModelInfo[]
}

export const PROVIDERS = [
  { label: 'OpenAI',    value: 'openai',    logo: '&#9675;' },
  { label: 'Anthropic', value: 'anthropic', logo: '&#9651;' },
]

export const MODEL_CATALOG: Record<string, ModelGroup[]> = {
  openai: [
    {
      label: 'GPT-5.4 계열 (최신)',
      models: [
        { id: 'gpt-5.4',       name: 'GPT-5.4',       ctx: '1M' },
        { id: 'gpt-5.4-pro',   name: 'GPT-5.4 Pro',   ctx: '1M' },
        { id: 'gpt-5.4-mini',  name: 'GPT-5.4 Mini',  ctx: '1M' },
        { id: 'gpt-5.4-nano',  name: 'GPT-5.4 Nano',  ctx: '1M' },
      ]
    },
    {
      label: 'GPT-5 계열',
      models: [
        { id: 'gpt-5.2',       name: 'GPT-5.2',       ctx: '1M' },
        { id: 'gpt-5',         name: 'GPT-5',         ctx: '1M' },
      ]
    },
    {
      label: 'GPT-4.1 계열',
      models: [
        { id: 'gpt-4.1',       name: 'GPT-4.1',       ctx: '1M' },
        { id: 'gpt-4.1-mini',  name: 'GPT-4.1 Mini',  ctx: '1M' },
        { id: 'gpt-4.1-nano',  name: 'GPT-4.1 Nano',  ctx: '1M' },
      ]
    },
    {
      label: 'GPT-4o 계열',
      models: [
        { id: 'gpt-4o',        name: 'GPT-4o',        ctx: '128K' },
        { id: 'gpt-4o-mini',   name: 'GPT-4o Mini',   ctx: '128K' },
      ]
    },
    {
      label: 'o-시리즈 (추론)',
      models: [
        { id: 'o4-mini',       name: 'o4 Mini',       ctx: '200K' },
        { id: 'o3',            name: 'o3',            ctx: '200K' },
        { id: 'o3-mini',       name: 'o3 Mini',       ctx: '200K' },
        { id: 'o1',            name: 'o1',            ctx: '200K' },
      ]
    },
  ],
  anthropic: [
    {
      label: 'Claude 4.x (최신)',
      models: [
        { id: 'claude-opus-4-6',           name: 'Claude Opus 4.6',   ctx: '1M' },
        { id: 'claude-sonnet-4-6',         name: 'Claude Sonnet 4.6', ctx: '1M' },
        { id: 'claude-haiku-4-5-20251001', name: 'Claude Haiku 4.5',  ctx: '200K' },
      ]
    },
    {
      label: 'Claude 3.x (레거시)',
      models: [
        { id: 'claude-3-5-sonnet-20241022', name: 'Claude 3.5 Sonnet', ctx: '200K' },
        { id: 'claude-3-5-haiku-20241022',  name: 'Claude 3.5 Haiku',  ctx: '200K' },
      ]
    },
  ],
}

export function getModelGroups(provider: string): ModelGroup[] {
  return MODEL_CATALOG[provider] ?? []
}

export function getDefaultModel(provider: string): string {
  const groups = MODEL_CATALOG[provider] ?? []
  return groups[0]?.models[0]?.id ?? ''
}

export function getModelPlaceholder(provider: string): string {
  return getDefaultModel(provider) || 'Enter model name'
}

export function getModelCtx(provider: string, modelId: string): string {
  for (const g of MODEL_CATALOG[provider] ?? []) {
    const found = g.models.find(m => m.id === modelId)
    if (found) return found.ctx
  }
  return ''
}

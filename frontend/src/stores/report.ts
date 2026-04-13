import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import { useProjectStore } from './project'

export interface ReportSection {
  title: string
  content: string
  order: number
}

export const useReportStore = defineStore('report', () => {
  const projectStore = useProjectStore()

  const reportId = ref('')
  const title = ref('')
  const markdown = ref('')
  const sections = ref<ReportSection[]>([])
  const isGenerating = ref(false)
  const currentStep = ref('')
  const error = ref('')

  async function generate(
    simulationId: string,
    ontologyId: string,
    topic: string,
    llmConfig: { provider: string; model: string; api_key: string; base_url?: string },
  ) {
    isGenerating.value = true
    currentStep.value = '보고서 생성 요청 중...'
    error.value = ''
    sections.value = []
    markdown.value = ''

    try {
      currentStep.value = 'LangGraph 워크플로우 실행 중...'
      const res = await api('/report/generate', {
        method: 'POST',
        body: JSON.stringify({
          simulation_id: simulationId,
          ontology_id: ontologyId,
          topic,
          llm: llmConfig,
        }),
      })

      reportId.value = res.id
      title.value = res.title || ''
      markdown.value = res.markdown || ''
      sections.value = (res.sections || []).map((s: any, i: number) => ({
        title: s.title,
        content: s.content || '',
        order: s.order ?? i,
      }))
      currentStep.value = '완료'

      // Project 연동: 보고서 버전 추가
      projectStore.addReportVersion({
        id: res.id,
        title: res.title || '',
        sectionCount: sections.value.length,
        model: llmConfig.model,
        provider: llmConfig.provider,
        simulationId,
        ontologyId: ontologyId,
        sections: sections.value,
        markdown: markdown.value,
      })
    } catch (err: any) {
      error.value = err.message
      currentStep.value = '에러 발생'
    } finally {
      isGenerating.value = false
    }
  }

  async function exportMarkdown() {
    if (!reportId.value) return
    try {
      const res = await api(`/report/${reportId.value}/export?format=markdown`)
      // Create download
      const blob = new Blob([typeof res === 'string' ? res : JSON.stringify(res)], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report_${reportId.value.slice(0, 8)}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch {}
  }

  function loadVersion(rv: import('./project').ReportVersion) {
    reportId.value = rv.id
    title.value = rv.title
    sections.value = rv.sections ?? []
    markdown.value = rv.markdown ?? ''
    error.value = ''
  }

  return {
    reportId, title, markdown, sections,
    isGenerating, currentStep, error,
    generate, exportMarkdown, loadVersion,
  }
}, {
  persist: {
    pick: ['reportId', 'title', 'markdown', 'sections'],
  },
})

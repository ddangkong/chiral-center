<template>
  <div class="report-view">

    <!-- Left: TOC -->
    <div class="toc-panel">
      <div class="toc-header">
        <span class="toc-title">{{ t('report.toc') }}</span>
        <span class="toc-doc mono">
          {{ projectStore.activeReport ? `v${projectStore.activeReport.version}` : (reportStore.reportId ? reportStore.reportId.slice(0, 6) : '—') }}
        </span>
      </div>
      <nav class="toc-nav">
        <template v-if="hasReport">
          <div
            v-for="chapter in chapters"
            :key="chapter.id"
            class="toc-item"
            :class="{ active: activeChapter === chapter.id }"
            @click="scrollToSection(chapter.id)"
          >
            <span class="toc-num mono">{{ chapter.num }}</span>
            <span class="toc-label">{{ chapter.title }}</span>
          </div>
        </template>
        <div v-else class="toc-empty">
          {{ t('report.tocEmpty') }}
        </div>
      </nav>
      <div class="toc-meta">
        <div class="meta-item">
          <span class="meta-key">{{ t('report.metaDate') }}</span>
          <span class="meta-val mono">{{ today }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-key">{{ t('report.metaRounds') }}</span>
          <span class="meta-val mono">{{ simStore.totalRounds }} rounds</span>
        </div>
        <div class="meta-item">
          <span class="meta-key">{{ t('report.metaAgents') }}</span>
          <span class="meta-val mono">{{ simStore.agents.length }} agents</span>
        </div>
        <div class="meta-item">
          <span class="meta-key">{{ t('report.metaEvents') }}</span>
          <span class="meta-val mono">{{ eventCount }} events</span>
        </div>
      </div>
      <!-- 보고서 버전 이력 -->
      <div v-if="projectStore.activeSimulationReports.length > 0" class="version-history">
        <div class="version-history-title mono">{{ t('report.versions') }}</div>
        <div
          v-for="rv in [...projectStore.activeSimulationReports].reverse()"
          :key="rv.id"
          class="version-row"
          :class="{ active: rv.id === selectedReportId }"
          @click="selectedReportId = rv.id"
        >
          <span class="version-badge mono">v{{ rv.version }}</span>
          <div class="version-info">
            <div class="version-model mono">{{ rv.model }}</div>
            <div class="version-date mono">{{ projectStore.fmtDate(rv.createdAt) }}</div>
          </div>
          <span v-if="rv.id === selectedReportId" class="version-active-dot">●</span>
        </div>
      </div>
    </div>

    <!-- Right: Report Body -->
    <div class="report-body">

      <!-- Export Bar -->
      <div class="export-bar">
        <div class="export-left">
          <span class="report-badge mono">{{ hasReport ? 'FINAL REPORT' : 'REPORT' }}</span>
          <span v-if="reportStore.reportId" class="report-id mono">#{{ reportStore.reportId.slice(0, 6) }}</span>
        </div>
        <div class="export-right">
          <!-- 시뮬레이션 버전 선택 (현재 온톨로지 기반만) -->
          <div v-if="projectStore.activeOntologySimulations.length > 1" class="sim-picker">
            <span class="sim-picker-label mono">시뮬</span>
            <select class="sim-picker-select" v-model="selectedSimId">
              <option v-for="s in projectStore.activeOntologySimulations" :key="s.id" :value="s.id">
                v{{ s.version }} · {{ s.rounds }}R · {{ s.model }}
              </option>
            </select>
          </div>
          <!-- 보고서 버전 선택 (현재 시뮬레이션 기반만) -->
          <div v-if="projectStore.activeSimulationReports.length > 1" class="sim-picker">
            <span class="sim-picker-label mono">보고서</span>
            <select class="sim-picker-select" v-model="selectedReportId">
              <option v-for="r in projectStore.activeSimulationReports" :key="r.id" :value="r.id">
                v{{ r.version }} · {{ r.sectionCount }}섹션 · {{ r.model }}
              </option>
            </select>
          </div>
          <button v-if="hasReport" class="btn-secondary" @click="reportStore.exportMarkdown()">{{ t('report.download') }}</button>
          <button
            v-if="(selectedSimId || simStore.simId) && !isGenerating"
            class="btn-primary"
            @click="generateReport"
          >
            {{ hasReport ? t('report.regenerate') : t('report.generate') }}
          </button>
        </div>
      </div>

      <!-- Content Area -->
      <div class="report-content">

        <!-- Empty: no simulation -->
        <div v-if="!simStore.simId && !hasReport" class="center-state">
          <div class="state-icon">📋</div>
          <div class="state-title">{{ t('report.needSimTitle') }}</div>
          <div class="state-desc">{{ t('report.needSimDesc') }}</div>
        </div>

        <!-- Generating -->
        <div v-else-if="isGenerating" class="center-state">
          <div class="spinner"></div>
          <div class="state-title">{{ reportStore.currentStep }}</div>
          <div class="state-elapsed mono">{{ formatElapsed(elapsed) }}</div>
          <div class="state-desc">LangGraph 워크플로우로 보고서를 생성하고 있습니다...</div>
        </div>

        <!-- Error -->
        <div v-else-if="reportStore.error && !hasReport" class="center-state">
          <div class="state-icon error-icon">⚠</div>
          <div class="state-title">생성 실패</div>
          <div class="state-desc">{{ reportStore.error }}</div>
          <button class="btn-primary" style="margin-top:16px" @click="generateReport">다시 시도</button>
        </div>

        <!-- Report -->
        <template v-else-if="hasReport">
          <div class="report-inner">
            <!-- Title -->
            <div class="report-title-block">
              <h1 class="report-main-title">{{ reportStore.title || '분석 보고서' }}</h1>
              <div class="report-meta-row">
                <span>플랫폼: {{ simStore.platform }}</span>
                <span class="sep">·</span>
                <span>라운드: {{ simStore.totalRounds }}</span>
                <span class="sep">·</span>
                <span>에이전트: {{ simStore.agents.length }}명</span>
                <span class="sep">·</span>
                <span>{{ today }}</span>
                <span class="sep">·</span>
                <span>{{ currentModelLabel }}</span>
              </div>
            </div>

            <!-- Agent table -->
            <div v-if="simStore.agents.length > 0" class="report-section">
              <h2 class="section-h2">에이전트 구성</h2>
              <div class="data-table">
                <table>
                  <thead>
                    <tr>
                      <th>에이전트</th>
                      <th>역할</th>
                      <th>스탠스</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="agent in simStore.agents" :key="agent.id">
                      <td class="mono">
                        <span class="agent-dot" :style="{ background: agent.color }"></span>
                        {{ agent.name }}
                      </td>
                      <td>{{ agent.role || '—' }}</td>
                      <td><span class="stance-chip" :class="agent.stance">{{ stanceKr(agent.stance) }}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Dynamic sections -->
            <section
              v-for="(sec, idx) in renderedSections"
              :key="idx"
              :id="`sec${idx}`"
              class="report-section"
            >
              <h2 class="section-h2">{{ idx + 1 }}. {{ sec.title }}</h2>
              <div class="section-content" v-html="sec.html"></div>
            </section>

            <!-- Fallback: full markdown -->
            <div v-if="reportStore.sections.length === 0 && renderedMarkdown" class="report-section">
              <div class="section-content" v-html="renderedMarkdown"></div>
            </div>
          </div>
        </template>

        <!-- Ready to generate -->
        <div v-else class="center-state">
          <div class="state-icon">📊</div>
          <div class="state-title">보고서 생성 준비 완료</div>
          <div class="state-desc">
            시뮬레이션 ID: <span class="mono">{{ simStore.simId.slice(0, 8) }}</span><br/>
            {{ simStore.agents.length }}명의 에이전트 · {{ eventCount }}개 이벤트 · {{ simStore.totalRounds }} 라운드
          </div>
          <button class="btn-generate" @click="generateReport">
            ▶ 보고서 생성하기
          </button>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useLLMStore } from '../stores/llm'
import { useDocumentStore } from '../stores/document'
import { useSimulationStore } from '../stores/simulation'
import { useReportStore } from '../stores/report'
import { useProjectStore } from '../stores/project'
import { useI18n } from '../composables/useI18n'

const llmStore = useLLMStore()
const docStore = useDocumentStore()
const simStore = useSimulationStore()
const reportStore = useReportStore()
const projectStore = useProjectStore()
const { t } = useI18n()

// 시뮬레이션 버전 선택 (현재 온톨로지에 속한 것만)
const selectedSimId = computed({
  get: () => projectStore.currentProject?.activeSimulationId ?? simStore.simId,
  set: (v) => { if (projectStore.currentProject) projectStore.setActiveSimulation(v) },
})

// 보고서 버전 선택 (현재 시뮬레이션에 속한 것만)
const selectedReportId = computed({
  get: () => projectStore.currentProject?.activeReportId ?? reportStore.reportId,
  set: (v) => { if (projectStore.currentProject) projectStore.setActiveReport(v) },
})

// activeReport 변경 시 콘텐츠 동기화
watch(
  () => projectStore.activeReport,
  (rv) => { if (rv) reportStore.loadVersion(rv) },
  { immediate: true }
)

const activeChapter = ref('sec0')
const today = new Date().toISOString().slice(0, 10)

const eventCount = computed(() =>
  simStore.eventLog.filter((e: any) => e.type === 'event').length
)

const currentModelLabel = computed(() => {
  const agent = llmStore.enabledAgents[0]
  return agent ? `${agent.provider} ${agent.modelName}` : '—'
})

const chapters = computed(() =>
  reportStore.sections.map((s, i) => ({ id: `sec${i}`, num: `${i + 1}.`, title: s.title }))
)

const isGenerating = computed(() => reportStore.isGenerating)
const hasReport = computed(() => reportStore.sections.length > 0 || !!reportStore.markdown)

// Memoize rendered markdown — prevents re-running regex on every render
const renderedSections = computed(() =>
  reportStore.sections.map(s => ({ title: s.title, html: renderMarkdown(s.content) }))
)
const renderedMarkdown = computed(() =>
  reportStore.markdown ? renderMarkdown(reportStore.markdown) : ''
)

// Elapsed timer
const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
watch(isGenerating, (val) => {
  if (val) { elapsed.value = 0; timer = setInterval(() => elapsed.value++, 1000) }
  else { if (timer) { clearInterval(timer); timer = null } }
})
onUnmounted(() => { if (timer) clearInterval(timer) })

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

async function generateReport() {
  const simId = selectedSimId.value || simStore.simId
  if (!simId) { alert('시뮬레이션을 먼저 실행해주세요.'); return }
  const agent = llmStore.enabledAgents[0]
  if (!agent?.apiKey) { alert('LLM 모델과 API 키를 설정해주세요.'); return }

  // Resolve ontology from project or fallback
  const ontId = projectStore.activeOntology?.id ?? docStore.ontologyId
  const topic = projectStore.activeOntology?.topic ?? docStore.ontologyTopic ?? ''

  // Restore simulation to backend in case it was lost after server restart
  try {
    await fetch('/api/simulation/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        sim_id: simId,
        topic,
        total_rounds: simStore.totalRounds,
        events: simStore.eventLog
          .filter(e => e.type === 'event')
          .map(e => ({ round: e.round, agentId: e.agentId, agentName: e.agentName, action: e.action, content: e.content })),
      }),
    })
  } catch { /* non-critical */ }

  await reportStore.generate(
    simId,
    ontId,
    topic,
    { provider: agent.provider, model: agent.modelName, api_key: agent.apiKey, base_url: agent.baseUrl || undefined },
  )
}

function scrollToSection(id: string) {
  activeChapter.value = id
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function stanceKr(s: string): string {
  return ({ supportive: '지지', opposing: '반대', neutral: '중립' } as Record<string, string>)[s] || s
}

function renderMarkdown(md: string): string {
  if (!md) return ''
  let html = md
    .replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
    .replace(/^# (.+)$/gm, '<h3 class="md-h3">$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code class="md-code">$1</code>')
    .replace(/^---$/gm, '<hr class="md-hr"/>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li class="ordered">$1</li>')
    .replace(/(<li>.*?<\/li>)/gs, '<ul class="md-list">$1</ul>')
    .replace(/<\/ul>\s*<ul class="md-list">/g, '')
    .replace(/\n{2,}/g, '</p><p class="md-p">')
    .replace(/\n/g, '<br/>')
  return `<p class="md-p">${html}</p>`
}
</script>

<style scoped>
.report-view {
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* ─── TOC ─────────────────────────────────────── */
.toc-panel {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid #EAEAEA;
  display: flex;
  flex-direction: column;
  background: #FAFAFA;
  overflow: hidden;
}
.toc-header {
  height: 48px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px; border-bottom: 1px solid #EAEAEA; flex-shrink: 0;
}
.toc-title { font-size: 13px; font-weight: 700; color: #000; }
.toc-doc   { font-size: 10px; color: #AAA; }

.toc-nav { flex: 1; overflow-y: auto; padding: 8px 0; }
.toc-item {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 7px 16px; cursor: pointer; transition: all 0.15s;
  border-left: 2px solid transparent;
}
.toc-item:hover { background: #F0F0F0; }
.toc-item.active { background: #FFF3F0; border-left-color: #FF5722; }
.toc-num   { font-size: 10px; color: #AAA; min-width: 22px; padding-top: 1px; flex-shrink: 0; }
.toc-label { font-size: 12px; color: #333; line-height: 1.4; }
.toc-item.active .toc-label { color: #FF5722; font-weight: 600; }

.toc-empty {
  padding: 24px 16px;
  font-size: 12px; color: #BBB; line-height: 1.7; text-align: center;
}

.toc-meta {
  padding: 12px 16px; border-top: 1px solid #EAEAEA; flex-shrink: 0;
  display: flex; flex-direction: column; gap: 6px;
}
.meta-item { display: flex; justify-content: space-between; align-items: center; }
.meta-key { font-size: 10px; color: #AAA; }
.meta-val { font-size: 10px; color: #555; }

/* ─── Report Body ─────────────────────────────── */
.report-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.export-bar {
  height: 48px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 32px; border-bottom: 1px solid #EAEAEA; background: #FFF;
}
.export-left  { display: flex; align-items: center; gap: 10px; }
.export-right { display: flex; gap: 8px; }

.report-badge {
  padding: 3px 10px; background: #000; color: #FFF;
  border-radius: 4px; font-size: 10px; letter-spacing: 1px;
}
.report-id { font-size: 11px; color: #AAA; }

.btn-primary {
  padding: 6px 14px; background: #000; color: #FFF;
  border: none; border-radius: 5px; font-size: 12px; cursor: pointer;
  font-family: 'Space Grotesk', sans-serif; transition: all 0.15s;
}
.btn-primary:hover { background: #FF5722; transform: translateY(-1px); }

.sim-picker { display: flex; align-items: center; gap: 6px; }
.sim-picker-label { font-size: 10px; color: #AAA; letter-spacing: 0.5px; font-family: 'JetBrains Mono', monospace; }
.sim-picker-select { padding: 5px 8px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 11px; font-family: 'JetBrains Mono', monospace; background: #FFF; color: #333; outline: none; cursor: pointer; }
.sim-picker-select:focus { border-color: #FF5722; }

.btn-secondary {
  padding: 6px 14px; background: transparent; color: #555;
  border: 1px solid #DCDCDC; border-radius: 5px; font-size: 12px; cursor: pointer;
  font-family: 'Space Grotesk', sans-serif; transition: all 0.15s;
}
.btn-secondary:hover { border-color: #FF5722; color: #FF5722; transform: translateY(-1px); }

/* ─── Content scroll container ────────────────── */
.report-content {
  flex: 1; overflow-y: auto;
  display: flex; flex-direction: column;
  background: #FFF;
}

/* ─── Centered states ─────────────────────────── */
.center-state {
  flex: 1;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; padding: 48px 24px; text-align: center;
}
.state-icon  { font-size: 36px; }
.state-title { font-size: 16px; font-weight: 600; color: #222; }
.state-desc  { font-size: 13px; color: #888; line-height: 1.7; }
.state-elapsed { font-size: 22px; color: #FF5722; letter-spacing: 2px; }
.error-icon  { color: #FF5722; }

.spinner {
  width: 36px; height: 36px; border-radius: 50%;
  border: 3px solid #F0F0F0; border-top-color: #FF5722;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.btn-generate {
  margin-top: 8px; padding: 10px 28px;
  background: #000; color: #FFF; border: none; border-radius: 6px;
  font-size: 14px; font-weight: 600; cursor: pointer;
  font-family: 'Space Grotesk', sans-serif; transition: all 0.15s;
}
.btn-generate:hover { background: #FF5722; transform: translateY(-2px); }

/* ─── Report inner layout ─────────────────────── */
.report-inner {
  max-width: 820px;
  width: 100%;
  margin: 0 auto;
  padding: 40px 48px 60px;
  display: flex; flex-direction: column; gap: 36px;
}

/* ─── Title block ─────────────────────────────── */
.report-title-block {
  padding-bottom: 24px;
  border-bottom: 1px solid #EAEAEA;
  display: flex; flex-direction: column; gap: 10px;
}
.report-main-title {
  font-size: 26px; font-weight: 700; color: #000; line-height: 1.3;
}
.report-meta-row {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  font-size: 11px; color: #AAA;
}
.sep { color: #DDD; }

/* ─── Section ─────────────────────────────────── */
.report-section { display: flex; flex-direction: column; gap: 14px; }
.section-h2 {
  font-size: 18px; font-weight: 700; color: #000;
  padding-bottom: 8px; border-bottom: 1px solid #F0F0F0;
}

/* section-content: v-html 내부 스타일은 :deep() 필수 */
.section-content { line-height: 1.8; }

.section-content :deep(.md-p) {
  font-size: 13px; color: #444; line-height: 1.8; margin-bottom: 12px;
}
.section-content :deep(.md-h3) {
  font-size: 15px; font-weight: 700; color: #111; margin: 20px 0 8px;
}
.section-content :deep(.md-h4) {
  font-size: 13px; font-weight: 600; color: #333; margin: 16px 0 6px;
}
.section-content :deep(.md-list) {
  padding-left: 20px; margin: 8px 0 12px; display: flex; flex-direction: column; gap: 5px;
}
.section-content :deep(.md-list li) {
  font-size: 13px; color: #444; line-height: 1.6;
}
.section-content :deep(.md-code) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px; background: #F4F4F4; color: #D32F2F;
  padding: 1px 5px; border-radius: 3px;
}
.section-content :deep(.md-hr) {
  border: none; border-top: 1px solid #EAEAEA; margin: 16px 0;
}
.section-content :deep(strong) { color: #000; font-weight: 600; }
.section-content :deep(em)     { color: #555; }

/* ─── Agent table ─────────────────────────────── */
.data-table { overflow-x: auto; }
.data-table table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th {
  padding: 8px 12px; text-align: left; background: #F7F7F7;
  border: 1px solid #EAEAEA; font-weight: 600; color: #333; font-size: 11px;
}
.data-table td { padding: 8px 12px; border: 1px solid #EAEAEA; color: #444; vertical-align: middle; }
.data-table tr:hover td { background: #FAFAFA; }

.agent-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 6px; flex-shrink: 0; vertical-align: middle;
}
.stance-chip {
  padding: 2px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 600; font-family: 'JetBrains Mono', monospace;
}
.stance-chip.supportive { background: #E8F5E9; color: #2E7D32; }
.stance-chip.opposing   { background: #FFEBEE; color: #C62828; }
.stance-chip.neutral    { background: #F5F5F5; color: #616161; }

/* ─── 버전 이력 ────────────────────────────────── */
.version-history {
  flex-shrink: 0;
  border-top: 1px solid #EAEAEA;
  padding: 8px 0;
}
.version-history-title {
  font-size: 9px; color: #BBB; letter-spacing: 1px;
  text-transform: uppercase; padding: 4px 16px 8px;
}
.version-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 16px; cursor: pointer; transition: background 0.15s;
  border-left: 2px solid transparent;
}
.version-row:hover { background: #F5F5F5; }
.version-row.active { background: #FFF3F0; border-left-color: #FF5722; }
.version-badge {
  font-size: 10px; font-weight: 700; color: #FF5722;
  background: #FFF3F0; padding: 1px 6px; border-radius: 4px; flex-shrink: 0;
}
.version-row.active .version-badge { background: #FF5722; color: #FFF; }
.version-info { flex: 1; display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.version-model { font-size: 10px; color: #555; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.version-date { font-size: 9px; color: #AAA; }
.version-active-dot { font-size: 8px; color: #FF5722; flex-shrink: 0; }

.mono { font-family: 'JetBrains Mono', monospace; }
</style>

<template>
  <div class="ontology-view">

    <!-- Left: Graph Canvas -->
    <div class="graph-panel">

      <div class="graph-toolbar">
        <div class="toolbar-left">
          <span class="panel-title">{{ t('graph.title') }}</span>
          <!-- 버전 선택기 -->
          <select
            v-if="ontologyVersions.length > 1"
            class="version-select mono"
            :value="activeOntologyId"
            @change="onVersionChange"
          >
            <option
              v-for="v in ontologyVersions"
              :key="v.id"
              :value="v.id"
            >v{{ v.version }} — {{ v.provider }}/{{ v.model }} ({{ v.nodeCount }}n · {{ v.edgeCount }}e)</option>
          </select>
          <span v-else-if="ontologyVersions.length === 1" class="version-badge mono">v{{ ontologyVersions[0].version }}</span>
          <span class="node-count mono">{{ nodeCount }} nodes · {{ edgeCount }} edges</span>
          <span v-if="loading" class="loading-badge">{{ t('graph.loading') }}</span>
          <span v-if="error" class="error-badge">{{ error }}</span>
        </div>
        <div class="toolbar-right">
          <button class="ctrl-btn" @click="zoomIn">+</button>
          <span class="zoom-label mono">{{ Math.round(currentZoom * 100) }}%</span>
          <button class="ctrl-btn" @click="zoomOut">−</button>
          <button class="ctrl-btn" @click="zoomReset">⊙</button>
          <div class="toolbar-divider"></div>
          <button
            class="ctrl-btn"
            :class="{ 'active-filter': colorMode === 'type' }"
            @click="toggleColorMode('type')"
          >{{ t('graph.byType') }}</button>
          <button
            class="ctrl-btn"
            :class="{ 'active-filter': colorMode === 'community' }"
            @click="toggleColorMode('community')"
            :disabled="communities.length === 0"
          >{{ t('graph.community') }}</button>
          <div class="toolbar-divider"></div>
          <button class="ctrl-btn" :class="{ 'active-filter': showForcePanel }" @click="showForcePanel = !showForcePanel">⚙</button>
        </div>
      </div>

      <!-- SVG canvas — D3 manages internals -->
      <div class="graph-canvas" ref="canvasEl">
        <svg ref="svgEl" class="graph-svg"></svg>

        <!-- Force Settings Panel -->
        <Transition name="slide">
          <div v-if="showForcePanel" class="force-panel">
            <div class="fp-title">{{ t('graph.settings') }}</div>
            <div class="fp-row" v-for="s in forceSliders" :key="s.key">
              <div class="fp-label">{{ s.label }} <span class="fp-val mono">{{ s.ref.value }}</span></div>
              <input type="range" class="fp-slider" :min="s.min" :max="s.max" :step="s.step" v-model.number="s.ref.value" @input="applyForce" />
            </div>
            <button class="fp-reset" @click="resetForce">{{ t('graph.resetForce') }}</button>
          </div>
        </Transition>

        <div v-if="docStore.isExtracting" class="canvas-overlay">
          <div class="overlay-spinner"></div>
          <div class="overlay-text">{{ docStore.currentStep || '지식 그래프 추출 중...' }}</div>
          <div v-if="docStore.extractionProgress > 0" class="overlay-progress mono">{{ docStore.extractionProgress }}%</div>
        </div>
        <div v-else-if="loading" class="canvas-overlay">
          <div class="overlay-spinner"></div>
          <div class="overlay-text">그래프 데이터 로드 중...</div>
        </div>

        <div v-if="!loading && !building && ontologyMissing" class="canvas-empty">
          <div class="empty-icon">⚠</div>
          <div class="empty-title">{{ t('graph.missingTitle') }}</div>
          <div class="empty-desc">{{ t('graph.missingDesc') }}</div>
        </div>

        <div v-else-if="!loading && !building && nodeCount === 0" class="canvas-empty">
          <div class="empty-icon">⬡</div>
          <div class="empty-title">{{ t('graph.empty') }}</div>
          <div class="empty-desc" v-html="t('graph.emptyDesc')"></div>
        </div>
      </div>

      <div class="graph-legend">
        <span class="legend-label">{{ colorMode === 'community' ? t('graph.community') : t('graph.legend') }}</span>
        <span class="legend-hint" v-if="colorMode === 'community'">
          {{ t('graph.communityHint') }}
        </span>
        <span class="legend-hint" v-else>
          {{ t('graph.legendHint') }}
        </span>
        <template v-if="colorMode === 'community'">
          <div v-for="c in communities" :key="c.id" class="legend-item legend-clickable"
            :class="{ 'legend-active': selectedCommunity?.id === c.id }"
            @click="selectCommunity(c)">
            <span class="legend-dot" :style="{ background: communityColor(c.id) }"></span>
            <span class="legend-text">C{{ c.id }} ({{ c.size }})</span>
          </div>
        </template>
        <template v-else>
          <div v-for="item in legendItems" :key="item.type" class="legend-item">
            <span class="legend-dot" :style="{ background: item.color }"></span>
            <span class="legend-text">{{ item.type }}</span>
            <span class="legend-count mono">{{ item.count }}</span>
          </div>
        </template>
      </div>
    </div>

    <!-- Right: Detail Panel -->
    <div class="detail-panel">
      <div class="detail-header">
        <span class="detail-title">{{ t('graph.nodeDetail') }}</span>
        <button v-if="selectedNode" class="detail-close" @click="selectedNode = null">✕</button>
      </div>

      <div v-if="!selectedNode" class="detail-empty">
        <div class="detail-empty-icon">◎</div>
        <div class="detail-empty-text" v-html="t('graph.clickNode').replace('\\n', '<br/>')"></div>
      </div>

      <div v-else class="detail-content">
        <div class="detail-section">
          <div class="detail-node-name">{{ selectedNode.name }}</div>
          <div
            class="detail-node-type-badge"
            :style="{ background: nodeColor(selectedNode.type) + '22', color: nodeColor(selectedNode.type) }"
          >{{ selectedNode.type }}</div>
        </div>

        <div v-if="selectedNode.description" class="detail-section">
          <div class="detail-section-title">{{ t('graph.description') }}</div>
          <div class="detail-desc">{{ selectedNode.description }}</div>
        </div>

        <div v-if="Object.keys(selectedNode.attributes || {}).length > 0" class="detail-section">
          <div class="detail-section-title">{{ t('graph.attributes') }}</div>
          <div class="prop-list">
            <div v-for="(val, key) in selectedNode.attributes" :key="key" class="prop-item">
              <span class="prop-key mono">{{ key }}</span>
              <span class="prop-val">{{ val }}</span>
            </div>
          </div>
        </div>

        <div class="detail-section">
          <div class="detail-section-title">{{ t('graph.relations') }} ({{ getNodeRelations(selectedNode.id).length }})</div>
          <div v-if="getNodeRelationSummary(selectedNode.id).length" class="relation-summary-list">
            <div
              v-for="item in getNodeRelationSummary(selectedNode.id)"
              :key="item.label"
              class="relation-summary-item"
            >
              <span class="relation-summary-label mono">{{ item.label }}</span>
              <span class="relation-summary-count">{{ item.count }}</span>
            </div>
          </div>
          <div class="relation-list">
            <div
              v-for="rel in getNodeRelations(selectedNode.id)"
              :key="rel.id"
              class="relation-item"
            >
              <span class="rel-direction">{{ rel.direction === 'out' ? '→' : '←' }}</span>
              <span class="rel-label mono">{{ rel.label }}</span>
              <span class="rel-target">{{ rel.peerName }}</span>
            </div>
            <div v-if="getNodeRelations(selectedNode.id).length === 0" class="no-relations">{{ t('graph.none') }}</div>
          </div>
        </div>
      </div>

      <!-- Community detail (when community selected) -->
      <div v-if="selectedCommunity && !selectedNode" class="detail-content">
        <div class="detail-section">
          <div class="detail-node-name">커뮤니티 {{ selectedCommunity.id }}</div>
          <div class="detail-node-type-badge"
            :style="{ background: communityColor(selectedCommunity.id) + '22', color: communityColor(selectedCommunity.id) }">
            {{ selectedCommunity.size }} members
          </div>
        </div>
        <div v-if="selectedCommunity.summary" class="detail-section">
          <div class="detail-section-title">{{ t('graph.summary') }}</div>
          <div class="detail-desc">{{ selectedCommunity.summary }}</div>
        </div>
        <div class="detail-section">
          <div class="detail-section-title">{{ t('graph.members') }}</div>
          <div class="relation-list">
            <div v-for="name in selectedCommunity.member_names" :key="name" class="relation-item">
              <span class="rel-direction" :style="{ color: communityColor(selectedCommunity.id) }">●</span>
              <span class="rel-target">{{ name }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="detail-actions">
        <!-- Community summarize button -->
        <button
          v-if="communities.length > 0"
          class="btn-build"
          :disabled="summarizing"
          @click="doSummarize"
          style="background: #3498db"
        >
          {{ summarizing ? t('graph.summarize') + '...' : t('graph.summarize') }}
        </button>

        <button
          class="btn-build"
          :disabled="building || !docStore.ontologyId"
          @click="buildGraph"
        >
          {{ building ? buildStepLabel : t('graph.build') }}
        </button>

        <!-- Progress bar (visible during build) -->
        <div v-if="building" class="build-progress">
          <div class="build-progress-bar" :style="{ width: buildProgress + '%' }"></div>
        </div>
        <div v-if="building" class="build-progress-label mono">{{ buildProgress }}%</div>

        <button class="btn-export" @click="exportJSON" :disabled="nodeCount === 0">{{ t('graph.export') }}</button>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useDocumentStore } from '../stores/document'
import { useProjectStore } from '../stores/project'
import { useLLMStore } from '../stores/llm'
import { useI18n } from '../composables/useI18n'
import { getGraphData, buildGraph as apiBuildGraph, startGraphBuild, summarizeCommunities as apiSummarize } from '../api/graph'
import { getTask } from '../api/tasks'

const docStore = useDocumentStore()
const projectStore = useProjectStore()
const llmStore = useLLMStore()
const { t } = useI18n()

const svgEl = ref<SVGSVGElement | null>(null)
const canvasEl = ref<HTMLDivElement | null>(null)

const loading = ref(false)
const building = ref(false)
const error = ref('')
const ontologyMissing = ref(false)  // backend lost ontology after restart
const currentZoom = ref(1)
const nodeCount = ref(0)
const edgeCount = ref(0)
const filterType = ref('all')
const selectedNode = ref<any>(null)
const colorMode = ref<'type' | 'community'>('type')
const communities = ref<any[]>([])
const selectedCommunity = ref<any>(null)
const summarizing = ref(false)

// ── 버전 선택 ──
const ontologyVersions = computed(() => projectStore.currentProject?.ontologies ?? [])
const activeOntologyId = computed(() => {
  const p = projectStore.currentProject
  if (!p) return ''
  const versions = p.ontologies
  return p.activeOntologyId ?? versions[versions.length - 1]?.id ?? ''
})

function onVersionChange(e: Event) {
  const id = (e.target as HTMLSelectElement).value
  if (id && id !== activeOntologyId.value) {
    projectStore.setActiveOntology(id)
    // docStore.ontologyId는 setActiveOntology 내부에서 동기화됨
  }
}

// Build progress
const buildProgress = ref(0)
const buildStepLabel = ref('빌드 중...')
let progressTimer: ReturnType<typeof setInterval> | null = null
let buildPollRunId = 0

const BUILD_STEPS = [
  { pct: 10, label: '지식 그래프 로드 중...' },
  { pct: 30, label: '노드 생성 중...' },
  { pct: 55, label: '엣지 연결 중...' },
  { pct: 75, label: '그래프 구조 검증 중...' },
  { pct: 88, label: '저장 중...' },
  { pct: 95, label: '마무리 중...' },
]

function startBuildProgress() {
  buildProgress.value = 0
  buildStepLabel.value = '빌드 준비 중...'
  return
  buildStepLabel.value = '빌드 중...'
  let stepIdx = 0
  progressTimer = setInterval(() => {
    if (stepIdx < BUILD_STEPS.length) {
      const step = BUILD_STEPS[stepIdx]
      buildProgress.value = step.pct
      buildStepLabel.value = step.label
      stepIdx++
    } else {
      // Hold at 95% until done
      buildProgress.value = Math.min(buildProgress.value + 0.3, 95)
    }
  }, 600)
}

function finishBuildProgress() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
  buildProgress.value = 100
  buildStepLabel.value = '완료!'
  buildStepLabel.value = '완료!'
  setTimeout(() => { buildProgress.value = 0 }, 800)
}

// ── Force parameter controls ──
const showForcePanel = ref(false)
const fCharge = ref(-800)
const fLinkDist = ref(200)
const fLinkStrength = ref(0.35)
const fDistMax = ref(700)
const fCollisionPad = ref(25)
const fCenter = ref(0.03)

const forceSliders = computed(() => [
  { key: 'charge', label: t('graph.forceCharge'), ref: fCharge, min: -2000, max: -100, step: 50 },
  { key: 'linkDist', label: t('graph.forceLinkDist'), ref: fLinkDist, min: 50, max: 400, step: 10 },
  { key: 'linkStr', label: t('graph.forceLinkStr'), ref: fLinkStrength, min: 0.05, max: 1.0, step: 0.05 },
  { key: 'distMax', label: t('graph.forceDistMax'), ref: fDistMax, min: 200, max: 1500, step: 50 },
  { key: 'colPad', label: t('graph.forceCollision'), ref: fCollisionPad, min: 0, max: 60, step: 5 },
  { key: 'center', label: t('graph.forceCenter'), ref: fCenter, min: 0.01, max: 0.2, step: 0.01 },
])

function applyForce() {
  if (!simulation) return
  simulation.force('charge', d3.forceManyBody().strength(fCharge.value).distanceMax(fDistMax.value))
  const lf = simulation.force('link') as d3.ForceLink<any, any> | undefined
  if (lf) lf.distance(fLinkDist.value).strength(fLinkStrength.value)
  simulation.force('collision', d3.forceCollide().radius((d: any) => nodeRadius(d) + fCollisionPad.value))
  const cf = simulation.force('center') as d3.ForceCenter<any> | undefined
  if (cf) cf.strength(fCenter.value)
  simulation.alpha(0.3).restart()
}

function resetForce() {
  fCharge.value = -800; fLinkDist.value = 200; fLinkStrength.value = 0.35
  fDistMax.value = 700; fCollisionPad.value = 25; fCenter.value = 0.03
  applyForce()
}

// D3 internals (not reactive — updated by D3)
let simulation: d3.Simulation<any, any> | null = null
let zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null
let _d3Links: any[] = []
let _allNodes: any[] = []
let _allLinks: any[] = []
// 범례 갱신용 reactive trigger (D3 데이터는 non-reactive이므로 수동 트리거 필요)
const legendTrigger = ref(0)

const filterOptions = [
  { value: 'all', label: '전체' },
  { value: 'Concept', label: '개념' },
  { value: 'Actor', label: '행위자' },
  { value: 'Event', label: '이벤트' },
  { value: 'Organization', label: '기관' },
]

const legendItems = computed(() => {
  legendTrigger.value  // reactive 의존성 등록
  const typeColors: Record<string, string> = {}
  const typeCounts: Record<string, number> = {}
  _allNodes.forEach(n => {
    if (!typeColors[n.type]) typeColors[n.type] = nodeColor(n.type)
    typeCounts[n.type] = (typeCounts[n.type] || 0) + 1
  })
  return Object.entries(typeColors)
    .map(([type, color]) => ({ type, color, count: typeCounts[type] || 0 }))
    .sort((a, b) => b.count - a.count)
})

const TYPE_COLORS: Record<string, string> = {
  Concept: '#5C6BC0',
  Actor: '#26A69A',
  Event: '#EF5350',
  Organization: '#AB47BC',
  Person: '#FF7043',
  Location: '#42A5F5',
  Technology: '#66BB6A',
  Policy: '#FFA726',
}
const COLOR_POOL = ['#7E57C2', '#29B6F6', '#EC407A', '#8D6E63', '#26C6DA', '#9CCC65']
const COMMUNITY_COLORS = ['#FF5722', '#3498db', '#2ecc71', '#9b59b6', '#f39c12', '#1abc9c', '#e74c3c', '#00bcd4', '#ff9800', '#607d8b', '#8bc34a', '#e91e63']
let colorIdx = 0
function nodeColor(type: string): string {
  if (TYPE_COLORS[type]) return TYPE_COLORS[type]
  if (!TYPE_COLORS[type]) {
    TYPE_COLORS[type] = COLOR_POOL[colorIdx % COLOR_POOL.length]
    colorIdx++
  }
  return TYPE_COLORS[type]
}
function communityColor(communityId: number): string {
  return COMMUNITY_COLORS[communityId % COMMUNITY_COLORS.length]
}
function getNodeColor(d: any): string {
  if (colorMode.value === 'community' && d.community_id !== undefined) {
    return communityColor(d.community_id)
  }
  return nodeColor(d.type)
}
function nodeRadius(d: any): number {
  return 18 + Math.min((d.attributes ? Object.keys(d.attributes).length : 0), 5) * 3
}

// ── D3 setup ──────────────────────────────────────────────────────────────────

function initSVG() {
  if (!svgEl.value || !canvasEl.value) return
  const svg = d3.select(svgEl.value)
  svg.selectAll('*').remove()

  // Dot pattern background
  const defs = svg.append('defs')
  defs.append('pattern')
    .attr('id', 'bg-dots').attr('width', 24).attr('height', 24)
    .attr('patternUnits', 'userSpaceOnUse')
    .append('circle').attr('cx', 1).attr('cy', 1).attr('r', 1).attr('fill', '#EAEAEA')

  // Arrow marker
  defs.append('marker')
    .attr('id', 'arrow').attr('viewBox', '0 -5 10 10')
    .attr('refX', 18).attr('refY', 0)
    .attr('markerWidth', 6).attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#DCDCDC')

  svg.append('rect').attr('width', '100%').attr('height', '100%').attr('fill', 'url(#bg-dots)')

  const g = svg.append('g').attr('class', 'main-group')

  zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.05, 6])
    .on('zoom', (event) => {
      g.attr('transform', event.transform.toString())
      currentZoom.value = Math.round(event.transform.k * 100) / 100
    })

  svg.call(zoomBehavior)
  // Disable double-click zoom
  svg.on('dblclick.zoom', null)
}

function renderGraph(rawNodes: any[], rawEdges: any[]) {
  if (!svgEl.value || !canvasEl.value) return

  const width = canvasEl.value.clientWidth || 800
  const height = canvasEl.value.clientHeight || 600

  const svg = d3.select(svgEl.value)
  const g = svg.select('g.main-group')
  g.selectAll('*').remove()

  if (rawNodes.length === 0) return

  const d3Nodes = rawNodes.map(n => ({ ...n, x: width / 2 + (Math.random() - 0.5) * 200, y: height / 2 + (Math.random() - 0.5) * 200 }))
  const nodeById = new Map(d3Nodes.map(n => [n.id, n]))

  const d3Links = rawEdges
    .filter(e => nodeById.has(e.source_id) && nodeById.has(e.target_id))
    .map(e => ({ ...e, source: e.source_id, target: e.target_id }))

  _d3Links = d3Links

  // ── Simulation ─────────────────────────────────────────────────────────────
  if (simulation) simulation.stop()

  // Set adaptive initial values for sliders
  fCharge.value = Math.max(-1200, -500 - d3Nodes.length * 12)
  fLinkDist.value = d3Nodes.length > 40 ? 160 : 200

  simulation = d3.forceSimulation(d3Nodes)
    .force('link', d3.forceLink(d3Links).id((d: any) => d.id).distance(fLinkDist.value).strength(fLinkStrength.value))
    .force('charge', d3.forceManyBody().strength(fCharge.value).distanceMax(fDistMax.value))
    .force('center', d3.forceCenter(width / 2, height / 2).strength(fCenter.value))
    .force('collision', d3.forceCollide().radius((d: any) => nodeRadius(d) + fCollisionPad.value))
    .alphaDecay(0.025)   // faster settle (default 0.0228)
    .velocityDecay(0.4)  // more friction → stable faster

  // ── Links ───────────────────────────────────────────────────────────────────
  const linkGroup = g.append('g').attr('class', 'links')
  const linkSel = linkGroup.selectAll('g.lnk')
    .data(d3Links).enter().append('g').attr('class', 'lnk')

  const selectedNodeId = selectedNode.value?.id || null
  const isLinkedToSelected = (d: any) => {
    if (!selectedNodeId) return true
    const srcId = typeof d.source === 'object' ? d.source.id : d.source
    const tgtId = typeof d.target === 'object' ? d.target.id : d.target
    return srcId === selectedNodeId || tgtId === selectedNodeId
  }
  const isNodeSelectedOrNeighbor = (d: any) => {
    if (!selectedNodeId) return true
    if (d.id === selectedNodeId) return true
    return d3Links.some((link: any) => {
      const srcId = typeof link.source === 'object' ? link.source.id : link.source
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target
      return (
        (srcId === selectedNodeId && tgtId === d.id) ||
        (tgtId === selectedNodeId && srcId === d.id)
      )
    })
  }

  const lineSel = linkSel.append('line')
    .attr('stroke', (d: any) => isLinkedToSelected(d) ? '#FF5722' : '#DCDCDC')
    .attr('stroke-opacity', (d: any) => selectedNodeId ? (isLinkedToSelected(d) ? 0.9 : 0.08) : 0.45)
    .attr('stroke-width', (d: any) => {
      const base = Math.max(1.4, Number(d.weight || 0.5) * 2.4)
      return selectedNodeId && isLinkedToSelected(d) ? base + 1.2 : base
    })
    .attr('marker-end', 'url(#arrow)')

  const linkLabelSel = linkSel.append('text')
    .text((d: any) => d.relation_type?.replace(/_/g, ' ').toLowerCase() || '')
    .attr('text-anchor', 'middle').attr('font-size', (d: any) => selectedNodeId && isLinkedToSelected(d) ? 10 : 8)
    .attr('fill', (d: any) => selectedNodeId && isLinkedToSelected(d) ? '#C2410C' : '#9E9E9E')
    .attr('fill-opacity', (d: any) => selectedNodeId ? (isLinkedToSelected(d) ? 0.95 : 0) : 0.35)
    .attr('font-family', 'JetBrains Mono, monospace')

  // ── Nodes ───────────────────────────────────────────────────────────────────
  const nodeGroup = g.append('g').attr('class', 'nodes')
  const nodeSel = nodeGroup.selectAll('g.nd')
    .data(d3Nodes).enter().append('g').attr('class', 'nd')
    .style('cursor', 'pointer')
    .call(
      d3.drag<SVGGElement, any>()
        .on('start', (event, d) => {
          if (!event.active) simulation!.alphaTarget(0.3).restart()
          d.fx = d.x; d.fy = d.y
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
        .on('end', (event, d) => {
          if (!event.active) simulation!.alphaTarget(0)
          d.fx = null; d.fy = null
        })
    )
    .on('click', (_event, d: any) => {
      selectedNode.value = selectedNode.value?.id === d.id ? null : d
    })

  // ── Community hulls (drawn before nodes) ─────────────────────────────────
  const hullGroup = g.insert('g', '.nodes').attr('class', 'hulls')

  function updateHulls() {
    hullGroup.selectAll('path.hull').remove()
    if (colorMode.value !== 'community') return
    const communityNodes: Record<number, {x: number, y: number}[]> = {}
    d3Nodes.forEach((n: any) => {
      if (n.community_id === undefined) return
      if (!communityNodes[n.community_id]) communityNodes[n.community_id] = []
      communityNodes[n.community_id].push({ x: n.x, y: n.y })
    })
    for (const [cid, points] of Object.entries(communityNodes)) {
      if (points.length < 3) continue
      const hullPoints = d3.polygonHull(points.map(p => [p.x, p.y] as [number, number]))
      if (!hullPoints) continue
      hullGroup.append('path')
        .attr('class', 'hull')
        .attr('d', `M${hullPoints.map(p => p.join(',')).join('L')}Z`)
        .attr('fill', communityColor(Number(cid)))
        .attr('fill-opacity', 0.08)
        .attr('stroke', communityColor(Number(cid)))
        .attr('stroke-opacity', 0.3)
        .attr('stroke-width', 1.5)
        .attr('rx', 20)
    }
  }

  nodeSel.append('circle')
    .attr('r', (d: any) => nodeRadius(d))
    .attr('fill', (d: any) => getNodeColor(d))
    .attr('stroke', (d: any) => d.id === selectedNodeId ? '#111111' : '#FFFFFF')
    .attr('stroke-width', (d: any) => d.id === selectedNodeId ? 3 : 2)
    .attr('fill-opacity', (d: any) => selectedNodeId ? (isNodeSelectedOrNeighbor(d) ? 1 : 0.18) : 1)
    .attr('filter', 'drop-shadow(0px 2px 4px rgba(0,0,0,0.12))')

  nodeSel.append('text')
    .text((d: any) => d.name.length > 14 ? d.name.slice(0, 13) + '…' : d.name)
    .attr('text-anchor', 'middle')
    .attr('dy', (d: any) => nodeRadius(d) + 14)
    .attr('font-size', 11).attr('fill', '#333333')
    .attr('fill-opacity', (d: any) => selectedNodeId ? (isNodeSelectedOrNeighbor(d) ? 1 : 0.22) : 1)
    .attr('font-family', 'Space Grotesk, sans-serif').attr('font-weight', 500)

  // ── Tick (throttled: skip every other frame for large graphs) ───────────────
  let tickCount = 0
  const skipFrame = d3Nodes.length > 50 ? 2 : 1  // throttle ratio

  simulation.on('tick', () => {
    tickCount++
    if (tickCount % skipFrame !== 0) return

    lineSel
      .attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
      .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)

    linkLabelSel
      .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
      .attr('y', (d: any) => (d.source.y + d.target.y) / 2 - 4)

    nodeSel.attr('transform', (d: any) => `translate(${d.x},${d.y})`)

    // Update community hulls every 5th frame
    if (tickCount % (skipFrame * 5) === 0) updateHulls()
  })

  // Auto-stop after simulation fully cools (saves CPU)
  simulation.on('end', () => {
    // Final render pass after stopping
    lineSel
      .attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
      .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
    linkLabelSel
      .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
      .attr('y', (d: any) => (d.source.y + d.target.y) / 2 - 4)
    nodeSel.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
    updateHulls()
  })

  // Update filter visibility
  applyFilter(filterType.value, nodeSel, linkSel, lineSel)
}

function applyFilter(type: string, nodeSel?: any, linkSel?: any, lineSel?: any) {
  if (!svgEl.value) return
  const svg = d3.select(svgEl.value)
  const ns = nodeSel || svg.selectAll('g.nd')
  const ls = linkSel || svg.selectAll('g.lnk')

  if (type === 'all') {
    ns.style('opacity', 1)
    ls.style('opacity', 1)
    return
  }

  ns.style('opacity', (d: any) => d.type === type ? 1 : 0.15)
  ls.style('opacity', (d: any) => {
    const srcType = (d.source as any)?.type
    const tgtType = (d.target as any)?.type
    return srcType === type || tgtType === type ? 0.8 : 0.05
  })
}

// ── Zoom controls ─────────────────────────────────────────────────────────────

function zoomIn() {
  if (!svgEl.value || !zoomBehavior) return
  d3.select(svgEl.value).transition().duration(250).call(zoomBehavior.scaleBy, 1.3)
}
function zoomOut() {
  if (!svgEl.value || !zoomBehavior) return
  d3.select(svgEl.value).transition().duration(250).call(zoomBehavior.scaleBy, 0.77)
}
function zoomReset() {
  if (!svgEl.value || !zoomBehavior) return
  d3.select(svgEl.value).transition().duration(400).call(zoomBehavior.transform, d3.zoomIdentity.translate(0, 0).scale(1))
}

function setFilter(type: string) {
  filterType.value = type
  applyFilter(type)
}

// ── Clear graph ──────────────────────────────────────────────────────────────

function clearGraph() {
  _allNodes = []
  _allLinks = []
  communities.value = []
  nodeCount.value = 0
  edgeCount.value = 0
  selectedNode.value = null
  selectedCommunity.value = null
  error.value = ''
  ontologyMissing.value = false
  // SVG 내부 요소 제거
  if (svgEl.value) {
    const g = d3.select(svgEl.value).select('g')
    g.selectAll('.links').selectAll('*').remove()
    g.selectAll('.edge-labels').selectAll('*').remove()
    g.selectAll('.nodes').selectAll('*').remove()
    g.selectAll('.labels').selectAll('*').remove()
    g.selectAll('.hulls').selectAll('*').remove()
  }
}

// ── Graph 캐싱 (localStorage) ─────────────────────────────────────────────────

function cacheGraphData(ontologyId: string, data: any) {
  try {
    localStorage.setItem(`graph_${ontologyId}`, JSON.stringify(data))
  } catch { /* quota exceeded 무시 */ }
}

function loadCachedGraphData(ontologyId: string): any | null {
  try {
    const raw = localStorage.getItem(`graph_${ontologyId}`)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function applyGraphData(data: any) {
  _allNodes = data.nodes || []
  _allLinks = data.edges || []
  communities.value = data.communities || []
  nodeCount.value = _allNodes.length
  edgeCount.value = _allLinks.length
  legendTrigger.value++
  if (_allNodes.length > 0) {
    renderGraph(_allNodes, _allLinks)
  }
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadGraphData(ontologyId: string) {
  if (!ontologyId) return
  loading.value = true
  error.value = ''
  try {
    const data = await getGraphData(ontologyId)
    applyGraphData(data)
    cacheGraphData(ontologyId, data)  // 캐시 저장
  } catch (e: any) {
    // API 실패 시 캐시에서 복원
    const cached = loadCachedGraphData(ontologyId)
    if (cached) {
      applyGraphData(cached)
      error.value = ''
    } else {
      error.value = e.message || '로드 실패'
    }
  } finally {
    loading.value = false
  }
}

async function runBuildTask(
  ontologyId: string,
  llm: { provider: string; model: string; api_key: string; base_url?: string },
  silent = false,
) {
  building.value = true
  error.value = ''
  startBuildProgress()

  const runId = ++buildPollRunId
  try {
    const start = await startGraphBuild(ontologyId, llm)
    while (runId === buildPollRunId) {
      const task = await getTask(start.task_id)
      buildProgress.value = task.progress ?? buildProgress.value
      buildStepLabel.value = task.message || buildStepLabel.value

      if (task.status === 'completed') {
        finishBuildProgress()
        await loadGraphData(ontologyId)
        return
      }
      if (task.status === 'failed') {
        throw new Error(task.error || task.message || '그래프 빌드 실패')
      }

      await new Promise(resolve => setTimeout(resolve, 700))
    }
  } catch (e: any) {
    finishBuildProgress()
    if (e.message?.includes('404') || e.message?.includes('not found') || e.message?.toLowerCase().includes('ontology')) {
      ontologyMissing.value = true
    } else if (!silent) {
      error.value = e.message || '그래프 빌드 실패'
    }
  } finally {
    building.value = false
  }
}

async function buildGraph() {
  const ontologyId = docStore.ontologyId
  if (!ontologyId) return
  const agent = llmStore.enabledAgents[0]
  if (!agent?.apiKey) { alert('LLM API 키를 설정해주세요.'); return }

  building.value = true
  error.value = ''
  startBuildProgress()
  try {
    await runBuildTask(ontologyId, {
      provider: agent.provider,
      model: agent.modelName,
      api_key: agent.apiKey,
      base_url: agent.baseUrl,
    })
    return
    finishBuildProgress()
    await loadGraphData(ontologyId)
  } catch (e: any) {
    error.value = e.message || '빌드 실패'
    finishBuildProgress()
  } finally {
    building.value = false
  }
}

// Auto-build: if ontology exists but graph not yet built, trigger build automatically
async function autoBuildIfNeeded(ontologyId: string) {
  if (!ontologyId) return
  ontologyMissing.value = false
  try {
    const data = await getGraphData(ontologyId)
    if (data.nodes?.length > 0) {
      applyGraphData(data)
      cacheGraphData(ontologyId, data)  // 캐시 저장
    } else {
      // Graph not built yet — auto-build silently
      const agent = llmStore.enabledAgents[0]
      if (agent?.apiKey) {
        await runBuildTask(ontologyId, {
          provider: agent.provider,
          model: agent.modelName,
          api_key: agent.apiKey,
          base_url: agent.baseUrl,
        }, true)
        return
        building.value = true
        startBuildProgress()
        try {
          await apiBuildGraph(ontologyId, { provider: agent.provider, model: agent.modelName, api_key: agent.apiKey })
          finishBuildProgress()
          await loadGraphData(ontologyId)
        } catch (e: any) {
          finishBuildProgress()
          // 404 = backend lost ontology after restart → user must re-extract
          if (e.message?.includes('404') || e.message?.includes('not found') || e.message?.toLowerCase().includes('ontology')) {
            ontologyMissing.value = true
          } else {
            error.value = e.message || '빌드 실패'
          }
        } finally {
          building.value = false
        }
      }
    }
  } catch (e: any) {
    // API 실패 시 캐시에서 복원
    const cached = loadCachedGraphData(ontologyId)
    if (cached && cached.nodes?.length > 0) {
      applyGraphData(cached)
    } else {
      error.value = e.message?.includes('fetch') ? '백엔드 연결 실패 — 서버가 실행 중인지 확인하세요' : (e.message || '그래프 로드 실패')
    }
  }
}

function toggleColorMode(mode: 'type' | 'community') {
  colorMode.value = mode
  selectedCommunity.value = null
  // Re-render with new colors
  if (_allNodes.length > 0) renderGraph(_allNodes, _allLinks)
}

function selectCommunity(c: any) {
  selectedCommunity.value = selectedCommunity.value?.id === c.id ? null : c
  selectedNode.value = null
}

async function doSummarize() {
  const ontologyId = docStore.ontologyId
  if (!ontologyId) return
  const agent = llmStore.enabledAgents[0]
  if (!agent?.apiKey) { alert('LLM API 키를 설정해주세요.'); return }

  summarizing.value = true
  try {
    const result = await apiSummarize(ontologyId, {
      provider: agent.provider, model: agent.modelName,
      api_key: agent.apiKey, base_url: agent.baseUrl,
    })
    communities.value = result.communities || []
  } catch (e: any) {
    alert('커뮤니티 요약 실패: ' + (e.message || ''))
  } finally {
    summarizing.value = false
  }
}

function exportJSON() {
  const data = { nodes: _allNodes, edges: _allLinks }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `graph_${docStore.ontologyId?.slice(0, 8) || 'export'}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function getNodeRelations(nodeId: string) {
  return _d3Links
    .filter((l: any) => {
      const srcId = typeof l.source === 'object' ? l.source.id : l.source
      const tgtId = typeof l.target === 'object' ? l.target.id : l.target
      return srcId === nodeId || tgtId === nodeId
    })
    .map((l: any) => {
      const srcId = typeof l.source === 'object' ? l.source.id : l.source
      const isOut = srcId === nodeId
      const peer = isOut
        ? (typeof l.target === 'object' ? l.target : _allNodes.find(n => n.id === l.target))
        : (typeof l.source === 'object' ? l.source : _allNodes.find(n => n.id === l.source))
      return {
        id: l.id,
        direction: isOut ? 'out' : 'in',
        label: l.relation_type?.replace(/_/g, ' ') || '',
        peerName: peer?.name || '—',
      }
    })
}

function getNodeRelationSummary(nodeId: string) {
  const summary = new Map<string, number>()
  for (const relation of getNodeRelations(nodeId)) {
    const label = relation.label || 'related to'
    summary.set(label, (summary.get(label) || 0) + 1)
  }
  return Array.from(summary.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

onMounted(() => {
  initSVG()
  if (docStore.isExtracting) {
    clearGraph()
    loading.value = true
    buildStepLabel.value = '지식 그래프 추출 중...'
  } else if (docStore.ontologyId) {
    autoBuildIfNeeded(docStore.ontologyId)
  }
})

// 추출 상태 변화 감시
watch(() => docStore.isExtracting, (extracting, wasExtracting) => {
  if (extracting) {
    // 추출 시작 → 화면 비우고 로딩 표시
    clearGraph()
    loading.value = true
    buildStepLabel.value = '지식 그래프 추출 중...'
  } else if (wasExtracting && !extracting && docStore.ontologyId) {
    // 추출 완료 → 새 그래프 로드
    loading.value = false
    clearGraph()
    autoBuildIfNeeded(docStore.ontologyId)
  }
}, { immediate: true })

watch(() => docStore.ontologyId, (id, oldId) => {
  // 추출 중이면 무시 (완료 시 위 watcher가 처리)
  if (docStore.isExtracting) return
  if (id && id !== oldId) {
    clearGraph()
    autoBuildIfNeeded(id)
  }
})

watch(selectedNode, () => {
  if (_allNodes.length > 0) renderGraph(_allNodes, _allLinks)
})

onUnmounted(() => {
  simulation?.stop()
  if (progressTimer) clearInterval(progressTimer)
})
</script>

<style scoped>
.ontology-view {
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* ── Graph Panel ────────────────────────────────── */
.graph-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #EAEAEA;
  overflow: hidden;
}

.graph-toolbar {
  height: 48px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px; border-bottom: 1px solid #EAEAEA; background: #FFF;
}
.toolbar-left { display: flex; align-items: center; gap: 10px; }
.toolbar-right { display: flex; align-items: center; gap: 4px; }
.panel-title { font-size: 13px; font-weight: 600; color: #000; }
.node-count { font-size: 10px; color: #AAA; }
.loading-badge { font-size: 10px; color: #FF5722; background: #FFF3F0; padding: 2px 8px; border-radius: 8px; }
.error-badge { font-size: 10px; color: #C62828; background: #FFEBEE; padding: 2px 8px; border-radius: 8px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-select {
  padding: 3px 8px; border: 1px solid #EAEAEA; border-radius: 6px;
  font-size: 11px; background: #FFF; color: #333; outline: none; cursor: pointer;
  max-width: 300px; transition: border-color 0.15s;
}
.version-select:focus { border-color: #FF5722; }
.version-badge {
  padding: 2px 8px; border-radius: 6px; font-size: 10px; font-weight: 700;
  background: rgba(255,87,34,0.1); color: #FF5722;
}

.ctrl-btn {
  padding: 4px 10px; border: 1px solid #EAEAEA; border-radius: 4px;
  background: #FFF; font-size: 12px; color: #444; cursor: pointer;
  font-family: 'Space Grotesk', sans-serif; transition: all 0.15s;
}
.ctrl-btn:hover { border-color: #FF5722; color: #FF5722; }
.ctrl-btn.active-filter { background: #000; color: #FFF; border-color: #000; }
.zoom-label { font-size: 11px; color: #AAA; min-width: 40px; text-align: center; font-family: 'JetBrains Mono', monospace; }
.toolbar-divider { width: 1px; height: 18px; background: #EAEAEA; margin: 0 4px; }

/* ── Canvas ─────────────────────────────────────── */
.graph-canvas {
  flex: 1; position: relative; overflow: hidden; background: #FAFAFA;
}
.graph-svg { width: 100%; height: 100%; }

/* ── Force Panel ─────────────────────────────────── */
.force-panel {
  position: absolute; top: 8px; right: 8px; width: 250px; z-index: 10;
  background: #FFF; border: 1px solid #EAEAEA; border-radius: 12px;
  padding: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.08);
  display: flex; flex-direction: column; gap: 12px;
}
.fp-title { font-size: 12px; font-weight: 700; color: #000; border-bottom: 1px solid #EAEAEA; padding-bottom: 8px; }
.fp-row { display: flex; flex-direction: column; gap: 3px; }
.fp-label { font-size: 11px; color: #555; display: flex; justify-content: space-between; }
.fp-val { font-size: 10px; color: #FF5722; }
.fp-slider {
  -webkit-appearance: none; width: 100%; height: 4px; border-radius: 2px;
  background: #EAEAEA; outline: none; cursor: pointer;
}
.fp-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%;
  background: #FF5722; cursor: pointer; border: 2px solid #FFF; box-shadow: 0 1px 4px rgba(0,0,0,0.2);
}
.fp-reset {
  padding: 6px; border: 1px solid #EAEAEA; border-radius: 6px; background: #FAFAFA;
  font-size: 11px; color: #888; cursor: pointer; transition: all 0.15s;
  font-family: 'Space Grotesk', sans-serif;
}
.fp-reset:hover { border-color: #FF5722; color: #FF5722; }
.slide-enter-active, .slide-leave-active { transition: opacity 0.2s, transform 0.2s; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-8px); }

.canvas-overlay, .canvas-empty {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
}
.overlay-spinner {
  width: 32px; height: 32px; border-radius: 50%;
  border: 3px solid #F0F0F0; border-top-color: #FF5722;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.overlay-text { font-size: 13px; color: #888; }
.overlay-progress { font-size: 18px; font-weight: 700; color: #FF5722; margin-top: 4px; }
.empty-icon { font-size: 40px; color: #E0E0E0; }
.empty-title { font-size: 16px; font-weight: 600; color: #333; }
.empty-desc { font-size: 13px; color: #999; text-align: center; line-height: 1.7; }

/* ── Legend ─────────────────────────────────────── */
.graph-legend {
  height: 36px; flex-shrink: 0;
  display: flex; align-items: center; gap: 16px; padding: 0 16px;
  border-top: 1px solid #EAEAEA; background: #FFF; overflow-x: auto;
}
.legend-label { font-size: 10px; color: #AAA; text-transform: uppercase; letter-spacing: 0.5px; flex-shrink: 0; }
.legend-hint {
  font-size: 10.5px; color: #888; font-style: italic;
  padding: 2px 8px; border-left: 2px solid #EAEAEA;
  white-space: nowrap; flex-shrink: 0;
}
.legend-item { display: flex; align-items: center; gap: 5px; flex-shrink: 0; }
.legend-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.legend-text { font-size: 11px; color: #555; }
.legend-count { font-size: 9px; color: #BBB; }
.legend-clickable { cursor: pointer; padding: 2px 6px; border-radius: 4px; transition: background 0.15s; }
.legend-clickable:hover { background: #F5F5F5; }
.legend-active { background: #F0F0F0; font-weight: 600; }

/* ── Detail Panel ───────────────────────────────── */
.detail-panel {
  width: 300px; flex-shrink: 0;
  display: flex; flex-direction: column; background: #FFF; overflow: hidden;
}
.detail-header {
  height: 48px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px; border-bottom: 1px solid #EAEAEA;
}
.detail-title { font-size: 13px; font-weight: 600; color: #000; }
.detail-close { background: none; border: none; font-size: 12px; color: #CCC; cursor: pointer; transition: color 0.15s; }
.detail-close:hover { color: #F44336; }

.detail-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
}
.detail-empty-icon { font-size: 32px; color: #DDD; }
.detail-empty-text { font-size: 12px; color: #BBB; text-align: center; line-height: 1.6; }

.detail-content { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; }
.detail-section { display: flex; flex-direction: column; gap: 7px; }
.detail-node-name { font-size: 17px; font-weight: 700; color: #000; line-height: 1.3; }
.detail-node-type-badge {
  display: inline-block; padding: 3px 10px; border-radius: 12px;
  font-size: 11px; font-weight: 600; font-family: 'JetBrains Mono', monospace; width: fit-content;
}
.detail-section-title {
  font-size: 10px; font-weight: 600; color: #AAA; text-transform: uppercase; letter-spacing: 0.5px;
  padding-bottom: 5px; border-bottom: 1px solid #F0F0F0;
}
.detail-desc { font-size: 12px; color: #555; line-height: 1.6; }

.prop-list { display: flex; flex-direction: column; gap: 5px; }
.prop-item { display: flex; gap: 8px; font-size: 12px; }
.prop-key { color: #999; min-width: 72px; flex-shrink: 0; }
.prop-val { color: #333; }

.relation-list { display: flex; flex-direction: column; gap: 5px; }
.relation-summary-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.relation-summary-item {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 8px; border-radius: 999px;
  background: #FFF4EE; color: #C2410C;
}
.relation-summary-label { font-size: 10px; }
.relation-summary-count {
  min-width: 18px; height: 18px; border-radius: 999px;
  display: inline-flex; align-items: center; justify-content: center;
  background: #FF5722; color: #FFF; font-size: 10px; font-weight: 700;
}
.relation-item { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.rel-direction { color: #FF5722; font-weight: 700; flex-shrink: 0; }
.rel-label { color: #999; font-size: 10px; max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rel-target { color: #333; font-weight: 500; }
.no-relations { font-size: 12px; color: #CCC; }

.detail-actions {
  padding: 14px 16px; border-top: 1px solid #EAEAEA;
  display: flex; flex-direction: column; gap: 8px; flex-shrink: 0;
}
.btn-build {
  padding: 10px 16px; background: #000; color: #FFF; border: none; border-radius: 6px;
  font-size: 13px; font-weight: 600; font-family: 'Space Grotesk', sans-serif;
  cursor: pointer; transition: all 0.15s;
}
.btn-build:hover:not(:disabled) { background: #FF5722; transform: translateY(-2px); }
.btn-build:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-export {
  padding: 8px 16px; background: transparent; color: #555; border: 1px solid #EAEAEA; border-radius: 6px;
  font-size: 12px; font-family: 'Space Grotesk', sans-serif; cursor: pointer; transition: all 0.15s;
}
.btn-export:hover:not(:disabled) { border-color: #000; color: #000; }
.btn-export:disabled { opacity: 0.4; cursor: not-allowed; }

.build-progress {
  height: 4px; background: #F0F0F0; border-radius: 2px; overflow: hidden;
}
.build-progress-bar {
  height: 100%; background: #FF5722; border-radius: 2px;
  transition: width 0.5s ease;
}
.build-progress-label {
  font-size: 10px; color: #FF5722; text-align: right;
}

.mono { font-family: 'JetBrains Mono', monospace; }
</style>

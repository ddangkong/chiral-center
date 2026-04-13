<template>
  <div class="home-view">

    <!-- Hero Section -->
    <section class="hero">
      <div class="hero-left">
        <div class="hero-eyebrow">
          <span class="eyebrow-dot"></span>
          <span class="eyebrow-text mono">v0.1.0 — Research Platform</span>
        </div>
        <h1 class="hero-title">
          Chiral Center<br />
          <span class="title-accent">The center between real and simulated communities.</span>
        </h1>
        <p class="hero-desc" v-html="t('home.heroDesc').replace('\n', '<br/>')"></p>
        <div class="hero-tags">
          <span class="tag">{{ t('home.tag.docAnalysis') }}</span>
          <span class="tag">{{ t('home.tag.ontology') }}</span>
          <span class="tag">{{ t('home.tag.agentSim') }}</span>
          <span class="tag">{{ t('home.tag.reportGen') }}</span>
        </div>
        <div class="hero-actions">
          <RouterLink to="/research" class="btn-primary">{{ t('home.startResearch') }}</RouterLink>
          <RouterLink to="/ontology" class="btn-secondary">{{ t('home.viewGraph') }}</RouterLink>
        </div>
      </div>
      <div class="hero-right">
        <div class="hero-icon-wrap">
          <img src="/icon.png" class="hero-icon" alt="Chiral Center" />
        </div>
        <div class="hero-stats">
          <div class="stat-item">
            <span class="stat-num mono">5</span>
            <span class="stat-label">{{ t('home.pipeline') }}</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num mono">2</span>
            <span class="stat-label">{{ t('home.providers') }}</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num mono">∞</span>
            <span class="stat-label">{{ t('home.rounds') }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Recent Projects -->
    <section class="projects-section">
      <div class="section-header">
        <h2 class="section-title">{{ t('home.projects') }}</h2>
        <RouterLink to="/upload" class="btn-ghost">{{ t('home.newProject') }}</RouterLink>
      </div>

      <div v-if="projectStore.projects.length === 0" class="empty-state">
        <div class="empty-icon">◈</div>
        <div class="empty-title">{{ t('home.noProjects') }}</div>
        <div class="empty-desc">{{ t('home.emptyDesc') }}</div>
        <RouterLink to="/upload" class="btn-primary">{{ t('home.uploadDocs') }}</RouterLink>
      </div>

      <div v-else class="project-grid">
        <div v-for="p in projectStore.projects" :key="p.id"
          class="project-card"
          :class="{ current: p.id === projectStore.currentProjectId }"
          @click="projectStore.setCurrentProject(p.id)">
          <div class="pc-header">
            <div class="pc-icon">◈</div>
            <div class="pc-meta mono">{{ projectStore.fmtDate(p.updatedAt) }}</div>
            <div v-if="p.id === projectStore.currentProjectId" class="pc-current-badge">현재</div>
            <button class="pc-delete" @click.stop="confirmDelete(p.id, p.name)" title="프로젝트 삭제">✕</button>
          </div>
          <div class="pc-name">{{ p.name }}</div>
          <div class="pc-docs mono">{{ p.documents.map(d => d.name).join(', ') }}</div>
          <div class="pc-stages">
            <div class="pc-stage" :class="{ done: p.documents.length > 0 }">
              <span class="stage-dot"></span>
              <span class="stage-label">문서 {{ p.documents.length }}개</span>
            </div>
            <span class="stage-arrow">→</span>
            <div class="pc-stage" :class="{ done: p.ontologies.length > 0 }">
              <span class="stage-dot"></span>
              <span class="stage-label">온톨로지 {{ p.ontologies.length }}개</span>
            </div>
            <span class="stage-arrow">→</span>
            <div class="pc-stage" :class="{ done: p.simulations.length > 0 }">
              <span class="stage-dot"></span>
              <span class="stage-label">시뮬 {{ p.simulations.length }}개</span>
            </div>
            <span class="stage-arrow">→</span>
            <div class="pc-stage" :class="{ done: p.reports.length > 0 }">
              <span class="stage-dot"></span>
              <span class="stage-label">보고서 {{ p.reports.length }}개</span>
            </div>
          </div>
          <RouterLink
            :to="nextStep(p)"
            class="pc-cta"
            @click.stop="projectStore.setCurrentProject(p.id)">
            {{ nextStepLabel(p) }} →
          </RouterLink>
        </div>
      </div>
    </section>

    <!-- Delete Confirm Modal -->
    <div v-if="deleteTarget" class="modal-backdrop" @click.self="deleteTarget = null">
      <div class="modal">
        <div class="modal-title">프로젝트 삭제</div>
        <div class="modal-body">
          <strong>{{ deleteTarget.name }}</strong> 프로젝트를 삭제하시겠습니까?<br/>
          문서, 온톨로지, 시뮬레이션, 보고서 데이터가 모두 삭제됩니다.
        </div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="deleteTarget = null">{{ t('common.cancel') }}</button>
          <button class="btn-confirm-delete" @click="doDelete">{{ t('common.delete') }}</button>
        </div>
      </div>
    </div>

    <!-- Pipeline Steps -->
    <section class="pipeline-section">
      <div class="section-header">
        <h2 class="section-title">{{ t('home.pipeline') }}</h2>
        <span class="section-subtitle mono">{{ t('home.pipelineFlow') }}</span>
      </div>
      <div class="pipeline-scroll">
        <div class="pipeline-track">
          <div v-for="(step, idx) in pipelineSteps" :key="step.id" class="pipeline-card">
            <div class="card-number mono">{{ String(step.id).padStart(2, '0') }}</div>
            <div class="card-icon">{{ step.icon }}</div>
            <div class="card-body">
              <div class="card-title">{{ step.title }}</div>
              <div class="card-desc">{{ step.desc }}</div>
            </div>
            <div class="card-status" :class="step.status">{{ step.statusLabel }}</div>
            <div v-if="idx < pipelineSteps.length - 1" class="card-arrow">→</div>
          </div>
        </div>
      </div>
    </section>


  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useProjectStore } from '../stores/project'
import type { Project } from '../stores/project'
import { useI18n } from '../composables/useI18n'

const projectStore = useProjectStore()
const { t } = useI18n()

const deleteTarget = ref<{ id: string; name: string } | null>(null)

function confirmDelete(id: string, name: string) {
  deleteTarget.value = { id, name }
}

function doDelete() {
  if (deleteTarget.value) {
    projectStore.deleteProject(deleteTarget.value.id)
    deleteTarget.value = null
  }
}

function nextStep(p: Project): string {
  if (p.ontologies.length === 0) return '/upload'
  if (p.simulations.length === 0) return '/simulation'
  if (p.reports.length === 0) return '/report'
  return '/report'
}
function nextStepLabel(p: Project): string {
  if (p.ontologies.length === 0) return '온톨로지 추출'
  if (p.simulations.length === 0) return '시뮬레이션 실행'
  if (p.reports.length === 0) return '보고서 생성'
  return '보고서 보기'
}

const pipelineSteps = computed(() => [
  { id: 1, icon: '📄', title: t('home.step.docs'),    desc: t('home.step.docs.desc'),    status: 'done',    statusLabel: t('status.done') },
  { id: 2, icon: '⬡',  title: t('home.step.graph'),   desc: t('home.step.graph.desc'),   status: 'active',  statusLabel: t('status.active') },
  { id: 3, icon: '👤', title: t('home.step.persona'), desc: t('home.step.persona.desc'), status: 'pending', statusLabel: t('status.pending') },
  { id: 4, icon: '⚡',  title: t('home.step.sim'),     desc: t('home.step.sim.desc'),     status: 'pending', statusLabel: t('status.pending') },
  { id: 5, icon: '📊', title: t('home.step.report'),  desc: t('home.step.report.desc'),  status: 'pending', statusLabel: t('status.pending') },
])
</script>

<style scoped>
.home-view { padding: 0; }

/* Hero */
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 64px 56px;
  border-bottom: 1px solid #EAEAEA;
  min-height: 380px;
  background: linear-gradient(135deg, #FFFFFF 0%, #FAFAFA 100%);
}
.hero-left { max-width: 540px; }
.hero-eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
}
.eyebrow-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #FF5722;
}
.eyebrow-text {
  font-size: 11px;
  color: #999;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.hero-title {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 38px;
  font-weight: 700;
  line-height: 1.2;
  color: #000;
  margin-bottom: 16px;
}
.title-accent { color: #FF5722; }
.hero-desc {
  font-size: 15px;
  color: #555;
  line-height: 1.7;
  margin-bottom: 24px;
}
.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 32px;
}
.tag {
  padding: 4px 12px;
  border: 1px solid #EAEAEA;
  border-radius: 20px;
  font-size: 12px;
  color: #555;
  background: #FAFAFA;
}
.hero-actions { display: flex; gap: 12px; align-items: center; }
.btn-primary {
  padding: 10px 24px;
  background: #000;
  color: #FFF;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  font-family: 'Space Grotesk', sans-serif;
  text-decoration: none;
  display: inline-block;
  transition: all 0.15s ease;
}
.btn-primary:hover {
  background: #FF5722;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255,87,34,0.3);
}
.btn-secondary {
  padding: 10px 24px;
  background: transparent;
  color: #000;
  border: 1px solid #EAEAEA;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  font-family: 'Space Grotesk', sans-serif;
  text-decoration: none;
  display: inline-block;
  transition: all 0.15s ease;
}
.btn-secondary:hover {
  border-color: #FF5722;
  color: #FF5722;
  transform: translateY(-2px);
}

/* Hero Right */
.hero-right { display: flex; flex-direction: column; align-items: center; gap: 32px; }
.hero-icon-wrap {
  display: flex; align-items: center; justify-content: center;
  transition: transform 0.3s ease;
}
.hero-icon-wrap:hover {
  transform: translateY(-6px);
}
.hero-icon {
  width: 220px;
  height: 220px;
  display: block;
  object-fit: contain;
}
.hero-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 24px;
  border: 1px solid #EAEAEA;
  border-radius: 10px;
  background: #FAFAFA;
}
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.stat-num { font-size: 22px; font-weight: 700; color: #000; }
.stat-label { font-size: 10px; color: #999; white-space: nowrap; }
.stat-divider { width: 1px; height: 32px; background: #EAEAEA; }

/* Overview */
.overview-section { padding: 48px 56px; border-bottom: 1px solid #EAEAEA; }
.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}
.overview-card {
  display: flex;
  gap: 16px;
  padding: 20px;
  border: 1px solid #EAEAEA;
  border-radius: 10px;
  background: #FAFAFA;
  transition: all 0.15s;
}
.overview-card:hover {
  border-color: rgba(255,87,34,0.2);
  background: #FFF;
  box-shadow: 0 4px 16px rgba(255,87,34,0.06);
}
.overview-icon { font-size: 28px; line-height: 1; flex-shrink: 0; margin-top: 2px; }
.overview-body { display: flex; flex-direction: column; gap: 6px; }
.overview-title { font-family: 'Space Grotesk', sans-serif; font-size: 14px; font-weight: 700; color: #000; }
.overview-desc { font-size: 12px; color: #666; line-height: 1.65; }

.how-to {
  padding: 20px 24px;
  background: #F7F7F7;
  border: 1px solid #EAEAEA;
  border-radius: 10px;
}
.how-to-title {
  font-size: 10px; font-weight: 700; color: #999;
  letter-spacing: 1px; text-transform: uppercase;
  margin-bottom: 14px;
}
.how-to-steps {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
}
.how-step {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 140px;
}
.how-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px; font-weight: 700; color: #FF5722;
  letter-spacing: 1px;
}
.how-text {
  font-size: 12px; color: #555; line-height: 1.55;
}
.how-text strong { color: #000; font-weight: 600; }
.how-text em { font-style: normal; color: #FF5722; font-weight: 500; }
.how-arrow {
  color: #DDD; font-size: 18px; padding-top: 12px; flex-shrink: 0;
}

/* Pipeline */
.pipeline-section { padding: 48px 56px; border-bottom: 1px solid #EAEAEA; }
.section-header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 28px; }
.section-title { font-size: 20px; font-weight: 700; color: #000; }
.section-subtitle { font-size: 11px; color: #AAA; letter-spacing: 0.5px; }
.pipeline-scroll { overflow-x: auto; padding: 4px 0 8px; }
.pipeline-track { display: flex; align-items: stretch; min-width: max-content; }
.pipeline-card {
  position: relative;
  display: flex; flex-direction: column; gap: 8px;
  padding: 20px;
  border: 1px solid #EAEAEA; border-radius: 10px;
  background: #FFF; width: 180px; margin-right: 32px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  transition: all 0.15s ease;
}
.pipeline-card:hover {
  border-color: rgba(255,87,34,0.25);
  box-shadow: 0 4px 16px rgba(255,87,34,0.08);
  transform: translateY(-2px);
}
.pipeline-card:last-child { margin-right: 0; }
.card-number { font-size: 10px; color: #CCC; letter-spacing: 1px; }
.card-icon { font-size: 24px; line-height: 1; }
.card-title { font-weight: 600; font-size: 13px; color: #000; margin-bottom: 4px; }
.card-desc { font-size: 11px; color: #888; line-height: 1.5; }
.card-status {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 500; font-family: 'JetBrains Mono', monospace; width: fit-content;
}
.card-status.done    { background: #E8F5E9; color: #2E7D32; }
.card-status.active  { background: #FFF3E0; color: #E65100; }
.card-status.pending { background: #F5F5F5; color: #999; }
.card-arrow {
  position: absolute; right: -24px; top: 50%;
  transform: translateY(-50%); font-size: 16px; color: #CCC; z-index: 1;
}

/* Projects */
.projects-section { padding: 48px 56px; border-bottom: 1px solid #EAEAEA; }
.btn-ghost {
  background: none; border: none; font-size: 12px; color: #999;
  cursor: pointer; font-family: 'Space Grotesk', sans-serif; transition: color 0.15s;
  text-decoration: none;
}
.btn-ghost:hover { color: #FF5722; }
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 64px 32px;
  border: 1px dashed #EAEAEA; border-radius: 12px; gap: 12px; background: #FAFAFA;
}
.empty-icon { font-size: 40px; color: #E0E0E0; margin-bottom: 8px; }
.empty-title { font-size: 16px; font-weight: 600; color: #333; }
.empty-desc { font-size: 13px; color: #999; text-align: center; line-height: 1.6; margin-bottom: 8px; }

.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.project-card {
  border: 1px solid #EAEAEA; border-radius: 12px; padding: 20px;
  background: #FFF; cursor: pointer; transition: all 0.15s;
  display: flex; flex-direction: column; gap: 8px;
}
.project-card:hover { border-color: rgba(255,87,34,0.25); box-shadow: 0 4px 16px rgba(255,87,34,0.08); transform: translateY(-2px); }
.project-card.current { border-color: rgba(255,87,34,0.4); background: #FFFAF8; }
.pc-header { display: flex; align-items: center; gap: 6px; }
.pc-icon { font-size: 14px; color: #FF5722; }
.pc-meta { font-size: 10px; color: #BBB; flex: 1; }
.pc-current-badge { font-size: 9px; font-weight: 700; color: #FF5722; background: #FFF3F0; padding: 1px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; }
.pc-name { font-size: 15px; font-weight: 700; color: #000; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pc-docs { font-size: 10px; color: #AAA; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
.pc-stages { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.pc-stage { display: flex; align-items: center; gap: 4px; }
.stage-dot { width: 6px; height: 6px; border-radius: 50%; background: #E0E0E0; flex-shrink: 0; transition: background 0.15s; }
.pc-stage.done .stage-dot { background: #FF5722; }
.stage-label { font-size: 10px; color: #AAA; font-family: 'JetBrains Mono', monospace; }
.pc-stage.done .stage-label { color: #555; }
.stage-arrow { font-size: 10px; color: #DDD; }
.pc-cta {
  display: inline-block; margin-top: 4px; padding: 6px 12px;
  background: #000; color: #FFF; border-radius: 6px;
  font-size: 12px; font-weight: 600; text-decoration: none;
  font-family: 'Space Grotesk', sans-serif; transition: all 0.15s;
  align-self: flex-start;
}
.pc-cta:hover { background: #FF5722; }

/* Project delete button */
.pc-delete {
  margin-left: auto;
  background: none; border: none; cursor: pointer;
  font-size: 12px; color: #CCC; padding: 2px 4px;
  border-radius: 4px; line-height: 1; transition: all 0.15s;
  flex-shrink: 0;
}
.pc-delete:hover { color: #EF4444; background: #FEF2F2; }

/* Delete confirm modal */
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal {
  background: #FFF; border-radius: 12px;
  padding: 28px 32px; width: 360px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  display: flex; flex-direction: column; gap: 16px;
}
.modal-title { font-size: 16px; font-weight: 700; color: #000; }
.modal-body { font-size: 13px; color: #555; line-height: 1.7; }
.modal-body strong { color: #000; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
.btn-cancel {
  padding: 8px 16px; background: #F5F5F5; border: none;
  border-radius: 6px; font-size: 13px; cursor: pointer;
  font-family: 'Space Grotesk', sans-serif; transition: background 0.15s;
}
.btn-cancel:hover { background: #EAEAEA; }
.btn-confirm-delete {
  padding: 8px 16px; background: #EF4444; color: #FFF; border: none;
  border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer;
  font-family: 'Space Grotesk', sans-serif; transition: background 0.15s;
}
.btn-confirm-delete:hover { background: #DC2626; }

.mono { font-family: 'JetBrains Mono', monospace; }
</style>

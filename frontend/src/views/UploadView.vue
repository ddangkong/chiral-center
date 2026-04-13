<template>
  <div class="upload-view">

    <!-- Left: Project + Files + Ontology History -->
    <div class="left-panel">

      <!-- Project Header -->
      <div class="project-header">
        <div class="project-selector">
          <div class="project-icon">◈</div>
          <div class="project-info" v-if="projectStore.currentProject">
            <div class="project-name">{{ projectStore.currentProject.name }}</div>
            <div class="project-meta mono">
              문서 {{ projectStore.currentProject.documents.length }}개 ·
              지식그래프 {{ projectStore.currentProject.ontologies.length }}개 버전
            </div>
          </div>
          <div class="project-info" v-else>
            <div class="project-name no-project">{{ t('upload.noProject') }}</div>
            <div class="project-meta">{{ t('upload.dropHint') }}</div>
          </div>
        </div>
        <div class="project-actions">
          <select v-if="projectStore.projects.length > 1" class="project-select" @change="onProjectSwitch">
            <option v-for="p in projectStore.projects" :key="p.id" :value="p.id"
              :selected="p.id === projectStore.currentProjectId">
              {{ p.name }}
            </option>
          </select>
          <button class="btn-new-project" @click="projectStore.startNewProject()">{{ t('upload.newProject') }}</button>
        </div>
      </div>

      <!-- Documents + Ontology Versions linked view -->
      <div class="project-body" v-if="projectStore.currentProject">

        <div class="doc-section-top">
          <div class="doc-section-label mono">{{ t('upload.docs') }}</div>
        </div>
        <div class="doc-list">
          <div v-for="doc in projectStore.currentProject.documents" :key="doc.id" class="doc-row">
            <div class="doc-type-badge" :style="{ background: fileColor(doc.ext) }">{{ doc.ext.toUpperCase() }}</div>
            <div class="doc-info">
              <div class="doc-name">{{ doc.name }}</div>
              <div class="doc-meta mono">{{ doc.size }} · {{ doc.pages }}p · {{ doc.chunks }}청크</div>
            </div>
            <div class="doc-status-done">{{ t('status.done') }}</div>
            <button class="doc-remove" @click="projectStore.removeDocument(doc.id)" title="문서 삭제">✕</button>
          </div>
        </div>

        <!-- Ontology version history linked to documents -->
        <div class="onto-section">
          <div class="onto-section-header">
            <div class="onto-connector-line"></div>
            <span class="onto-section-label mono">{{ t('upload.extractHistory') }}</span>
            <span class="onto-version-count mono">{{ projectStore.currentProject.ontologies.length }}개 버전</span>
          </div>
          <div v-if="projectStore.currentProject.ontologies.length === 0" class="onto-empty">
            {{ t('upload.noHistory') }}
          </div>
          <div v-else class="onto-list">
            <div
              v-for="o in [...projectStore.currentProject.ontologies].reverse()"
              :key="o.id"
              class="onto-row"
              :class="{ active: o.id === projectStore.currentProject.activeOntologyId }"
            >
              <div class="onto-version mono">v{{ o.version }}</div>
              <div class="onto-main">
                <div class="onto-model mono">{{ o.provider }} / {{ o.model }}</div>
                <div class="onto-stats mono">{{ o.nodeCount }}n · {{ o.edgeCount }}e · {{ projectStore.fmtDate(o.createdAt) }}</div>
                <div class="onto-topic" v-if="o.topic">{{ o.topic }}</div>
              </div>
              <div class="onto-row-actions">
                <span v-if="o.id === projectStore.currentProject.activeOntologyId" class="onto-active-badge">● 활성</span>
                <button v-else class="btn-set-active" @click="projectStore.setActiveOntology(o.id)">{{ t('upload.setActive') }}</button>
                <RouterLink to="/ontology" class="btn-goto-graph" @click="projectStore.setActiveOntology(o.id)">그래프→</RouterLink>
                <button class="btn-delete-onto" @click="confirmDeleteOntology(o.id, o.version)">✕</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Import from research -->
        <div class="drop-zone-inline research-import" @click="showResearchModal = true">
          <span class="drop-inline-icon">🔬</span>
          <span class="drop-inline-text">{{ t('upload.importResearch') }}</span>
        </div>
        <!-- Add file inline -->
        <div class="drop-zone-inline" :class="{ 'drag-over': isDragging }"
          @dragover.prevent="isDragging = true" @dragleave.prevent="isDragging = false"
          @drop.prevent="handleDrop" @click="triggerFileInput">
          <input ref="fileInput" type="file" multiple accept=".pdf,.docx,.txt,.md" class="hidden-input" @change="handleFileSelect" />
          <span class="drop-inline-icon">+</span>
          <span class="drop-inline-text">{{ t('upload.addFiles') }}</span>
        </div>
      </div>

      <!-- No project: main drop zone -->
      <div v-else class="no-project-state">
        <div class="drop-zone-main" :class="{ 'drag-over': isDragging }"
          @dragover.prevent="isDragging = true" @dragleave.prevent="isDragging = false"
          @drop.prevent="handleDrop" @click="triggerFileInput">
          <input ref="fileInput" type="file" multiple accept=".pdf,.docx,.txt,.md" class="hidden-input" @change="handleFileSelect" />
          <div class="drop-icon">↑</div>
          <div class="drop-title">{{ t('upload.dropTitle') }}</div>
          <div class="drop-desc">{{ t('upload.dropDesc') }}</div>
          <div class="drop-extensions">
            <span class="ext-badge">.pdf</span><span class="ext-badge">.docx</span>
            <span class="ext-badge">.txt</span><span class="ext-badge">.md</span>
          </div>
        </div>
        <button class="btn-research-large" @click="showResearchModal = true">🔬 {{ t('upload.importResearch') }}</button>
        <div v-if="projectStore.projects.length > 0" class="prev-projects">
          <div class="prev-label mono">{{ t('upload.prevProjects') }}</div>
          <div v-for="p in projectStore.projects" :key="p.id" class="prev-project-row"
            @click="projectStore.setCurrentProject(p.id)">
            <div class="prev-proj-name">{{ p.name }}</div>
            <div class="prev-proj-meta mono">지식그래프 {{ p.ontologies.length }}개 · 시뮬 {{ p.simulations.length }}개 · {{ projectStore.fmtDate(p.updatedAt) }}</div>
          </div>
        </div>
      </div>

      <!-- Upload log -->
      <div class="progress-log" v-if="logs.length > 0">
        <div class="log-header">
          <span class="log-title mono">Upload Log</span>
          <span class="log-status" :class="{ running: isExtracting }">● {{ isExtracting ? 'RUNNING' : 'DONE' }}</span>
        </div>
        <div class="log-body" ref="logBodyEl">
          <div v-for="(entry, idx) in logs" :key="idx" class="log-line">
            <span class="log-time mono">{{ entry.time }}</span>
            <span class="log-level" :class="entry.level">{{ entry.level.toUpperCase() }}</span>
            <span class="log-msg">{{ entry.msg }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: Extraction Settings -->
    <div class="right-panel">
      <div class="settings-card">
        <div class="settings-title">{{ t('upload.settings') }}</div>

        <div v-if="!projectStore.canRunOntology" class="warn-box">
          {{ t('upload.warnNoDoc') }}
        </div>

        <div class="form-group">
          <label class="form-label">{{ t('upload.topic') }}</label>
          <textarea v-model="topic" class="form-textarea" rows="3"
            :placeholder="t('upload.topicPlaceholder')" />
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('upload.purpose') }}</label>
          <textarea v-model="purpose" class="form-textarea" rows="3"
            :placeholder="t('upload.purposePlaceholder')" />
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('upload.model') }}</label>
          <div v-if="llmStore.enabledAgents.length === 0" class="no-model-msg">
            상단 <strong>LLM Model</strong> 버튼에서 먼저 설정해주세요.
          </div>
          <select v-else v-model="selectedAgentId" class="model-select">
            <option v-for="agent in llmStore.enabledAgents" :key="agent.id" :value="agent.id">
              {{ agent.provider }} / {{ agent.modelName || '(모델 미지정)' }}
            </option>
            <option v-if="llmStore.multiAgentMode && llmStore.enabledAgents.length > 1" value="__random__">Multi-Agent (가중치 랜덤)</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('upload.options') }}</label>
          <div class="option-rows">
            <label class="option-row"><input type="checkbox" v-model="opts.entities" /> {{ t('upload.entity') }}</label>
            <label class="option-row"><input type="checkbox" v-model="opts.relations" /> {{ t('upload.relation') }}</label>
          </div>
        </div>

        <button v-if="!isExtracting" class="btn-start"
          :disabled="!projectStore.canRunOntology || !selectedAgent"
          @click="startExtraction">
          {{ extractionDone ? t('upload.restart') : t('upload.start') }}
        </button>
        <button v-else class="btn-start btn-stop" @click="docStore.cancelExtraction()">
          {{ t('upload.stop') }}
        </button>

        <div class="extraction-progress" v-if="isExtracting">
          <div class="progress-spinner"></div>
          <div class="progress-info">
            <div class="progress-step">{{ docStore.currentStep || 'LLM 처리 중...' }}</div>
            <div class="progress-bar-wrap">
              <div class="progress-bar-fill" :style="{ width: `${extractionProgress}%` }"></div>
            </div>
            <div class="progress-elapsed mono">진행률: {{ extractionProgress }}% · 경과: {{ elapsed }}s</div>
          </div>
        </div>
      </div>
    </div>

    <!-- DB Setup Modal -->
    <DBSetupModal
      :visible="showDbModal"
      :project-id="projectStore.currentProjectId ?? ''"
      @skip="onDbSkip"
      @confirm="onDbConfirm"
    />

    <!-- Research Import Modal -->
    <ResearchImportModal
      :visible="showResearchModal"
      @close="showResearchModal = false"
      @imported="onResearchImported"
    />

    <!-- Delete confirm modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div class="modal-overlay" v-if="deleteTarget" @click.self="deleteTarget = null">
          <div class="confirm-modal">
            <div class="confirm-title">지식 그래프 v{{ deleteTarget.version }} 삭제</div>
            <div class="confirm-desc">이 버전을 기반으로 한 <strong>시뮬레이션과 보고서도 함께 삭제</strong>됩니다. 계속하시겠습니까?</div>
            <div class="confirm-actions">
              <button class="btn-cancel" @click="deleteTarget = null">취소</button>
              <button class="btn-confirm-delete" @click="doDeleteOntology">삭제</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useLLMStore } from '../stores/llm'
import { useDocumentStore } from '../stores/document'
import { useProjectStore } from '../stores/project'
import { useI18n } from '../composables/useI18n'
import DBSetupModal from '../components/DBSetupModal.vue'
import ResearchImportModal from '../components/ResearchImportModal.vue'

const router = useRouter()

const llmStore = useLLMStore()
const docStore = useDocumentStore()
const projectStore = useProjectStore()
const { t } = useI18n()

const showDbModal = ref(false)
const showResearchModal = ref(false)

const isDragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const logBodyEl = ref<HTMLElement | null>(null)
const topic = ref('')
const purpose = ref('')
const extractionMethod = ref<'hybrid' | 'llm'>('llm')

const logs = computed(() => docStore.logs)
const isExtracting = computed(() => docStore.isExtracting)
const extractionDone = computed(() => docStore.extractionDone)
const extractionProgress = computed(() => docStore.extractionProgress)

function scrollLogToBottom() {
  nextTick(() => {
    if (logBodyEl.value) logBodyEl.value.scrollTop = logBodyEl.value.scrollHeight
  })
}

onMounted(() => scrollLogToBottom())
watch(() => logs.value.length, () => scrollLogToBottom())

const selectedAgentId = ref(llmStore.enabledAgents.length > 0 ? llmStore.enabledAgents[0].id : '')
const selectedAgent = computed(() =>
  selectedAgentId.value === '__random__'
    ? (llmStore.pickRandom?.() ?? null)
    : llmStore.enabledAgents.find(a => a.id === selectedAgentId.value) ?? null
)
const opts = reactive({ entities: true, relations: true, events: false, sentiment: false })

const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
watch(isExtracting, (val) => {
  if (val) { elapsed.value = 0; timer = setInterval(() => elapsed.value++, 1000) }
  else { if (timer) { clearInterval(timer); timer = null } }
})
onUnmounted(() => { if (timer) clearInterval(timer) })


const deleteTarget = ref<{ id: string; version: number } | null>(null)
function confirmDeleteOntology(id: string, version: number) { deleteTarget.value = { id, version } }
function doDeleteOntology() {
  if (deleteTarget.value) { projectStore.deleteOntologyVersion(deleteTarget.value.id); deleteTarget.value = null }
}

function onResearchImported(doc: { id: string; filename: string; ext: string; size: number; pages: number; chunks: number }) {
  const sizeStr = doc.size < 1024 ? `${doc.size} B` : doc.size < 1048576 ? `${(doc.size / 1024).toFixed(1)} KB` : `${(doc.size / 1048576).toFixed(1)} MB`
  docStore.files.push({
    id: doc.id, name: doc.filename, ext: doc.ext,
    size: sizeStr, pages: String(doc.pages ?? 1), chunks: doc.chunks,
    status: 'done', statusLabel: '리서치',
  })
  const entry = { id: doc.id, name: doc.filename, ext: doc.ext, size: sizeStr, pages: String(doc.pages ?? 1), chunks: doc.chunks }
  if (!projectStore.currentProjectId) {
    projectStore.createProject(entry)
  } else {
    projectStore.addDocumentToCurrentProject(entry)
  }
  showResearchModal.value = false
  docStore.addLog('info', `리서치 가져오기 완료: ${doc.filename} (${doc.chunks}개 청크)`)
}

function fileColor(ext: string) {
  const map: Record<string, string> = { pdf: '#C8D8E8', docx: '#C8E8D0', txt: '#E8E0C8', md: '#E8C8D8' }
  return map[ext] || '#E8E8E8'
}

function triggerFileInput() { fileInput.value?.click() }
async function handleDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files) for (const f of Array.from(e.dataTransfer.files)) await docStore.upload(f)
}
async function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files) for (const f of Array.from(input.files)) await docStore.upload(f)
  input.value = ''
}
function onProjectSwitch(e: Event) { projectStore.setCurrentProject((e.target as HTMLSelectElement).value) }

function startExtraction() {
  const agent = selectedAgent.value
  if (!agent) { docStore.addLog('error', 'LLM 모델이 설정되지 않았습니다.'); return }
  showDbModal.value = true
}

async function onDbSkip() {
  showDbModal.value = false
  const agent = selectedAgent.value
  if (!agent) return
  // 추출 시작 후 1초 뒤 지식그래프 탭으로 자동 전환
  docStore.extractOntology(topic.value, purpose.value, opts, agent, extractionMethod.value)
  setTimeout(() => router.push('/ontology'), 1000)
}

async function onDbConfirm(dbId: string | null) {
  showDbModal.value = false
  const agent = selectedAgent.value
  if (!agent) return
  docStore.extractOntology(topic.value, purpose.value, opts, agent, extractionMethod.value)
  setTimeout(() => router.push('/ontology'), 1000)
}
</script>

<style scoped>
.upload-view { display: flex; gap: 24px; padding: 32px 40px; height: 100%; overflow: hidden; }

.left-panel { flex: 1; display: flex; flex-direction: column; gap: 0; overflow-y: auto; min-width: 0; }

.project-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; border: 1px solid #EAEAEA; border-radius: 12px 12px 0 0; background: #FFF; border-bottom: none; }
.project-selector { display: flex; align-items: center; gap: 10px; }
.project-icon { font-size: 18px; color: #FF5722; }
.project-name { font-size: 14px; font-weight: 700; color: #000; }
.project-name.no-project { color: #AAA; }
.project-meta { font-size: 10px; color: #AAA; margin-top: 2px; }
.project-actions { display: flex; align-items: center; gap: 8px; }
.project-select { padding: 5px 8px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 12px; background: #FFF; color: #333; outline: none; cursor: pointer; }
.btn-new-project { padding: 5px 12px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 12px; font-weight: 600; background: #FAFAFA; color: #555; cursor: pointer; transition: all 0.15s; }
.btn-new-project:hover { border-color: #FF5722; color: #FF5722; background: #FFF9F8; }
.btn-import-research { background: none; border: 1px solid #EAEAEA; border-radius: 6px; padding: 3px 8px; font-size: 12px; cursor: pointer; transition: all 0.15s; }
.btn-import-research:hover { border-color: #FF5722; background: #FFF9F8; }

.project-body { border: 1px solid #EAEAEA; border-top: none; border-radius: 0 0 12px 12px; background: #FAFAFA; margin-bottom: 16px; }
.doc-section-top { display: flex; align-items: center; justify-content: space-between; padding: 12px 20px 6px; }
.doc-section-label { font-size: 9px; font-weight: 700; color: #BBB; letter-spacing: 1px; text-transform: uppercase; }
.doc-list { padding: 0 20px 12px; display: flex; flex-direction: column; gap: 6px; max-height: 240px; overflow-y: auto; }
.doc-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: #FFF; border: 1px solid #EAEAEA; border-radius: 8px; }
.doc-type-badge { padding: 2px 7px; border-radius: 4px; font-size: 9px; font-weight: 700; font-family: 'JetBrains Mono', monospace; color: #444; flex-shrink: 0; }
.doc-info { flex: 1; min-width: 0; }
.doc-name { font-size: 13px; font-weight: 500; color: #222; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-meta { font-size: 10px; color: #AAA; margin-top: 1px; }
.doc-status-done { padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 500; font-family: 'JetBrains Mono', monospace; background: #E8F5E9; color: #2E7D32; flex-shrink: 0; }
.doc-remove { background: none; border: none; color: #CCC; cursor: pointer; font-size: 11px; padding: 2px 4px; border-radius: 3px; transition: all 0.15s; flex-shrink: 0; }
.doc-remove:hover { color: #F44336; background: #FEE; }

.onto-section { border-top: 1px solid #EAEAEA; }
.onto-section-header { display: flex; align-items: center; gap: 10px; padding: 10px 20px 8px; }
.onto-connector-line { width: 20px; height: 2px; background: #FF5722; flex-shrink: 0; }
.onto-section-label { font-size: 9px; font-weight: 700; color: #FF5722; letter-spacing: 1px; text-transform: uppercase; }
.onto-version-count { font-size: 9px; color: #BBB; margin-left: auto; }
.onto-empty { padding: 8px 20px 16px; font-size: 12px; color: #CCC; }
.onto-list { padding: 0 20px 12px; display: flex; flex-direction: column; gap: 6px; }
.onto-row { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; background: #FFF; border: 1px solid #EAEAEA; border-radius: 8px; transition: all 0.15s; }
.onto-row.active { border-color: rgba(255,87,34,0.4); background: #FFFAF8; }
.onto-row:hover { border-color: #DDD; }
.onto-version { font-size: 11px; font-weight: 700; color: #FF5722; min-width: 22px; padding-top: 1px; }
.onto-main { flex: 1; min-width: 0; }
.onto-model { font-size: 11px; font-weight: 600; color: #333; }
.onto-stats { font-size: 10px; color: #AAA; margin-top: 2px; }
.onto-topic { font-size: 11px; color: #666; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.onto-row-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.onto-active-badge { font-size: 10px; font-weight: 700; color: #FF5722; font-family: 'JetBrains Mono', monospace; }
.btn-set-active { padding: 2px 8px; border: 1px solid #EAEAEA; border-radius: 4px; font-size: 10px; background: #FAFAFA; color: #666; cursor: pointer; transition: all 0.15s; }
.btn-set-active:hover { border-color: #FF5722; color: #FF5722; }
.btn-goto-graph { padding: 2px 8px; border: 1px solid #000; border-radius: 4px; font-size: 10px; background: #000; color: #FFF; text-decoration: none; font-family: 'JetBrains Mono', monospace; transition: all 0.15s; }
.btn-goto-graph:hover { background: #FF5722; border-color: #FF5722; }
.btn-delete-onto { background: none; border: none; color: #DDD; cursor: pointer; font-size: 11px; padding: 2px 4px; border-radius: 3px; transition: all 0.15s; }
.btn-delete-onto:hover { color: #F44336; background: #FEE; }

.drop-zone-inline { margin: 0 20px 16px; padding: 10px 14px; border: 1px dashed #DDD; border-radius: 8px; display: flex; align-items: center; gap: 8px; cursor: pointer; transition: all 0.15s; background: #FFF; }
.drop-zone-inline:hover, .drop-zone-inline.drag-over { border-color: #FF5722; background: #FFFAF8; }
.drop-inline-icon { font-size: 16px; color: #CCC; }
.drop-inline-text { font-size: 12px; color: #AAA; }
.research-import { border-style: dashed; border-color: #E0D4F5; background: #FDFBFF; }
.research-import:hover { border-color: #9C27B0; background: #F9F0FF; }
.research-import .drop-inline-icon { color: inherit; }
.research-import .drop-inline-text { color: #9C27B0; font-weight: 500; }

.no-project-state { display: flex; flex-direction: column; gap: 16px; }
.drop-zone-main { border: 1px dashed #CCC; border-radius: 12px; padding: 48px 32px; text-align: center; cursor: pointer; transition: all 0.15s; background: #FAFAFA; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.drop-zone-main:hover, .drop-zone-main.drag-over { border-color: #FF5722; background: rgba(255,87,34,0.03); }
.btn-research-large {
  padding: 12px; border: 1px dashed #EAEAEA; border-radius: 10px; background: #FFF;
  font-size: 13px; font-weight: 600; color: #888; cursor: pointer; transition: all 0.15s;
  font-family: 'Space Grotesk', sans-serif;
}
.btn-research-large:hover { border-color: #FF5722; color: #FF5722; background: #FFF9F8; }
.drop-icon { width: 48px; height: 48px; border: 1px solid #EAEAEA; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 20px; color: #999; background: #FFF; }
.drop-title { font-size: 14px; font-weight: 600; color: #333; }
.drop-desc { font-size: 12px; color: #AAA; }
.drop-extensions { display: flex; gap: 6px; }
.ext-badge { padding: 2px 8px; border: 1px solid #EAEAEA; border-radius: 4px; font-size: 11px; font-family: 'JetBrains Mono', monospace; color: #777; background: #FFF; }

.prev-projects { border: 1px solid #EAEAEA; border-radius: 12px; overflow: hidden; }
.prev-label { font-size: 9px; font-weight: 700; color: #BBB; letter-spacing: 1px; text-transform: uppercase; padding: 10px 16px 6px; background: #FAFAFA; border-bottom: 1px solid #EAEAEA; display: block; }
.prev-project-row { padding: 10px 16px; cursor: pointer; border-bottom: 1px solid #F5F5F5; transition: background 0.1s; }
.prev-project-row:last-child { border-bottom: none; }
.prev-project-row:hover { background: #FFFAF8; }
.prev-proj-name { font-size: 13px; font-weight: 600; color: #222; }
.prev-proj-meta { font-size: 10px; color: #AAA; margin-top: 2px; }

.hidden-input { display: none; }

.progress-log { margin-top: 16px; border: 1px solid #EAEAEA; border-radius: 12px; overflow: hidden; }
.log-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 14px; background: #1A1A1A; }
.log-title { font-size: 11px; color: #888; letter-spacing: 1px; font-family: 'JetBrains Mono', monospace; }
.log-status { font-size: 10px; color: #4CAF50; font-family: 'JetBrains Mono', monospace; }
.log-status.running { animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.log-body { background: #111; padding: 10px 14px; display: flex; flex-direction: column; gap: 3px; max-height: 200px; overflow-y: auto; }
.log-line { display: flex; align-items: flex-start; gap: 8px; font-size: 11px; line-height: 1.5; }
.log-time { color: #555; flex-shrink: 0; font-family: 'JetBrains Mono', monospace; }
.log-level { padding: 0 5px; border-radius: 3px; font-size: 9px; font-weight: 700; flex-shrink: 0; font-family: 'JetBrains Mono', monospace; line-height: 1.8; }
.log-level.info  { background: #1A3A1A; color: #66BB6A; }
.log-level.warn  { background: #3A2E1A; color: #FFA726; }
.log-level.error { background: #3A1A1A; color: #EF5350; }
.log-msg { color: #BBBBBB; }

.right-panel { width: 340px; flex-shrink: 0; overflow-y: auto; }
.settings-card { border: 1px solid #EAEAEA; border-radius: 12px; padding: 24px; background: #FFF; box-shadow: 0 2px 8px rgba(0,0,0,0.04); display: flex; flex-direction: column; gap: 18px; }
.settings-title { font-size: 14px; font-weight: 700; color: #000; padding-bottom: 12px; border-bottom: 1px solid #EAEAEA; }
.warn-box { padding: 10px 14px; background: #FFF8E1; border: 1px solid #FFE082; border-radius: 6px; font-size: 12px; color: #F57F17; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 11px; font-weight: 600; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }
.form-textarea { border: 1px solid #EAEAEA; border-radius: 6px; padding: 10px 12px; font-size: 13px; color: #333; font-family: 'Space Grotesk', sans-serif; resize: vertical; outline: none; transition: border-color 0.15s; }
.form-textarea:focus { border-color: #FF5722; }
.model-select { width: 100%; padding: 9px 12px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 13px; color: #333; font-family: 'JetBrains Mono', monospace; background: #FFF; outline: none; cursor: pointer; transition: border-color 0.15s; }
.model-select:focus { border-color: #FF5722; }
.no-model-msg { padding: 10px 12px; border: 1px dashed #E0E0E0; border-radius: 6px; font-size: 12px; color: #999; background: #FAFAFA; line-height: 1.5; }
.no-model-msg strong { color: #FF5722; }
.option-rows { display: flex; flex-direction: column; gap: 8px; }
.option-row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #444; cursor: pointer; }
.option-row input[type="checkbox"] { accent-color: #FF5722; width: 14px; height: 14px; }
.engine-toggle { display: flex; gap: 4px; }
.engine-btn { flex: 1; padding: 7px 0; border: 1px solid #EAEAEA; border-radius: 6px; background: #FAFAFA; font-size: 12px; color: #888; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.engine-btn.active { background: #000; color: #FFF; border-color: #000; }
.engine-desc { font-size: 11px; color: #AAA; margin-top: 6px; line-height: 1.5; }
.btn-start { padding: 12px 20px; background: #000; color: #FFF; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; font-family: 'Space Grotesk', sans-serif; cursor: pointer; transition: all 0.15s; }
.btn-start:hover:not(:disabled) { background: #FF5722; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(255,87,34,0.3); }
.btn-start:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-stop { background: #D32F2F; }
.btn-stop:hover { background: #B71C1C !important; transform: none !important; box-shadow: none !important; }
.extraction-progress { display: flex; align-items: center; gap: 14px; padding: 14px; border: 1px solid #FFF3E0; border-radius: 8px; background: #FFFAF5; }
.progress-spinner { width: 24px; height: 24px; border: 3px solid #FFE0CC; border-top-color: #FF5722; border-radius: 50%; animation: spin 0.8s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg) } }
.progress-info { flex: 1; display: flex; flex-direction: column; gap: 5px; }
.progress-step { font-size: 12px; font-weight: 600; color: #E65100; }
.progress-bar-wrap { height: 3px; background: #FFE0CC; border-radius: 2px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #FF5722, #FF9800); transition: width 0.25s ease; }
.progress-elapsed { font-size: 10px; color: #BBA090; font-family: 'JetBrains Mono', monospace; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); backdrop-filter: blur(4px); z-index: 1000; display: flex; align-items: center; justify-content: center; }
.confirm-modal { width: 380px; background: #FFF; border-radius: 12px; padding: 28px; box-shadow: 0 16px 48px rgba(0,0,0,0.2); }
.confirm-title { font-size: 16px; font-weight: 700; color: #000; margin-bottom: 12px; }
.confirm-desc { font-size: 13px; color: #555; line-height: 1.65; margin-bottom: 24px; }
.confirm-desc strong { color: #D32F2F; }
.confirm-actions { display: flex; gap: 10px; justify-content: flex-end; }
.btn-cancel { padding: 8px 20px; border: 1px solid #EAEAEA; border-radius: 6px; font-size: 13px; background: #FAFAFA; color: #555; cursor: pointer; }
.btn-cancel:hover { border-color: #999; }
.btn-confirm-delete { padding: 8px 20px; border: none; border-radius: 6px; font-size: 13px; font-weight: 700; background: #D32F2F; color: #FFF; cursor: pointer; transition: background 0.15s; }
.btn-confirm-delete:hover { background: #B71C1C; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.mono { font-family: 'JetBrains Mono', monospace; }
</style>

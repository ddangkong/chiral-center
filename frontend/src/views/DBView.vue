<template>
  <div class="db-view">
    <div class="left-panel">
      <div class="panel-header">
        <div class="header-icon">DB</div>
        <div class="header-info">
          <div class="header-title">{{ t('db.title') }}</div>
          <div class="header-meta mono">{{ dbStore.collections.length }}{{ t('db.collections') }}</div>
        </div>
        <button class="btn-new" @click="startCreate">{{ t('db.newDb') }}</button>
      </div>

      <div v-if="dbStore.collections.length > 0" class="db-list">
        <div
          v-for="col in dbStore.collections"
          :key="col.id"
          class="db-row"
          :class="{ active: col.id === dbStore.currentCollectionId }"
          @click="toggleCollection(col.id)"
        >
          <div class="db-row-icon">□</div>
          <div class="db-row-info">
            <div class="db-row-name">{{ col.name }}</div>
            <div class="db-row-desc">{{ col.description || t('db.noDesc') }}</div>
            <div class="db-row-meta mono">
              {{ t('db.records') }} {{ col.totalRecords }} · {{ t('db.files') }} {{ col.files.length }} · {{ fmtDate(col.updatedAt) }}
            </div>
          </div>
        </div>
      </div>

      <div v-else class="db-empty-list">
        {{ t('db.emptyList') }}
      </div>
    </div>

    <div class="right-panel">
      <div v-if="isCreating" class="detail-card">
        <div class="detail-title">New DB 만들기</div>

        <div class="form-group">
          <label class="form-label">DB 이름</label>
          <input
            v-model="newName"
            class="form-input"
            placeholder="예: 고객 문의 데이터"
          />
        </div>

        <div class="form-group">
          <label class="form-label">설명 (선택)</label>
          <input
            v-model="newDesc"
            class="form-input"
            placeholder="예: 회의록 모음, 고객 데이터 등"
          />
        </div>

        <div class="form-actions">
          <button class="btn-cancel" @click="isCreating = false">취소</button>
          <button class="btn-create" :disabled="!newName.trim()" @click="doCreate">만들기</button>
        </div>
      </div>

      <div v-else-if="dbStore.currentCollection" class="right-sections">
        <!-- 헤더 카드 -->
        <div class="detail-card">
          <div class="detail-header">
            <div>
              <div class="detail-title">{{ dbStore.currentCollection.name }}</div>
              <div class="detail-created mono">{{ t('db.records') }} {{ dbStore.currentCollection.totalRecords }} · {{ t('db.files') }} {{ dbStore.currentCollection.files.length }} · {{ fmtDate(dbStore.currentCollection.createdAt) }}</div>
            </div>
            <div class="detail-actions">
              <button class="btn-close-detail" @click="dbStore.setCurrentCollection(null)">{{ t('db.selectClear') }}</button>
              <button class="btn-delete-db" @click="deleteCurrentDb">{{ t('common.delete') }}</button>
            </div>
          </div>
        </div>

        <!-- 채팅 카드 -->
        <div v-if="dbStore.currentCollection.totalRecords > 0" class="db-chat">
          <div class="db-chat-bar">
            <span class="db-chat-title">{{ t('db.chatTitle') }}</span>
            <span class="db-chat-hint">{{ t('db.chatHint') }}</span>
          </div>

          <div class="db-chat-messages" ref="chatMessagesRef">
            <div v-if="!chatMessages.length" class="db-chat-empty">
              <span class="db-chat-empty-text">{{ t('db.chatEmpty') }}</span>
              <div class="db-chat-suggests">
                <button class="db-chat-sug" @click="sendSuggestion('이 데이터를 요약해줘')">{{ t('db.sugSummary') }}</button>
                <button class="db-chat-sug" @click="sendSuggestion('주요 키워드와 핵심 내용을 정리해줘')">{{ t('db.sugKeyPoints') }}</button>
                <button class="db-chat-sug" @click="sendSuggestion('이 데이터에서 중요한 인사이트는?')">{{ t('db.sugInsights') }}</button>
              </div>
            </div>

            <div v-for="(msg, idx) in chatMessages" :key="idx" class="db-chat-msg" :class="msg.role">
              <span class="db-msg-who">{{ msg.role === 'user' ? 'User' : 'AI' }}</span>
              <div v-if="msg.role === 'assistant'" class="db-msg-bubble md-content" v-html="renderMd(msg.content)"></div>
              <div v-else class="db-msg-bubble">{{ msg.content }}</div>
            </div>

            <div v-if="chatLoading" class="db-chat-msg assistant">
              <span class="db-msg-who">AI</span>
              <div class="db-msg-bubble typing">응답 생성 중...</div>
            </div>
          </div>

          <div class="db-chat-input-bar">
            <input
              v-model="chatInput"
              class="db-chat-input"
              :placeholder="t('db.chatPlaceholder')"
              @keydown.enter="sendChat"
              :disabled="chatLoading"
            />
            <button class="db-chat-send" @click="sendChat" :disabled="!chatInput.trim() || chatLoading">{{ t('common.send') }}</button>
          </div>
        </div>

        <!-- 파일 관리 카드 -->
        <div class="detail-card">
          <div class="section-label mono">
            {{ t('db.fileList') }}
            <span v-if="dbStore.currentCollection.files.length" class="file-count">{{ dbStore.currentCollection.files.length }}</span>
          </div>
          <div v-if="dbStore.currentCollection.files.length === 0" class="file-empty">
            업로드된 파일이 없습니다.
          </div>
          <div v-else class="file-list-scroll">
            <div v-for="f in dbStore.currentCollection.files" :key="f.name" class="file-row">
              <div class="file-badge">{{ ext(f.name) }}</div>
              <div class="file-info">
                <div class="file-name">{{ f.name }}</div>
                <div v-if="f.chunks" class="file-meta mono">레코드 {{ f.chunks }}개</div>
              </div>
              <div class="file-status mono">처리됨</div>
            </div>
          </div>
          <button v-if="dbStore.currentCollection.files.length > 0" class="btn-clear" @click="clearCurrentDb">{{ t('db.clearAll') }}</button>

          <div class="section-label mono" style="margin-top: 4px">{{ t('db.fileUpload') }}</div>
          <div
            class="upload-zone"
            :class="{ dragging: isDragging, uploading: dbStore.isUploading }"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="onDrop"
            @click="fileInput?.click()"
          >
            <input
              ref="fileInput"
              type="file"
              multiple
              accept=".csv,.json,.jsonl,.txt,.md"
              style="display: none"
              @change="onFileSelect"
            />
            <div class="upload-icon">{{ dbStore.isUploading ? '...' : '+' }}</div>
            <div class="upload-text">{{ dbStore.isUploading ? '...' : t('db.uploadZone') }}</div>
            <div class="upload-sub">CSV · JSON · JSONL · TXT · MD</div>
          </div>

          <div v-if="dbStore.logs.length > 0" class="log-box">
            <div v-for="(l, i) in dbStore.logs" :key="i" class="log-line mono">{{ l }}</div>
          </div>
        </div>
      </div>

      <div v-else class="no-selection-wrap">
        <div class="no-selection">
          <div class="no-sel-icon">DB</div>
          <div class="no-sel-text">{{ t('db.selectOrCreate') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, reactive, nextTick, watch, computed } from 'vue'
import { useDatabaseStore } from '../stores/database'
import { useLLMStore } from '../stores/llm'
import { useI18n } from '../composables/useI18n'
import { marked } from 'marked'

// marked 설정: 간결한 출력
marked.setOptions({ breaks: true, gfm: true })

const dbStore = useDatabaseStore()
const llmStore = useLLMStore()
const { t } = useI18n()

const fileInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const isCreating = ref(false)
const newName = ref('')
const newDesc = ref('')

// Chat state
const chatMessages = ref<{ role: string; content: string }[]>([])
const chatInput = ref('')
const chatLoading = ref(false)
const chatMessagesRef = ref<HTMLElement>()

// Reset chat when collection changes
watch(() => dbStore.currentCollectionId, () => {
  chatMessages.value = []
  chatInput.value = ''
})

onMounted(() => {
  if (dbStore.currentCollectionId) dbStore.fetchStatus(dbStore.currentCollectionId)
})

function startCreate() {
  isCreating.value = true
  newName.value = ''
  newDesc.value = ''
  dbStore.setCurrentCollection(null)
}

function doCreate() {
  if (!newName.value.trim()) return
  dbStore.createCollection(newName.value.trim(), newDesc.value.trim())
  isCreating.value = false
}

async function onDrop(e: DragEvent) {
  isDragging.value = false
  const id = dbStore.currentCollectionId
  if (!id || !e.dataTransfer?.files) return
  for (const file of Array.from(e.dataTransfer.files)) {
    await dbStore.uploadFile(id, file)
  }
}

async function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const id = dbStore.currentCollectionId
  if (input.files && id) {
    for (const file of Array.from(input.files)) {
      await dbStore.uploadFile(id, file)
    }
  }
  input.value = ''
}

async function clearCurrentDb() {
  const id = dbStore.currentCollectionId
  if (id) await dbStore.clearCollection(id)
}

function deleteCurrentDb() {
  const id = dbStore.currentCollectionId
  if (id) dbStore.deleteCollection(id)
}

function toggleCollection(id: string) {
  if (dbStore.currentCollectionId === id) {
    dbStore.setCurrentCollection(null)
    return
  }
  dbStore.setCurrentCollection(id)
}

function ext(name: string) {
  return name.split('.').pop()?.toUpperCase() ?? 'FILE'
}

function fmtDate(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

function renderMd(text: string): string {
  return marked.parse(text) as string
}

function scrollChat() {
  nextTick(() => { if (chatMessagesRef.value) chatMessagesRef.value.scrollTop = chatMessagesRef.value.scrollHeight })
}

async function sendSuggestion(text: string) {
  chatInput.value = text
  await sendChat()
}

async function sendChat() {
  const text = chatInput.value.trim()
  if (!text || chatLoading.value) return

  const agent = llmStore.enabledAgents[0]
  if (!agent?.apiKey) { dbStore.addLog('LLM API 키를 설정하세요 (상단 LLM Model 버튼)'); return }

  chatMessages.value.push({ role: 'user', content: text })
  chatInput.value = ''
  chatLoading.value = true
  scrollChat()

  try {
    const res = await fetch('/api/db/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        project_id: dbStore.currentCollectionId,
        messages: chatMessages.value,
        collection_name: dbStore.currentCollection?.name || '',
        provider: agent.provider,
        model: agent.modelName,
        api_key: agent.apiKey,
        base_url: agent.baseUrl,
      }),
    })
    const resText = await res.text()
    if (!resText) throw new Error('서버 응답이 비어있습니다')
    let data: any
    try { data = JSON.parse(resText) } catch { throw new Error('응답 파싱 실패') }
    if (!res.ok) throw new Error(data.detail || '채팅 실패')
    chatMessages.value.push({ role: 'assistant', content: data.response })
  } catch (e: any) {
    chatMessages.value.push({ role: 'assistant', content: `오류: ${e.message}` })
  } finally {
    chatLoading.value = false
    scrollChat()
  }
}
</script>

<style scoped>
.db-view {
  display: flex;
  gap: 24px;
  padding: 32px 40px;
  height: 100%;
  overflow: hidden;
}

.left-panel {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  border: 1px solid #eaeaea;
  border-radius: 12px 12px 0 0;
  background: #fff;
  border-bottom: none;
}

.header-icon {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #fff2eb;
  color: #ff5722;
  font-size: 11px;
  font-weight: 700;
}

.header-info {
  flex: 1;
}

.header-title {
  font-size: 14px;
  font-weight: 700;
  color: #000;
}

.header-meta {
  font-size: 10px;
  color: #aaa;
  margin-top: 2px;
}

.btn-new {
  padding: 5px 12px;
  border: 1px solid #eaeaea;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  background: #fafafa;
  color: #555;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn-new:hover {
  border-color: #ff5722;
  color: #ff5722;
  background: #fff9f8;
}

.db-list {
  border: 1px solid #eaeaea;
  border-top: none;
  border-radius: 0 0 12px 12px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
}

.db-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
  transition: background 0.1s;
}

.db-row:last-child {
  border-bottom: none;
  border-radius: 0 0 12px 12px;
}

.db-row:hover {
  background: #fff;
}

.db-row.active {
  background: #fff9f8;
  border-left: 3px solid #ff5722;
}

.db-row-icon {
  font-size: 12px;
  color: #ccc;
  flex-shrink: 0;
  padding-top: 2px;
}

.db-row.active .db-row-icon {
  color: #ff5722;
}

.db-row-info {
  flex: 1;
  min-width: 0;
}

.db-row-name {
  font-size: 13px;
  font-weight: 700;
  color: #000;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.db-row-desc {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.db-row-meta {
  font-size: 10px;
  color: #bbb;
  margin-top: 3px;
}

.db-empty-list {
  border: 1px solid #eaeaea;
  border-top: none;
  border-radius: 0 0 12px 12px;
  padding: 24px 20px;
  font-size: 12px;
  color: #999;
  background: #fafafa;
  line-height: 1.6;
}

.right-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  display: flex;
}

.right-sections {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-card {
  width: 100%;
  border: 1px solid #eaeaea;
  border-radius: 12px;
  padding: 24px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.detail-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.detail-title {
  font-size: 16px;
  font-weight: 700;
  color: #000;
}

.detail-created {
  font-size: 10px;
  color: #aaa;
  margin-top: 4px;
}

.btn-delete-db {
  padding: 5px 12px;
  border: 1px solid #ffcdd2;
  border-radius: 6px;
  font-size: 11px;
  background: #fff;
  color: #e53935;
  cursor: pointer;
}

.btn-close-detail {
  padding: 5px 12px;
  border: 1px solid #eaeaea;
  border-radius: 6px;
  font-size: 11px;
  background: #fff;
  color: #666;
  cursor: pointer;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 11px;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.form-input,
.form-textarea {
  border: 1px solid #eaeaea;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 13px;
  color: #333;
  font-family: 'Space Grotesk', sans-serif;
  outline: none;
  transition: border-color 0.15s;
}

.form-input:focus,
.form-textarea:focus {
  border-color: #ff5722;
}

.form-textarea {
  resize: vertical;
}

.form-help {
  font-size: 12px;
  line-height: 1.6;
  color: #777;
}

.form-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.btn-cancel {
  padding: 8px 18px;
  border: 1px solid #eaeaea;
  border-radius: 6px;
  font-size: 13px;
  background: #fafafa;
  color: #888;
  cursor: pointer;
}

.btn-create {
  padding: 8px 18px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  background: #ff5722;
  color: #fff;
  cursor: pointer;
}

.btn-create:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.stats-row {
  display: flex;
  gap: 16px;
}

.stat-box {
  flex: 1;
  border: 1px solid #eaeaea;
  border-radius: 8px;
  padding: 14px 16px;
  background: #fafafa;
  text-align: center;
}

.stat-val {
  font-size: 22px;
  font-weight: 700;
  color: #000;
}

.stat-label {
  font-size: 10px;
  color: #aaa;
  margin-top: 4px;
  letter-spacing: 0.5px;
}

.section-label {
  font-size: 9px;
  font-weight: 700;
  color: #bbb;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.file-empty {
  font-size: 12px;
  color: #ccc;
}

.file-list-scroll {
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid #eaeaea;
  border-radius: 8px;
  padding: 6px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex-shrink: 0;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid #eaeaea;
  border-radius: 8px;
  background: #fafafa;
}

.file-badge {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  background: #222;
  color: #fff;
  flex-shrink: 0;
}

.file-info {
  flex: 1;
  min-width: 0;
}

.file-name {
  font-size: 13px;
  font-weight: 500;
  color: #222;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-meta {
  font-size: 10px;
  color: #aaa;
  margin-top: 2px;
}

.btn-clear {
  align-self: flex-start;
  padding: 5px 12px;
  border: 1px solid #ffcdd2;
  border-radius: 6px;
  font-size: 11px;
  background: #fff;
  color: #e53935;
  cursor: pointer;
  margin-top: 4px;
}

.upload-zone {
  border: 2px dashed #eaeaea;
  border-radius: 10px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  transition: all 0.15s;
  background: #fafafa;
}

.upload-zone:hover,
.upload-zone.dragging {
  border-color: #ff5722;
  background: rgba(255, 87, 34, 0.03);
}

.upload-zone.uploading {
  pointer-events: none;
  opacity: 0.7;
}

.upload-icon {
  width: 40px;
  height: 40px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: #fff;
  border: 1px solid #eaeaea;
  font-size: 24px;
  color: #ccc;
}

.upload-text {
  font-size: 13px;
  font-weight: 600;
  color: #555;
}

.upload-sub {
  font-size: 11px;
  color: #aaa;
}

.log-box {
  background: #111;
  border-radius: 8px;
  padding: 12px 14px;
  max-height: 200px;
  min-height: 60px;
  overflow-y: auto;
}

.log-line {
  font-size: 11px;
  color: #7cbb7c;
  line-height: 1.6;
}

.no-selection-wrap {
  flex: 1;
  min-height: 100%;
  display: grid;
  place-items: center;
}

.no-selection {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  text-align: center;
}

.no-sel-icon {
  width: 72px;
  height: 72px;
  border-radius: 20px;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, #fff7f3 0%, #fff 100%);
  border: 1px solid #f2e3db;
  color: #ff5722;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.no-sel-text {
  font-size: 15px;
  color: #999;
}

.file-count {
  color: #ff5722;
  margin-left: 4px;
}

.file-status {
  font-size: 9px;
  color: #4caf50;
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 4px;
  background: #e8f5e9;
}

/* ── DB Chat ── */
.db-chat {
  border: 1px solid #eaeaea;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  min-height: 300px;
  max-height: 420px;
  overflow: hidden;
}

.db-chat-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; border-bottom: 1px solid #f0f0f0; flex-shrink: 0;
}
.db-chat-title { font-size: 13px; font-weight: 600; color: #222; font-family: 'Space Grotesk', sans-serif; }
.db-chat-hint { font-size: 11px; color: #bbb; font-family: 'Space Grotesk', sans-serif; }

.db-chat-messages { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.db-chat-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 12px; }
.db-chat-empty-text { font-size: 13px; color: #bbb; font-family: 'Space Grotesk', sans-serif; }

.db-chat-suggests { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.db-chat-sug {
  padding: 6px 14px; border: 1px solid #eaeaea; border-radius: 20px;
  background: #fff; font-size: 12px; color: #888; font-family: 'Space Grotesk', sans-serif;
  cursor: pointer; transition: all 0.15s;
}
.db-chat-sug:hover { border-color: #222; color: #222; }

.db-chat-msg { max-width: 80%; }
.db-chat-msg.user { align-self: flex-end; }
.db-chat-msg.assistant { align-self: flex-start; }

.db-msg-who { font-size: 11px; color: #999; margin-bottom: 3px; display: block; font-family: 'Space Grotesk', sans-serif; font-weight: 600; }
.db-chat-msg.user .db-msg-who { text-align: right; }

.db-msg-bubble { padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.6; font-family: 'Space Grotesk', sans-serif; }
.db-chat-msg.user .db-msg-bubble { background: #222; color: #fff; border-bottom-right-radius: 4px; }
.db-chat-msg.assistant .db-msg-bubble { background: #f5f5f5; color: #333; border-bottom-left-radius: 4px; }
.db-msg-bubble.typing { color: #aaa; font-style: italic; }

.db-chat-input-bar { display: flex; gap: 8px; padding: 10px 16px; border-top: 1px solid #eaeaea; flex-shrink: 0; }
.db-chat-input {
  flex: 1; border: 1px solid #eaeaea; border-radius: 8px;
  padding: 9px 14px; font-size: 13px; outline: none; color: #333;
  font-family: 'Space Grotesk', sans-serif;
  transition: border-color 0.15s;
}
.db-chat-input:focus { border-color: #222; }

.db-chat-send {
  padding: 9px 18px; border: none; border-radius: 8px;
  background: #222; color: #fff; font-size: 13px; font-weight: 600;
  font-family: 'Space Grotesk', sans-serif;
  cursor: pointer; transition: all 0.15s;
}
.db-chat-send:hover { background: #444; }
.db-chat-send:disabled { opacity: 0.3; cursor: not-allowed; }

.mono {
  font-family: 'JetBrains Mono', monospace;
}

/* ── Markdown 렌더링 스타일 ── */
.md-content :deep(h1) { font-size: 15px; font-weight: 700; margin: 10px 0 6px; color: #111; }
.md-content :deep(h2) { font-size: 14px; font-weight: 700; margin: 10px 0 5px; color: #222; border-bottom: 1px solid #e8e8e8; padding-bottom: 4px; }
.md-content :deep(h3) { font-size: 13px; font-weight: 700; margin: 8px 0 4px; color: #333; }
.md-content :deep(p) { margin: 4px 0; line-height: 1.6; }
.md-content :deep(ul), .md-content :deep(ol) { margin: 4px 0; padding-left: 18px; }
.md-content :deep(li) { margin: 2px 0; line-height: 1.5; }
.md-content :deep(strong) { font-weight: 700; color: #111; }
.md-content :deep(em) { font-style: italic; color: #555; }
.md-content :deep(code) {
  background: #e8e8e8; padding: 1px 5px; border-radius: 3px;
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
}
.md-content :deep(blockquote) {
  margin: 6px 0; padding: 4px 12px; border-left: 3px solid #ddd;
  color: #666; font-size: 12px;
}
.md-content :deep(table) { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 12px; }
.md-content :deep(th), .md-content :deep(td) { border: 1px solid #e0e0e0; padding: 5px 8px; text-align: left; }
.md-content :deep(th) { background: #f5f5f5; font-weight: 600; }
.md-content :deep(hr) { border: none; border-top: 1px solid #e8e8e8; margin: 8px 0; }
</style>

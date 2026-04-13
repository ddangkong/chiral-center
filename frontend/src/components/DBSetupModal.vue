<template>
  <Teleport to="body">
    <Transition name="fade">
      <div class="modal-overlay" v-if="visible" @click.self="emit('skip')">
        <div class="db-modal">

          <div class="modal-header">
            <div class="modal-title">내부 DB 연동</div>
            <div class="modal-sub">이 프로젝트에 연결할 DB를 선택하세요</div>
          </div>

          <div v-if="dbStore.collections.length === 0" class="no-db">
            <div class="no-db-icon">▣</div>
            <div class="no-db-text">생성된 DB가 없습니다</div>
            <div class="no-db-sub">사이드바 DB 메뉴에서 New DB를 만드세요</div>
          </div>

          <div v-else class="db-list">
            <div
              v-for="col in dbStore.collections"
              :key="col.id"
              class="db-item"
              :class="{ selected: selectedId === col.id }"
              @click="selectedId = col.id"
            >
              <div class="db-item-icon">▣</div>
              <div class="db-item-info">
                <div class="db-item-name">{{ col.name }}</div>
                <div class="db-item-desc">{{ col.description }}</div>
                <div class="db-item-meta mono">{{ col.totalRecords }}개 레코드 · 파일 {{ col.files.length }}개</div>
              </div>
              <div class="db-item-check" v-if="selectedId === col.id">✓</div>
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn-skip" @click="emit('skip')">연결 없이 진행</button>
            <button class="btn-connect"
              :disabled="!selectedId"
              @click="confirm">
              연결 →
            </button>
          </div>

        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useDatabaseStore } from '../stores/database'

const props = defineProps<{ visible: boolean; projectId: string }>()
const emit = defineEmits<{
  (e: 'skip'): void
  (e: 'confirm', dbId: string | null): void
}>()

const dbStore = useDatabaseStore()
const selectedId = ref<string | null>(null)

watch(() => props.visible, (v) => { if (v) selectedId.value = null })

function confirm() {
  emit('confirm', selectedId.value)
}
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 9999;
  backdrop-filter: blur(4px);
}
.db-modal {
  background: #FFF; border-radius: 16px; width: 480px; max-width: 95vw;
  padding: 28px; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  display: flex; flex-direction: column; gap: 20px;
}
.modal-header { border-bottom: 1px solid #EAEAEA; padding-bottom: 16px; }
.modal-title { font-size: 16px; font-weight: 700; color: #000; }
.modal-sub { font-size: 12px; color: #AAA; margin-top: 4px; }

.no-db { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px 0; }
.no-db-icon { font-size: 32px; color: #DDD; }
.no-db-text { font-size: 14px; font-weight: 600; color: #AAA; }
.no-db-sub { font-size: 12px; color: #CCC; }

.db-list { display: flex; flex-direction: column; gap: 8px; max-height: 300px; overflow-y: auto; }
.db-item {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 14px 16px; border: 1px solid #EAEAEA; border-radius: 10px;
  cursor: pointer; transition: all 0.15s; background: #FAFAFA;
}
.db-item:hover { border-color: #BBB; background: #FFF; }
.db-item.selected { border-color: #FF5722; background: #FFF9F8; }
.db-item-icon { font-size: 18px; color: #CCC; flex-shrink: 0; padding-top: 1px; }
.db-item.selected .db-item-icon { color: #FF5722; }
.db-item-info { flex: 1; min-width: 0; }
.db-item-name { font-size: 13px; font-weight: 700; color: #000; }
.db-item-desc { font-size: 11px; color: #888; margin-top: 3px; line-height: 1.5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.db-item-meta { font-size: 10px; color: #BBB; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
.db-item-check { font-size: 14px; font-weight: 700; color: #FF5722; flex-shrink: 0; }

.modal-actions { display: flex; gap: 10px; border-top: 1px solid #EAEAEA; padding-top: 16px; }
.btn-skip { flex: 1; padding: 10px; border: 1px solid #EAEAEA; border-radius: 8px; background: #FAFAFA; font-size: 13px; color: #888; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.btn-skip:hover { border-color: #CCC; color: #333; }
.btn-connect { flex: 2; padding: 10px; background: #FF5722; color: #FFF; border: none; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; transition: all 0.15s; font-family: 'Space Grotesk', sans-serif; }
.btn-connect:hover:not(:disabled) { background: #E64A19; }
.btn-connect:disabled { opacity: 0.4; cursor: not-allowed; }

.mono { font-family: 'JetBrains Mono', monospace; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>

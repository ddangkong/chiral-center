<template>
  <aside class="app-sidebar" :class="{ expanded: isExpanded }" @mouseenter="isExpanded = true" @mouseleave="isExpanded = false">
    <nav class="sidebar-nav">
      <RouterLink
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: route.path === item.path }"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="sidebar-bottom">
      <button class="nav-item settings-btn" @click="settingsStore.toggle()">
        <span class="nav-icon">⚙</span>
        <span class="nav-label">{{ t('nav.settings') }}</span>
      </button>
    </div>
    <SettingsPanel />
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSettingsStore } from '../../stores/settings'
import { useI18n } from '../../composables/useI18n'
import SettingsPanel from '../SettingsPanel.vue'

const route = useRoute()
const settingsStore = useSettingsStore()
const { t } = useI18n()
const isExpanded = ref(false)

const isAxortex = window.location.hostname.includes('axortex')

const navItems = computed(() => {
  const items = [
    { path: '/',           icon: '⌂', label: t('nav.home')       },
    { path: '/research',   icon: '🔬', label: t('nav.research')   },
    { path: '/upload',     icon: '↑', label: t('nav.upload')     },
    { path: '/ontology',   icon: '⬡', label: t('nav.graph')      },
    { path: '/persona',    icon: '👤', label: t('nav.persona')    },
    { path: '/simulation', icon: '⚡', label: t('nav.simulation') },
    { path: '/report',     icon: '⊞', label: t('nav.report')     },
    { path: '/db',         icon: '💾', label: t('nav.data')       },
  ]
  return isAxortex ? items.filter(i => i.path !== '/db') : items
})
</script>

<style scoped>
.app-sidebar {
  width: 60px;
  background: #FFFFFF;
  border-right: 1px solid #EAEAEA;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.app-sidebar.expanded {
  width: 200px;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  padding: 12px 0;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  color: #888888;
  text-decoration: none;
  position: relative;
  transition: all 0.15s ease;
  border-left: 2px solid transparent;
  white-space: nowrap;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 13px;
  font-weight: 500;
  background: none;
  border-top: none;
  border-right: none;
  border-bottom: none;
  width: 100%;
  text-align: left;
}

.nav-item:hover {
  color: #000000;
  background: #F7F7F7;
}

.nav-item.active,
.nav-item.router-link-active {
  color: #FF5722;
  background: #FFF3F0;
  border-left-color: #FF5722;
}

.nav-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
  flex-shrink: 0;
  line-height: 1;
}

.nav-label {
  opacity: 0;
  transition: opacity 0.15s ease;
  font-size: 13px;
}

.app-sidebar.expanded .nav-label {
  opacity: 1;
}

.sidebar-bottom {
  padding: 12px 0;
  border-top: 1px solid #EAEAEA;
}

.settings-btn {
  cursor: pointer;
  color: #888888;
}

.settings-btn:hover {
  color: #000000;
  background: #F7F7F7;
}
</style>

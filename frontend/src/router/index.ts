import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'

const isAxortex = window.location.hostname.includes('axortex')

const routes = [
  { path: '/', component: HomeView },
  { path: '/upload', component: () => import('../views/UploadView.vue') },
  { path: '/ontology', component: () => import('../views/OntologyView.vue') },
  { path: '/simulation', component: () => import('../views/SimulationView.vue') },
  { path: '/report', component: () => import('../views/ReportView.vue') },
  { path: '/persona', component: () => import('../views/PersonaView.vue') },
  ...(!isAxortex ? [{ path: '/db', component: () => import('../views/DBView.vue') }] : []),
  { path: '/research', component: () => import('../views/ResearchView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// axortex에서 /db 직접 접근 시 홈으로 리다이렉트
if (isAxortex) {
  router.beforeEach((to) => {
    if (to.path === '/db') return '/'
  })
}

export default router

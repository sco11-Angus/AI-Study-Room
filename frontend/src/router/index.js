import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  // 告警监测大屏 (§7.3)
  { path: '/dashboard', component: () => import('../views/Dashboard.vue') },
  // 防区配置：Canvas 画区 (§5.1)
  { path: '/regions', component: () => import('../views/RegionConfig.vue') },
  // 自习伴侣：状态宣告 (§4)
  { path: '/companion', component: () => import('../views/SeatCompanion.vue') }
]

export default createRouter({ history: createWebHistory(), routes })

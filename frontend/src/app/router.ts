import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import ResourcesPage from '@/features/resources/ResourcesPage.vue'
import MessagesPage from '@/features/messages/MessagesPage.vue'
import ResourceDetailPage from '@/features/resources/ResourceDetailPage.vue'
import LeadsPage from '@/features/leads/LeadsPage.vue'
import TasksPage from '@/features/tasks/TasksPage.vue'
import TaskDetailPage from '@/features/tasks/TaskDetailPage.vue'
import BriefingsPage from '@/features/briefings/BriefingsPage.vue'
import BriefingDetailPage from '@/features/briefings/BriefingDetailPage.vue'
import SettingsPage from '@/features/settings/SettingsPage.vue'
import SourcesPage from '@/features/sources/SourcesPage.vue'
import ErrorPage from '@/components/shared/ErrorPage.vue'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
  }
}

const routes: RouteRecordRaw[] = [
  { path: '/leads', name: 'leads', component: LeadsPage, meta: { title: '历史线索' } },
  { path: '/', name: 'messages', component: MessagesPage, meta: { title: '消息动态' } },
  { path: '/resources', name: 'resources', component: ResourcesPage, meta: { title: '资源库' } },
  {
    path: '/resources/:id',
    name: 'resource-detail',
    component: ResourceDetailPage,
    meta: { title: '资源详情' },
  },
  { path: '/tasks', name: 'tasks', component: TasksPage, meta: { title: '研究任务' } },
  {
    path: '/tasks/:id',
    name: 'task-detail',
    component: TaskDetailPage,
    meta: { title: '任务详情' },
  },
  {
    path: '/briefings',
    name: 'briefings',
    component: BriefingsPage,
    meta: { title: '简报历史' },
  },
  {
    path: '/briefings/:id',
    name: 'briefing-detail',
    component: BriefingDetailPage,
    meta: { title: '简报正文' },
  },
  {
    path: '/sources',
    name: 'sources',
    component: SourcesPage,
    meta: { title: '来源管理' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsPage,
    meta: { title: '设置' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: ErrorPage,
    props: {
      title: '页面暂不可用',
      detail: '未找到此页面。请检查地址，或返回资源库继续浏览。',
    },
    meta: { title: '页面不存在' },
  },
]

function headerOffset(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--app-header-height')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) ? value : 64
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) {
      let target: Element | null = null
      try {
        target = document.querySelector(to.hash)
      } catch {
        target = null
      }
      if (target) return { el: to.hash, top: headerOffset() + 16 }
    }
    return { top: 0 }
  },
})

export default router

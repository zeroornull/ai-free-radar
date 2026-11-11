<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useAppQuery } from '@/api/queries'
import { autoRefreshEnabled, setAutoRefresh } from '@/app/refresh'

const route = useRoute()
const { data: app } = useAppQuery()
const activeRun = computed(() => app.value?.active_run ?? null)
const openLeads = computed(() => app.value?.open_leads ?? 0)
const header = ref<HTMLElement | null>(null)
let resizeObserver: ResizeObserver | null = null
const navGroup = computed(() => {
  if (route.path === '/') return 'messages'
  if (route.path === '/leads' || route.path.startsWith('/leads/')) return 'leads'
  if (route.path === '/resources' || route.path.startsWith('/resources/')) return 'resources'
  if (route.path === '/briefings' || route.path.startsWith('/briefings/')) return 'briefings'
  if (route.path === '/tasks' || route.path.startsWith('/tasks/')) return 'tasks'
  if (route.path === '/settings' || route.path.startsWith('/settings/')) return 'settings'
  return ''
})

function toggleAutoRefresh(): void {
  setAutoRefresh(!autoRefreshEnabled.value)
}

onMounted(() => {
  const element = header.value
  if (!element) return
  const applyHeight = (): void => {
    const height = element.getBoundingClientRect().height
    document.documentElement.style.setProperty('--app-header-height', `${Math.ceil(height)}px`)
  }
  applyHeight()
  resizeObserver = new ResizeObserver(applyHeight)
  resizeObserver.observe(element)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <header ref="header" class="site-header">
    <div class="shell header-inner">
      <RouterLink class="brand" to="/">
        <span class="brand-text">
          <span class="brand-name">AIFreeRadar</span>
          <span class="brand-tagline">免费 AI API 消息雷达</span>
        </span>
      </RouterLink>
      <nav class="site-nav" aria-label="主要导航">
        <RouterLink to="/" :aria-current="navGroup === 'messages' ? 'page' : undefined">
          消息动态
        </RouterLink>
        <RouterLink to="/resources" :aria-current="navGroup === 'resources' ? 'page' : undefined">
          资源库
        </RouterLink>
        <RouterLink
          to="/leads"
          :aria-current="navGroup === 'leads' ? 'page' : undefined"
          :aria-label="openLeads > 0 ? `历史线索，${openLeads} 条来源待补` : undefined"
        >
          历史线索
          <span v-if="openLeads > 0" class="nav-count" aria-hidden="true">{{ openLeads }}</span>
        </RouterLink>
        <RouterLink to="/tasks" :aria-current="navGroup === 'tasks' ? 'page' : undefined">
          研究任务
        </RouterLink>
        <RouterLink to="/briefings" :aria-current="navGroup === 'briefings' ? 'page' : undefined">
          简报历史
        </RouterLink>
        <RouterLink to="/settings" :aria-current="navGroup === 'settings' ? 'page' : undefined">
          设置
        </RouterLink>
      </nav>
      <div class="header-tools">
        <span class="local-chip">仅本机使用</span>
        <span role="status" aria-live="polite">
          <button class="button ghost" type="button" :aria-pressed="autoRefreshEnabled" @click="toggleAutoRefresh">
            {{ autoRefreshEnabled ? '暂停自动刷新' : '恢复自动刷新' }}
          </button>
        </span>
      </div>
    </div>
  </header>
  <main id="main" class="shell app-main" tabindex="-1">
    <details class="policy-note">
      <summary>来源报告未经核验 · 未实测调用与网络访问</summary>
      <p>“消息动态”中的免费信息均来自来源报告，标注<strong>未核验消息</strong>；只有资源库中按需核验过的官方政策才显示“政策已核验”。所有资源均<strong>未实测调用</strong>，网络访问<strong>未实测</strong>。未说明的额度或条件按“未说明”保留；需绑定支付方式不代表需要付费，明确收费的机会不收录。</p>
    </details>
    <aside v-if="activeRun" class="notice" aria-label="正在运行的任务">
      研究任务运行中。<RouterLink :to="`/tasks/${activeRun.id}`">查看运行状态</RouterLink>。任务共用写入锁，完成后可发起下一项任务。
    </aside>
    <slot />
  </main>
  <footer class="shell site-footer">
    AIFreeRadar · 免费 API 消息雷达 · 时间按本机时区显示 · 所有研究记录保存在本机
  </footer>
</template>

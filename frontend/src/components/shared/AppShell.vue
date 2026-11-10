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
      <RouterLink class="brand" to="/resources">
        <span class="brand-mark" aria-hidden="true">
          <svg
            width="32"
            height="32"
            viewBox="0 0 32 32"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
            focusable="false"
          >
            <circle cx="16" cy="16" r="13" stroke-width="2" />
            <circle cx="16" cy="16" r="7" stroke-width="2" />
            <line x1="16" y1="16" x2="25.2" y2="6.8" stroke-width="2" />
            <circle cx="16" cy="16" r="2" fill="currentColor" stroke="none" />
          </svg>
        </span>
        <span class="brand-text">
          <span class="brand-name">AIFreeRadar</span>
          <span class="brand-tagline">免费 API 政策雷达</span>
        </span>
      </RouterLink>
      <nav class="site-nav" aria-label="主要导航">
        <RouterLink
          to="/leads"
          :aria-current="navGroup === 'leads' ? 'page' : undefined"
          :aria-label="openLeads > 0 ? `待核实线索，${openLeads} 条待处理` : undefined"
        >
          待核实线索
          <span v-if="openLeads > 0" class="nav-count" aria-hidden="true">{{ openLeads }}</span>
        </RouterLink>
        <RouterLink to="/resources" :aria-current="navGroup === 'resources' ? 'page' : undefined">
          资源库
        </RouterLink>
        <RouterLink to="/briefings" :aria-current="navGroup === 'briefings' ? 'page' : undefined">
          简报历史
        </RouterLink>
        <RouterLink to="/tasks" :aria-current="navGroup === 'tasks' ? 'page' : undefined">
          研究任务
        </RouterLink>
        <RouterLink to="/settings" :aria-current="navGroup === 'settings' ? 'page' : undefined">
          设置
        </RouterLink>
      </nav>
      <span role="status" aria-live="polite">
        <button class="button ghost" type="button" @click="toggleAutoRefresh">
          {{ autoRefreshEnabled ? '暂停自动刷新' : '恢复自动刷新' }}
        </button>
      </span>
    </div>
  </header>
  <main id="main" class="shell app-main" tabindex="-1">
    <aside class="policy-note" aria-label="核查范围说明">
      <svg
        class="note-icon"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      >
        <circle cx="12" cy="12" r="9" />
        <line x1="12" y1="11" x2="12" y2="16" />
        <circle cx="12" cy="7.5" r="1" fill="currentColor" stroke="none" />
      </svg>
      “有效”仅表示已核实官方免费政策符合零支付门槛。所有资源均<strong>未实测调用</strong>，网络访问<strong>未实测</strong>。核查结论以所列时间及官方来源为准，不保证政策持续有效或资源穷尽。
    </aside>
    <aside v-if="activeRun" class="notice" aria-label="正在运行的任务">
      研究任务运行中。<RouterLink :to="`/tasks/${activeRun.id}`">查看运行状态</RouterLink>。任务共用写入锁，完成后可发起下一项任务。
    </aside>
    <slot />
  </main>
  <footer class="shell site-footer">
    AIFreeRadar · 官方政策研究 · 时间按本机时区显示 · 所有研究记录保存在本机
  </footer>
</template>

<style>
.app-main {
  display: flex;
  flex-direction: column;
}
.app-main > .page-heading {
  order: -1;
}
.site-nav a { display: inline-flex; align-items: center; gap: 0.4rem; }
.nav-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-inline-size: 1.35rem;
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill);
  background: var(--color-accent-solid);
  color: var(--color-on-accent);
  font-size: 0.72rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.5;
}
</style>

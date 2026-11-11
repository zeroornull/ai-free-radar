<script setup lang="ts">
import { computed } from 'vue'
import type { AppRead } from '@/api/types'
import { labelFor } from '@/app/presentation'
import FactsList from '@/components/shared/FactsList.vue'

const props = defineProps<{ app: AppRead }>()

const categoryText = computed(() => {
  const values = props.app.default_scope.categories ?? []
  return values.map((value) => labelFor(props.app, value)).join('、') || '未设置'
})

const regionText = computed(() => labelFor(props.app, props.app.default_scope.region))
</script>

<template>
  <section class="panel schedule-summary" aria-labelledby="schedule-heading">
    <h2 id="schedule-heading">每日默认收集计划</h2>
    <p class="muted">
      默认按类别收集新的免费消息与更新，不自动核验已有资源。严格核验只在任务中指定资源标识时执行。
    </p>
    <FactsList>
      <dt>定时状态</dt>
      <dd>{{ app.schedule_enabled ? '已启用' : '已停用' }}</dd>
      <dt>执行时刻</dt>
      <dd>本机时间 {{ app.schedule_time }}</dd>
      <dt>默认类别</dt>
      <dd>{{ categoryText }}</dd>
      <dt>默认地区条件</dt>
      <dd>{{ regionText }}</dd>
      <dt>默认模式</dt>
      <dd>收集（不自动核验）</dd>
    </FactsList>
    <p class="muted">程序运行时才能执行计划。错过时刻后，下次启动最多补跑一次，不按离线天数逐天补齐。同日已完成的定时任务不会因重启重复运行。</p>
    <p class="muted">计划与默认范围在本地配置文件中设置。下方选择只用于本次手动任务；如需核验，请填写资源标识。</p>
  </section>
</template>

<style scoped>
.schedule-summary { min-inline-size: 0; margin: 0; }
.schedule-summary > p { font-size: 0.875rem; line-height: 1.75; }
.schedule-summary > p:last-child { padding-block-start: 0.75rem; border-block-start: 1px solid var(--color-border); font: 400 0.75rem/1.7 var(--font-ui); }
</style>
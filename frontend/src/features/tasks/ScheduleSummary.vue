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
  <section class="panel" aria-labelledby="schedule-heading">
    <h2 id="schedule-heading">每日默认计划</h2>
    <FactsList>
      <dt>定时状态</dt>
      <dd>{{ app.schedule_enabled ? '已启用' : '已停用' }}</dd>
      <dt>执行时刻</dt>
      <dd>本机时间 {{ app.schedule_time }}</dd>
      <dt>默认类别</dt>
      <dd>{{ categoryText }}</dd>
      <dt>默认地区条件</dt>
      <dd>{{ regionText }}</dd>
    </FactsList>
    <p class="muted">程序运行时才能执行计划。错过时刻后，下次启动最多补跑一次，不按离线天数逐天补齐。同日已完成的定时任务不会因重启重复运行。</p>
    <p class="muted">计划与默认范围在本地配置文件中设置。下方选择只用于本次手动任务。</p>
  </section>
</template>
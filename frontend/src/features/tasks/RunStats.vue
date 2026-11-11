<script setup lang="ts">
import type { RunStats } from '@/api/types'

defineProps<{ stats: RunStats | null }>()
</script>

<template>
  <dl v-if="stats" class="run-consumption">
    <div>
      <dt>搜索次数</dt>
      <dd>{{ stats.search_calls }}</dd>
    </div>
    <div>
      <dt>抓取页面</dt>
      <dd>{{ stats.fetch_calls }}</dd>
    </div>
    <div>
      <dt>模型请求</dt>
      <dd>{{ stats.model_requests }}</dd>
    </div>
    <div>
      <dt>输入 token</dt>
      <dd>{{ stats.input_tokens }}</dd>
    </div>
    <div>
      <dt>输出 token</dt>
      <dd>{{ stats.output_tokens }}</dd>
    </div>
    <div>
      <dt>缓存命中 token</dt>
      <dd>{{ stats.cache_read_tokens }}</dd>
    </div>
    <div>
      <dt>推理 token</dt>
      <dd>{{ stats.reasoning_tokens }}</dd>
    </div>
  </dl>
  <p v-else class="muted">本次任务未记录消耗统计；统计功能上线前的任务不显示数字。</p>
</template>

<style scoped>
.run-consumption { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0; margin: 0; border-block-start: 1px solid var(--color-border); }
.run-consumption > div { display: flex; flex-direction: column; gap: 0.4rem; padding: 0.8rem 1rem 0.8rem 0; border-block-end: 1px solid var(--color-border); }
.run-consumption dt { font: 500 0.6875rem/1.5 var(--font-ui); color: var(--color-text-secondary); }
.run-consumption dd { margin: 0; font: 400 1rem/1.5 var(--font-mono); font-variant-numeric: tabular-nums; }
@media (max-width: 480px) { .run-consumption { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
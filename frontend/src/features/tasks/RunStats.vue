<script setup lang="ts">
import type { RunStats } from '@/api/types'

defineProps<{ stats: RunStats | null }>()
</script>

<template>
  <dl v-if="stats" class="stat-grid">
    <div class="stat">
      <dt>搜索次数</dt>
      <dd>{{ stats.search_calls }}</dd>
    </div>
    <div class="stat">
      <dt>抓取页面</dt>
      <dd>{{ stats.fetch_calls }}</dd>
    </div>
    <div class="stat">
      <dt>模型请求</dt>
      <dd>{{ stats.model_requests }}</dd>
    </div>
    <div class="stat">
      <dt>输入 token</dt>
      <dd>{{ stats.input_tokens }}</dd>
    </div>
    <div class="stat">
      <dt>输出 token</dt>
      <dd>{{ stats.output_tokens }}</dd>
    </div>
    <div class="stat">
      <dt>缓存命中 token</dt>
      <dd>{{ stats.cache_read_tokens }}</dd>
    </div>
    <div class="stat">
      <dt>推理 token</dt>
      <dd>{{ stats.reasoning_tokens }}</dd>
    </div>
  </dl>
  <p v-else class="muted">本次任务未记录消耗统计；统计功能上线前的任务不显示数字。</p>
</template>
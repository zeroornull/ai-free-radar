<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  html: string
}>()

const hasContent = computed(() => props.html.trim().length > 0)
</script>

<template>
  <article
    v-if="hasContent"
    class="markdown panel"
    aria-label="Markdown 简报正文"
    v-html="props.html"
  />
  <p v-else class="muted">简报正文为空</p>
</template>
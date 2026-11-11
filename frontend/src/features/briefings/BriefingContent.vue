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
    class="markdown briefing-article"
    aria-label="Markdown 简报正文"
    v-html="props.html"
  />
  <p v-else class="muted briefing-empty">简报正文为空</p>
</template>

<style scoped>
.briefing-article { inline-size: 100%; max-inline-size: 720px; min-inline-size: 0; padding: 0; margin: 0; font: 400 1rem/1.9 var(--font-body); overflow-wrap: anywhere; }
.briefing-article :deep(h1) { font-size: clamp(1.65rem, 3vw, 2.15rem); line-height: 1.35; }
.briefing-article :deep(h2) { margin-block: 2.5rem 1rem; padding-block-start: 1rem; border-block-start: 1px solid var(--color-border); font-size: 1.4rem; line-height: 1.4; }
.briefing-article :deep(h3) { margin-block: 1.75rem 0.75rem; font-size: 1.15rem; }
.briefing-article :deep(p) { margin-block: 1rem; }
.briefing-article :deep(blockquote) { margin-inline: 0; padding: 0.25rem 0 0.25rem 1rem; border: 0; border-inline-start: 1px solid var(--color-text-secondary); border-radius: 0; background: transparent; color: var(--color-text-secondary); font-size: 0.9375rem; }
.briefing-article :deep(th), .briefing-article :deep(td) { padding: 0.65rem; border: 1px solid var(--color-border); background: transparent; font-size: 0.8125rem; }
.briefing-article :deep(th) { font-family: var(--font-ui); font-weight: 600; }
.briefing-article :deep(code), .briefing-article :deep(pre) { border-radius: 0; font-family: var(--font-mono); font-size: 0.8125rem; }
.briefing-article :deep(pre) { background: transparent; border: 1px solid var(--color-border); }
.briefing-empty { max-inline-size: 720px; }
@media (max-width: 480px) { .briefing-article { font-size: 0.9375rem; line-height: 1.85; } }
</style>
<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  value: unknown
  label: string
}>()

const target = computed(() => {
  if (typeof props.value !== 'string' || props.value.length === 0) return null
  for (const character of props.value) {
    const code = character.codePointAt(0)
    if (code !== undefined && code < 33) return null
  }
  if (props.value.includes('\\') || !/^https?:\/\//iu.test(props.value)) return null
  const authority = props.value.replace(/^https?:\/\//iu, '').split(/[/?#]/)[0] ?? ''
  if (!authority || authority.includes('@')) return null
  let parsed: URL
  try {
    parsed = new URL(props.value)
  } catch {
    return null
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
  if (!parsed.hostname) return null
  return props.value
})

const display = computed(() => (typeof props.value === 'string' && props.value ? props.value : '未说明'))
const hint = computed(() =>
  typeof props.value === 'string' && props.value ? '（无可安全打开的 HTTP 链接）' : '',
)
</script>

<template>
  <a v-if="target" :href="target" rel="noreferrer noopener">{{ label }}</a>
  <span v-else>{{ label }}：{{ display }}{{ hint }}</span>
</template>

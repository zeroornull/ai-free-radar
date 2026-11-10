<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  value: string
  label: string
}>()

const tone = computed(() => {
  if (props.value === 'supported') return 'success'
  if (props.value === 'unsupported') return 'danger'
  return 'warning'
})
</script>

<template>
  <span class="chip" :class="`chip--${tone}`">中国大陆：{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  value: string
  label: string
}>()

const tone = computed(() => {
  if (props.value === 'active' || props.value === 'success') return 'success'
  if (props.value === 'pending' || props.value === 'incomplete') return 'warning'
  if (props.value === 'expired' || props.value === 'failed') return 'danger'
  return 'neutral'
})
</script>

<template>
  <span class="badge" :class="`badge--${tone}`">{{ label }}</span>
</template>

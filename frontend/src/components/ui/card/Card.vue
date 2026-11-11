<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = withDefaults(defineProps<{
  class?: HTMLAttributes['class']
  size?: 'default' | 'sm'
}>(), {
  size: 'default',
})
</script>

<template>
  <div
    data-slot="card"
    :data-size="size"
    :class="cn('text-card-foreground gap-6 py-6 text-sm has-[>img:first-child]:pt-0 data-[size=sm]:gap-4 data-[size=sm]:py-4 group/card flex flex-col', props.class)"
  >
    <slot />
  </div>
</template>

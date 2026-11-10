<script setup lang="ts">
defineProps<{
  eyebrow: string
  title: string
}>()
</script>

<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">{{ eyebrow }}</span>
      <h1>{{ title }}</h1>
    </div>
    <div class="chips">
      <span class="local-chip">仅本机使用</span>
      <slot name="actions" />
    </div>
  </div>
</template>

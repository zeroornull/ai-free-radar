<script setup lang="ts">
defineProps<{
  title: string
}>()
</script>

<template>
  <div class="page-heading">
    <div>
      <h1>{{ title }}</h1>
    </div>
    <div v-if="$slots.actions" class="actions">
      <slot name="actions" />
    </div>
  </div>
</template>

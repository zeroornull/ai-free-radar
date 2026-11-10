<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <section class="empty">
    <h2>{{ title }}</h2>
    <p v-if="description">{{ description }}</p>
    <slot name="actions" />
  </section>
</template>

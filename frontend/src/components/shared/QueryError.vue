<script setup lang="ts">
const props = defineProps<{
  message?: string
}>()

const emit = defineEmits<{
  retry: []
}>()

const fallback = '请求失败，请稍后重试。'
</script>

<template>
  <div class="error-message" role="alert">
    <strong>内容暂时无法加载</strong>
    <p>{{ props.message || fallback }}</p>
    <div class="actions">
      <button class="button" type="button" @click="emit('retry')">重试</button>
    </div>
  </div>
</template>

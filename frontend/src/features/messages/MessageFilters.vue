<script setup lang="ts">
import { ref, watch } from 'vue'
import type { AppRead } from '@/api/types'
import type { MessageFilters } from '@/api/queries'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'

const props = defineProps<{
  app?: AppRead
  applied: MessageFilters
  count: number
  error?: string | null
}>()

const emit = defineEmits<{
  apply: [filters: MessageFilters]
  clear: []
}>()

const category = ref(props.applied.category)
const includeEnded = ref(props.applied.include_ended ?? false)

function syncApplied(value: MessageFilters) {
  category.value = value.category
  includeEnded.value = value.include_ended ?? false
}

// URL query is the source of truth. Watch a joined primitive so background app
// polling cannot clobber an unsubmitted draft.
watch(
  () => `${props.applied.category}\u0000${props.applied.include_ended ? '1' : '0'}`,
  () => syncApplied(props.applied),
)

function submit() {
  emit('apply', {
    category: category.value.trim(),
    include_ended: includeEnded.value,
  })
}

function clearFilters() {
  syncApplied({ category: '', include_ended: false })
  emit('clear')
}

function entries(dict?: Record<string, string>) {
  return Object.entries(dict ?? {})
}
</script>

<template>
  <form class="panel filter-form toolbar" aria-label="筛选消息动态" @submit.prevent="submit">
    <div class="toolbar-head">
      <h2 class="toolbar-title">筛选条件</h2>
      <p class="count-chip" role="status" aria-live="polite">共 {{ count }} 条消息</p>
    </div>
    <div class="toolbar-grid">
      <div class="field">
        <Label for="message-category">API 类别</Label>
        <NativeSelect id="message-category" name="category" v-model="category">
          <NativeSelectOption value="">全部类别</NativeSelectOption>
          <NativeSelectOption v-for="[value, text] in entries(app?.categories)" :key="value" :value="value">
            {{ text }}
          </NativeSelectOption>
        </NativeSelect>
      </div>
      <div class="field">
        <span class="field-label">消息范围</span>
        <label class="check-option" for="include-ended">
          <input
            id="include-ended"
            class="scope-checkbox"
            type="checkbox"
            name="include_ended"
            v-model="includeEnded"
          />
          <span>包含已结束消息</span>
        </label>
        <p class="form-note">默认只显示仍有效的消息；开启后显示已结束的历史记录。</p>
      </div>
    </div>
    <Alert v-if="error" variant="destructive" role="alert" class="mt-2">
      <AlertTitle>筛选条件无效</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>
    <div class="actions">
      <Button type="submit">筛选消息</Button>
      <Button type="button" variant="ghost" @click="clearFilters">清除筛选</Button>
    </div>
    <p class="form-note">
      消息来自官方页面、社区或 GitHub、搜索片段，均标注<strong>未核验消息</strong>；未说明的项目按“未说明”保留，不做推测。
    </p>
  </form>
</template>
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
  <form class="filter-form journal-filters" aria-label="筛选消息动态" @submit.prevent="submit">
    <div class="filter-controls">
      <div class="field">
        <Label for="message-category">API 类别</Label>
        <NativeSelect id="message-category" name="category" v-model="category">
          <NativeSelectOption value="">全部类别</NativeSelectOption>
          <NativeSelectOption v-for="[value, text] in entries(app?.categories)" :key="value" :value="value">
            {{ text }}
          </NativeSelectOption>
        </NativeSelect>
      </div>
      <div class="field scope-field">
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
      </div>
      <div class="filter-actions">
        <Button type="submit">筛选消息</Button>
        <Button type="button" variant="ghost" @click="clearFilters">清除筛选</Button>
      </div>
      <p class="filter-count" role="status" aria-live="polite">共 {{ count }} 条消息</p>
    </div>
    <Alert v-if="error" variant="destructive" role="alert" class="mt-2">
      <AlertTitle>筛选条件无效</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>
    <p class="filter-scope-note">默认只显示仍有效的消息；开启后显示已结束的历史记录。</p>
    <p class="form-note">
      消息来自官方页面、社区或 GitHub、搜索片段，均标注<strong>未核验消息</strong>；未说明的项目按“未说明”保留，不做推测。
    </p>
  </form>
</template>

<style scoped>
.journal-filters { padding-block: 0.75rem; margin-block-end: 0; border-block: 1px solid var(--color-border); }
.filter-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 0.65rem 1.25rem; }
.journal-filters .field { display: flex; flex-direction: row; align-items: center; gap: 0.5rem; margin: 0; }
.journal-filters .field > label, .check-option { font: 500 0.75rem/1.5 var(--font-ui); }
.journal-filters select { min-inline-size: 8rem; min-block-size: 2rem; }
.journal-filters .check-option { display: flex; align-items: center; gap: 0.5rem; margin: 0; }
.scope-checkbox { inline-size: 1rem; block-size: 1rem; accent-color: #8c2f39; }
.filter-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.filter-count { margin: 0; margin-inline-start: auto; color: var(--color-text-secondary); font: 400 0.75rem/1.5 var(--font-ui); }
.filter-scope-note, .journal-filters .form-note { margin-block: 0.5rem 0; color: var(--color-text-secondary); font: 400 0.75rem/1.6 var(--font-ui); }
@media (max-width: 599px) {
  .filter-controls { align-items: flex-start; gap: 0.75rem; }
  .journal-filters .scope-field { inline-size: 100%; }
  .filter-count { align-self: center; }
}
</style>
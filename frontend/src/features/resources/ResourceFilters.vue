<script setup lang="ts">
import { ref, watch } from 'vue'
import type { AppRead } from '@/api/types'
import type { ResourceFilters } from '@/api/queries'
import { policyStatusLabel } from '@/app/presentation'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'

const props = defineProps<{
  app?: AppRead
  applied: ResourceFilters
  count: number
  error?: string | null
}>()

const emit = defineEmits<{
  apply: [filters: ResourceFilters]
  clear: []
}>()

const category = ref(props.applied.category)
const chinaPolicy = ref(props.applied.china_policy)
const status = ref(props.applied.status)
const includeEnded = ref(props.applied.include_ended ?? false)

function syncApplied(value: ResourceFilters) {
  category.value = value.category
  chinaPolicy.value = value.china_policy
  status.value = value.status
  includeEnded.value = value.include_ended ?? false
}

// URL query is the source of truth: back/forward or programmatic navigation
// resyncs the draft controls; editing the draft does not fire any request.
// Watch a joined primitive string so background app polling (which recomputes
// `applied` with a new object identity but the same values) cannot clobber an
// unsubmitted draft.
watch(
  () =>
    `${props.applied.category}\u0000${props.applied.china_policy}\u0000${props.applied.status}\u0000${props.applied.include_ended ? '1' : '0'}`,
  () => syncApplied(props.applied),
)

function submit() {
  emit('apply', {
    category: category.value.trim(),
    china_policy: chinaPolicy.value.trim(),
    status: status.value.trim(),
    include_ended: includeEnded.value,
  })
}

function clearFilters() {
  syncApplied({ category: '', china_policy: '', status: '', include_ended: false })
  emit('clear')
}

function entries(dict?: Record<string, string>) {
  return Object.entries(dict ?? {})
}
</script>

<template>
  <form class="panel filter-form toolbar" aria-label="筛选资源库" @submit.prevent="submit">
    <div class="toolbar-head">
      <h2 class="toolbar-title">筛选条件</h2>
      <p class="count-chip" role="status" aria-live="polite">共 {{ count }} 项资源</p>
    </div>
    <div class="toolbar-grid">
      <div class="field">
        <Label for="category">API 类别</Label>
        <NativeSelect id="category" name="category" v-model="category">
          <NativeSelectOption value="">全部类别</NativeSelectOption>
          <NativeSelectOption v-for="[value, text] in entries(app?.categories)" :key="value" :value="value">
            {{ text }}
          </NativeSelectOption>
        </NativeSelect>
      </div>
      <div class="field">
        <Label for="china_policy">中国大陆政策</Label>
        <NativeSelect id="china_policy" name="china_policy" v-model="chinaPolicy">
          <NativeSelectOption value="">全部政策</NativeSelectOption>
          <NativeSelectOption v-for="[value, text] in entries(app?.china_policies)" :key="value" :value="value">
            {{ text }}
          </NativeSelectOption>
        </NativeSelect>
      </div>
      <div class="field">
        <Label for="resource-status">政策核验状态</Label>
        <NativeSelect id="resource-status" name="status" v-model="status">
          <NativeSelectOption value="">全部政策状态</NativeSelectOption>
          <NativeSelectOption v-for="[value] in entries(app?.resource_statuses)" :key="value" :value="value">
            {{ policyStatusLabel(value) }}
          </NativeSelectOption>
        </NativeSelect>
      </div>
    </div>
    <div class="field checkbox-row">
      <Label for="include-ended" class="check-option">
        <input id="include-ended" v-model="includeEnded" type="checkbox" name="include_ended" />
        显示全部活动（含已结束）
      </Label>
      <p class="form-note">默认只显示尚未结束的活动；条件未说明的消息仍会展示。</p>
    </div>
    <Alert v-if="error" variant="destructive" role="alert" class="mt-2">
      <AlertTitle>筛选条件无效</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>
    <div class="actions">
      <Button type="submit">筛选资源</Button>
      <Button type="button" variant="ghost" @click="clearFilters">清除筛选</Button>
    </div>
    <p class="form-note">筛选仅改变当前显示，不修改收集范围或每日默认配置。</p>
  </form>
</template>
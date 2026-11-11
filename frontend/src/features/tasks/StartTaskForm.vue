<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { AppRead, CreateTaskRequest, RunRead, Scope, TaskDetailRead } from '@/api/types'
import { useStartTaskMutation } from '@/api/queries'
import { labelFor } from '@/app/presentation'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'

type CategoryValue = NonNullable<Scope['categories']>[number]
type RegionValue = Scope['region']

const props = defineProps<{ app: AppRead }>()

const router = useRouter()
const {
  mutateAsync,
  isPending,
  error: mutationError,
  reset,
} = useStartTaskMutation()

// 仅在首次挂载时从默认范围深拷贝一次；轮询更新 app 时保留用户草稿。
const draft = reactive<{ categories: CategoryValue[]; region: RegionValue }>({
  categories: [...(props.app.default_scope.categories ?? [])],
  region: props.app.default_scope.region,
})
const verifyIdsDraft = ref('')

const fieldsetRef = ref<HTMLElement | null>(null)
const formError = ref('')

const categoryOptions = computed(() =>
  Object.entries(props.app.categories).map(([value, text]) => [value as CategoryValue, text] as const),
)

const orderedCategories = computed(() => {
  const order = Object.keys(props.app.categories)
  return [...draft.categories].sort((a, b) => order.indexOf(a) - order.indexOf(b))
})

const verifyIds = computed(() => {
  const seen = new Set<string>()
  for (const raw of verifyIdsDraft.value.split(/[\s,，;；]+/)) {
    const value = raw.trim()
    if (value) seen.add(value)
  }
  return Array.from(seen)
})

const pending = computed(() => isPending.value)
const activeRun = computed(() => props.app.active_run)
const submitDisabled = computed(() => pending.value || activeRun.value !== null)

const disabledReason = computed(() => {
  if (pending.value) return '正在提交任务，请稍候。'
  if (activeRun.value) return '已有任务运行中，完成后再发起下一项任务。'
  return ''
})

const serverError = computed(() => mutationError.value?.message ?? '')
const displayError = computed(() => formError.value || serverError.value)
const describedBy = computed(() =>
  displayError.value ? 'scope-help verify-help task-error' : 'scope-help verify-help',
)

function clearErrors(): void {
  if (formError.value) formError.value = ''
  if (mutationError.value) reset()
}

function setCategory(value: CategoryValue, checked: boolean | 'indeterminate'): void {
  if (checked === true) {
    if (!draft.categories.includes(value)) draft.categories.push(value)
  } else if (checked === false) {
    draft.categories = draft.categories.filter((item) => item !== value)
  }
  clearErrors()
}

function onRegionChange(event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLSelectElement)) return
  const value = target.value
  if (value === 'global' || value === 'china') {
    draft.region = value
    clearErrors()
  }
}

function extractRunId(created: unknown): string | null {
  if (created && typeof created === 'object') {
    if ('run' in created) {
      const detail = created as TaskDetailRead
      if (typeof detail.run?.id === 'string') return detail.run.id
    }
    if ('id' in created) {
      const run = created as RunRead
      if (typeof run.id === 'string') return run.id
    }
  }
  return null
}

async function submit(): Promise<void> {
  if (draft.categories.length === 0) {
    formError.value = '请选择至少一个 API 类别。'
    fieldsetRef.value?.focus()
    return
  }
  formError.value = ''
  const payload: CreateTaskRequest = {
    categories: orderedCategories.value,
    region: draft.region,
  }
  if (verifyIds.value.length) payload.resource_ids = verifyIds.value
  try {
    const created: unknown = await mutateAsync(payload)
    const runId = extractRunId(created)
    if (runId) await router.push(`/tasks/${runId}`)
  } catch {
    // 失败原因由 mutationError 呈现；草稿保持不变。
  }
}
</script>

<template>
  <section class="panel task-form" aria-labelledby="start-task">
    <h2 id="start-task">发起收集任务</h2>
    <p id="scope-help" class="scope-help">
      默认按类别收集新的免费消息与更新，并保留来源链接，不自动核验已有资源。
      如需严格核验，请在下方填写资源标识；填写后本次只核验这些资源。
      任务不注册账号、不领取权益、不调用候选 API。
    </p>
    <div v-if="displayError" id="task-error" class="error-message" role="alert">
      <strong>任务未发起</strong>
      <p>{{ displayError }}</p>
    </div>
    <form class="task-fields" novalidate @submit.prevent="submit">
      <fieldset
        ref="fieldsetRef"
        class="scope-fieldset"
        tabindex="-1"
        :aria-describedby="describedBy"
      >
        <legend class="scope-legend">本次 API 类别</legend>
        <div class="checkbox-grid">
          <Label
            v-for="[value, text] in categoryOptions"
            :key="value"
            class="check-option"
            :for="`task-category-${value}`"
          >
            <Checkbox
              :id="`task-category-${value}`"
              :model-value="draft.categories.includes(value)"
              @update:model-value="(checked) => setCategory(value, checked)"
            />
            {{ text }}
          </Label>
        </div>
      </fieldset>
      <div class="field" @change="onRegionChange">
        <Label for="region">本次地区条件</Label>
        <NativeSelect
          id="region"
          class="[&>select]:h-11"
          :model-value="draft.region"
          aria-describedby="region-help"
        >
          <NativeSelectOption value="global">{{ labelFor(app, 'global') }}</NativeSelectOption>
          <NativeSelectOption value="china">{{ labelFor(app, 'china') }}</NativeSelectOption>
        </NativeSelect>
        <p id="region-help" class="form-note">
          中国大陆条件只按来源描述收集，并标注政策依据；不等于网络连通测试。依据不明的资源保留为未核验。
        </p>
      </div>
      <div class="field">
        <Label for="verify-ids">按需核验的资源标识（可选）</Label>
        <textarea
          id="verify-ids"
          v-model="verifyIdsDraft"
          name="resource_ids"
          class="verify-ids-input"
          rows="2"
          aria-describedby="verify-help"
          placeholder="例如：res_abc123, res_def456"
        />
        <p id="verify-help" class="form-note">
          留空则只收集消息，不自动核验已有资源。填写后本次仅对这些资源执行严格政策核验，且不会发现其他资源。
        </p>
      </div>
      <p class="sr-only" role="status" aria-live="polite">{{ disabledReason }}</p>
      <Button type="submit" class="h-11" :disabled="submitDisabled">
        {{ pending ? '正在提交…' : verifyIds.length ? '发起按需核验' : '发起本次收集' }}
      </Button>
      <p v-if="disabledReason" class="form-note">{{ disabledReason }}</p>
    </form>
  </section>
</template>

<style scoped>
.verify-ids-input {
  font: 400 0.8125rem/1.55 var(--font-mono);
  inline-size: 100%;
  min-block-size: 2.75rem;
  padding: 0.5rem 0.7rem;
  border: 1px solid var(--color-control-border);
  border-radius: 0;
  color: var(--color-text);
  background-color: var(--color-bg-surface);
  resize: vertical;
}
.task-form { min-inline-size: 0; margin: 0; }
.scope-help { max-inline-size: 65ch; color: var(--color-text-secondary); font-size: 0.875rem; line-height: 1.75; }
.task-fields { margin-block-start: 1.5rem; }
.task-fields :deep(label), .scope-legend { font-family: var(--font-ui); font-size: 0.8125rem; }
.task-fields .field { margin-block-end: 1.25rem; }
.task-fields .form-note { font-size: 0.75rem; line-height: 1.65; }
</style>
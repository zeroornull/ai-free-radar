<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  useAppQuery,
  useSaveSettingsMutation,
  useSettingsQuery,
  useTestSettingsMutation,
} from '@/api/queries'
import type { SettingsRead } from '@/api/types'
import { labelFor } from '@/app/presentation'
import PageHeading from '@/components/shared/PageHeading.vue'
import QueryError from '@/components/shared/QueryError.vue'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'

type Region = 'global' | 'china'
type SecretKey = 'model_api_key' | 'search_api_key'
type TestTarget = 'model' | 'search'

interface ScopeDraft {
  categories: string[]
  region: Region
}

interface Draft {
  model: string
  model_base_url: string
  model_api_key_env: string
  search_provider: string
  search_api_key_env: string
  schedule_enabled: boolean
  schedule_time: string
  default_scope: ScopeDraft
}

type DraftKey = Exclude<keyof Draft, 'default_scope'> | 'default_scope'

interface ReadField {
  value?: unknown
  configured?: boolean
  source?: string
}

const SOURCE_LABELS: Record<string, string> = {
  db: '设置页',
  toml: 'config.toml',
  default: '默认',
  env: '环境变量',
  missing: '未配置',
  read_only: '只读',
}

const PROVIDER_OPTIONS = ['duckduckgo', 'tavily', 'brave', 'exa'] as const

const {
  data: settings,
  isPending: settingsPending,
  isError: settingsFailed,
  error: settingsError,
  refetch: refetchSettings,
} = useSettingsQuery()

const {
  data: app,
  isError: appFailed,
  error: appError,
  refetch: refetchApp,
} = useAppQuery()

const saveMutation = useSaveSettingsMutation()
const testMutation = useTestSettingsMutation()

const fields = computed<Record<string, ReadField>>(
  () => (settings.value?.fields ?? {}) as unknown as Record<string, ReadField>,
)

const categoryOptions = computed<[string, string][]>(() =>
  Object.entries(app.value?.categories ?? {}),
)

function categoryOrder(): string[] {
  return Object.keys(app.value?.categories ?? {})
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function normalizeCategories(value: unknown): string[] {
  const input = Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
  const order = categoryOrder()
  const rank = (item: string): number => {
    const index = order.indexOf(item)
    return index === -1 ? order.length : index
  }
  return [...new Set(input)].sort((a, b) => rank(a) - rank(b))
}

function normalizeScope(value: unknown): ScopeDraft {
  const scope = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>
  return {
    categories: normalizeCategories(scope.categories),
    region: scope.region === 'china' ? 'china' : 'global',
  }
}

function emptyDraft(): Draft {
  return {
    model: '',
    model_base_url: '',
    model_api_key_env: '',
    search_provider: 'duckduckgo',
    search_api_key_env: '',
    schedule_enabled: false,
    schedule_time: '',
    default_scope: { categories: [], region: 'global' },
  }
}

function cloneDraft(draft: Draft): Draft {
  return {
    ...draft,
    default_scope: {
      categories: [...draft.default_scope.categories],
      region: draft.default_scope.region,
    },
  }
}

function baselineFrom(read: SettingsRead | undefined): Draft {
  const source = ((read?.fields ?? {}) as unknown as Record<string, ReadField>) ?? {}
  const get = (key: string): unknown => source[key]?.value
  const provider = asString(get('search_provider'))
  return {
    model: asString(get('model')),
    model_base_url: asString(get('model_base_url')),
    model_api_key_env: asString(get('model_api_key_env')),
    search_provider: (PROVIDER_OPTIONS as readonly string[]).includes(provider)
      ? provider
      : 'duckduckgo',
    search_api_key_env: asString(get('search_api_key_env')),
    schedule_enabled: get('schedule_enabled') === true,
    schedule_time: asString(get('schedule_time')),
    default_scope: normalizeScope(get('default_scope')),
  }
}

const draft = reactive<Draft>(emptyDraft())
const baseline = ref<Draft>(emptyDraft())
const secretDraft = reactive<Record<SecretKey, string>>({
  model_api_key: '',
  search_api_key: '',
})
const clearedSecrets = ref<Set<SecretKey>>(new Set())
let hasLoaded = false

const field = (key: string): ReadField => fields.value[key] ?? {}

function sourceLabel(source?: string): string {
  return SOURCE_LABELS[source ?? ''] ?? source ?? ''
}

function sourceVariant(source?: string): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (source === 'db') return 'default'
  if (source === 'toml' || source === 'env') return 'secondary'
  if (source === 'missing') return 'destructive'
  return 'outline'
}

function secretPlaceholder(key: SecretKey): string {
  const f = field(key)
  if (f.configured) return `已配置（来源：${sourceLabel(f.source)}），留空保持不变`
  return '未配置，留空保持不变'
}

function scopeKey(scope: ScopeDraft): string {
  return JSON.stringify({ categories: normalizeCategories(scope.categories), region: scope.region })
}

const dirtyKeys = computed<DraftKey[]>(() => {
  const base = baseline.value
  const keys = Object.keys(draft) as DraftKey[]
  return keys.filter((key) => {
    if (key === 'default_scope') return scopeKey(draft.default_scope) !== scopeKey(base.default_scope)
    return draft[key] !== base[key]
  })
})

const secretDirty = computed(
  () =>
    secretDraft.model_api_key !== '' ||
    secretDraft.search_api_key !== '' ||
    clearedSecrets.value.size > 0,
)

const dirty = computed(() => dirtyKeys.value.length > 0 || secretDirty.value)

const savePending = computed(() => saveMutation.isPending.value)
const testTarget = ref<TestTarget | null>(null)
const testPending = computed(() => testTarget.value !== null)

const saveError = ref('')
const saveNotice = ref('')

const testStates = reactive<Record<TestTarget, { kind: 'idle' | 'ok' | 'fail'; detail: string }>>({
  model: { kind: 'idle', detail: '' },
  search: { kind: 'idle', detail: '' },
})

const settingsErrorMessage = computed(() => settingsError.value?.message ?? '请求失败，请稍后重试。')

const READ_ONLY_LABELS: Record<string, string> = {
  host: '监听地址',
  port: '端口',
  data_dir: '数据目录',
}

const readOnlyFields = computed(() => {
  return ['host', 'port', 'data_dir'].map((key) => ({
    key,
    label: READ_ONLY_LABELS[key] ?? key,
    text: displayValue(field(key).value),
  }))
})

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}

watch(
  settings,
  (read) => {
    const first = !hasLoaded
    hasLoaded = true
    const next = baselineFrom(read)
    const keepDraft = !first && dirty.value
    baseline.value = next
    if (!keepDraft) {
      Object.assign(draft, cloneDraft(next))
      secretDraft.model_api_key = ''
      secretDraft.search_api_key = ''
      clearedSecrets.value = new Set()
    }
  },
  { immediate: true },
)

// 首屏加载完成或保存成功后，把服务器返回设置为基线。
function applyServerSettings(read: SettingsRead | undefined): void {
  const next = baselineFrom(read)
  baseline.value = next
  Object.assign(draft, cloneDraft(next))
  secretDraft.model_api_key = ''
  secretDraft.search_api_key = ''
  clearedSecrets.value = new Set()
}

function buildPatch(): {
  version: number
  values: Record<string, unknown>
  secrets: Record<string, string | null>
} {
  const values: Record<string, unknown> = {}
  for (const key of dirtyKeys.value) {
    if (key === 'default_scope') {
      values[key] = { categories: [...draft.default_scope.categories], region: draft.default_scope.region }
    } else {
      values[key] = draft[key]
    }
  }
  const secrets: Record<string, string | null> = {}
  if (secretDraft.model_api_key !== '') secrets.model_api_key = secretDraft.model_api_key
  else if (clearedSecrets.value.has('model_api_key')) secrets.model_api_key = null
  if (secretDraft.search_api_key !== '') secrets.search_api_key = secretDraft.search_api_key
  else if (clearedSecrets.value.has('search_api_key')) secrets.search_api_key = null
  return { version: settings.value?.version ?? 0, values, secrets }
}

async function submit(): Promise<void> {
  if (!settings.value || !dirty.value || savePending.value) return
  saveError.value = ''
  saveNotice.value = ''
  try {
    const result = await saveMutation.mutateAsync(buildPatch())
    applyServerSettings(result)
    saveNotice.value = '已生效'
  } catch (error) {
    const message = error instanceof ApiError ? error.message : '保存失败，请稍后重试。'
    saveError.value = error instanceof ApiError && error.status === 409 ? `版本冲突：${message}` : message
    if (error instanceof ApiError && error.status === 409) {
      void refetchSettings()
    }
  }
}

async function runTest(target: TestTarget): Promise<void> {
  if (testPending.value) return
  testTarget.value = target
  testStates[target] = { kind: 'idle', detail: '' }
  try {
    const result = await testMutation.mutateAsync({ target })
    testStates[target] = {
      kind: result.ok ? 'ok' : 'fail',
      detail: result.detail || (result.ok ? '测试通过' : '测试未通过'),
    }
  } catch (error) {
    testStates[target] = {
      kind: 'fail',
      detail: error instanceof ApiError ? error.message : '测试失败，请稍后重试。',
    }
  } finally {
    testTarget.value = null
  }
}

function setSecret(key: SecretKey, value: string): void {
  secretDraft[key] = value
  if (value !== '') {
    const next = new Set(clearedSecrets.value)
    next.delete(key)
    clearedSecrets.value = next
  }
}

function onSecretInput(key: SecretKey, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  setSecret(key, target.value)
}

function clearSecret(key: SecretKey): void {
  secretDraft[key] = ''
  const next = new Set(clearedSecrets.value)
  next.add(key)
  clearedSecrets.value = next
}

function toggleCategory(value: string, checked: boolean | 'indeterminate'): void {
  const categories = draft.default_scope.categories
  if (checked === true) {
    if (!categories.includes(value)) categories.push(value)
  } else if (checked === false) {
    const index = categories.indexOf(value)
    if (index !== -1) categories.splice(index, 1)
  }
}

function setRegion(value: string): void {
  if (value === 'global' || value === 'china') draft.default_scope.region = value
}

function regionLabel(value: Region, fallback: string): string {
  return app.value ? labelFor(app.value, value) : fallback
}

function beforeUnloadHandler(event: BeforeUnloadEvent): void {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => {
  window.addEventListener('beforeunload', beforeUnloadHandler)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnloadHandler)
})

onBeforeRouteLeave((): boolean => {
  if (!dirty.value) return true
  return window.confirm('有未保存的设置更改，确定离开吗？')
})

const errorMessage = computed(() => appError.value?.message ?? '请求失败，请稍后重试。')
</script>

<template>
  <PageHeading title="设置" />

  <Skeleton v-if="settingsPending && !settings" class="mb-4 h-64 w-full" />
  <QueryError
    v-else-if="settingsFailed && !settings"
    :message="settingsErrorMessage"
    @retry="refetchSettings()"
  />

  <template v-else>
    <p class="muted" role="status" aria-live="polite">
      设置立即生效；模型与搜索密钥仅保存在本机数据库，永不回显。
    </p>

    <Alert v-if="saveError" variant="destructive">
      <AlertTitle>保存失败</AlertTitle>
      <AlertDescription>{{ saveError }}</AlertDescription>
    </Alert>
    <p v-if="saveNotice" class="test-ok" role="status" aria-live="polite">{{ saveNotice }}</p>

    <Card class="settings-section" role="region" aria-labelledby="model-settings-heading">
      <CardHeader>
        <CardTitle id="model-settings-heading" role="heading" aria-level="2">模型</CardTitle>
        <CardDescription>用于运行研究的模型提供商与接口凭证。</CardDescription>
      </CardHeader>
      <CardContent class="settings-fields grid gap-4">
        <div class="grid gap-1">
          <Label for="setting-model">模型</Label>
          <input
            id="setting-model"
            v-model="draft.model"
            class="text-input control"
            type="text"
            autocomplete="off"
          >
          <Badge :variant="sourceVariant(field('model').source)">
            {{ sourceLabel(field('model').source) }}
          </Badge>
        </div>

        <div class="grid gap-1">
          <Label for="setting-model-base-url">模型接口地址</Label>
          <input
            id="setting-model-base-url"
            v-model="draft.model_base_url"
            class="text-input control"
            type="text"
            autocomplete="off"
          >
          <Badge :variant="sourceVariant(field('model_base_url').source)">
            {{ sourceLabel(field('model_base_url').source) }}
          </Badge>
        </div>

        <div class="grid gap-1">
          <Label for="setting-model-api-key-env">模型密钥环境变量名</Label>
          <input
            id="setting-model-api-key-env"
            v-model="draft.model_api_key_env"
            class="text-input control"
            type="text"
            autocomplete="off"
          >
          <Badge :variant="sourceVariant(field('model_api_key_env').source)">
            {{ sourceLabel(field('model_api_key_env').source) }}
          </Badge>
        </div>

        <div class="grid gap-1">
          <Label for="setting-model-api-key">模型密钥</Label>
          <div class="flex items-start gap-2">
            <input
              id="setting-model-api-key"
              class="text-input control flex-1"
              type="password"
              :placeholder="secretPlaceholder('model_api_key')"
              :value="secretDraft.model_api_key"
              autocomplete="new-password"
              @input="onSecretInput('model_api_key', $event)"
            >
            <Button
              type="button"
              variant="outline"
              class="h-9"
              :disabled="secretDraft.model_api_key === '' && !field('model_api_key').configured"
              @click="clearSecret('model_api_key')"
            >
              清除
            </Button>
          </div>
          <div class="flex items-center gap-2">
            <Badge :variant="sourceVariant(field('model_api_key').source)">
              {{ sourceLabel(field('model_api_key').source) }}
            </Badge>
            <span v-if="field('model_api_key').configured" class="muted">已配置</span>
          </div>
        </div>

        <div class="settings-test flex items-center gap-2">
          <Button type="button" variant="outline" :disabled="testPending" @click="runTest('model')">
            {{ testTarget === 'model' ? '测试中…' : '测试连接' }}
          </Button>
          <p
            v-if="testStates.model.kind !== 'idle'"
            class="muted"
            role="status"
            aria-live="polite"
            :class="testStates.model.kind === 'ok' ? 'test-ok' : 'test-fail'"
          >
            {{ testStates.model.detail }}
          </p>
        </div>
      </CardContent>
    </Card>

    <Card class="settings-section" role="region" aria-labelledby="search-settings-heading">
      <CardHeader>
        <CardTitle id="search-settings-heading" role="heading" aria-level="2">搜索</CardTitle>
        <CardDescription>用于资料检索的搜索提供商与接口凭证。</CardDescription>
      </CardHeader>
      <CardContent class="settings-fields grid gap-4">
        <div class="grid gap-1">
          <Label for="setting-search-provider">搜索提供商</Label>
          <NativeSelect
            id="setting-search-provider"
            class="w-full [&>select]:h-11"
            :model-value="draft.search_provider"
            @update:model-value="draft.search_provider = String($event)"
          >
            <NativeSelectOption v-for="provider in PROVIDER_OPTIONS" :key="provider" :value="provider">
              {{ provider }}
            </NativeSelectOption>
          </NativeSelect>
          <Badge :variant="sourceVariant(field('search_provider').source)">
            {{ sourceLabel(field('search_provider').source) }}
          </Badge>
        </div>

        <div class="grid gap-1">
          <Label for="setting-search-api-key-env">搜索密钥环境变量名</Label>
          <input
            id="setting-search-api-key-env"
            v-model="draft.search_api_key_env"
            class="text-input control"
            type="text"
            autocomplete="off"
          >
          <Badge :variant="sourceVariant(field('search_api_key_env').source)">
            {{ sourceLabel(field('search_api_key_env').source) }}
          </Badge>
        </div>

        <div class="grid gap-1">
          <Label for="setting-search-api-key">搜索密钥</Label>
          <div class="flex items-start gap-2">
            <input
              id="setting-search-api-key"
              class="text-input control flex-1"
              type="password"
              :placeholder="secretPlaceholder('search_api_key')"
              :value="secretDraft.search_api_key"
              autocomplete="new-password"
              @input="onSecretInput('search_api_key', $event)"
            >
            <Button
              type="button"
              variant="outline"
              class="h-9"
              :disabled="secretDraft.search_api_key === '' && !field('search_api_key').configured"
              @click="clearSecret('search_api_key')"
            >
              清除
            </Button>
          </div>
          <div class="flex items-center gap-2">
            <Badge :variant="sourceVariant(field('search_api_key').source)">
              {{ sourceLabel(field('search_api_key').source) }}
            </Badge>
            <span v-if="field('search_api_key').configured" class="muted">已配置</span>
          </div>
        </div>

        <div class="settings-test flex items-center gap-2">
          <Button type="button" variant="outline" :disabled="testPending" @click="runTest('search')">
            {{ testTarget === 'search' ? '测试中…' : '测试连接' }}
          </Button>
          <p
            v-if="testStates.search.kind !== 'idle'"
            class="muted"
            role="status"
            aria-live="polite"
            :class="testStates.search.kind === 'ok' ? 'test-ok' : 'test-fail'"
          >
            {{ testStates.search.detail }}
          </p>
        </div>
      </CardContent>
    </Card>

    <Card class="settings-section" role="region" aria-labelledby="schedule-settings-heading">
      <CardHeader>
        <CardTitle id="schedule-settings-heading" role="heading" aria-level="2">定时</CardTitle>
        <CardDescription>每日自动研究的时间安排。</CardDescription>
      </CardHeader>
      <CardContent class="settings-fields settings-fields--single grid gap-4">
        <div class="flex items-center gap-2">
          <Label for="setting-schedule-enabled">启用每日定时研究</Label>
          <Checkbox
            id="setting-schedule-enabled"
            :model-value="draft.schedule_enabled"
            @update:model-value="draft.schedule_enabled = $event === true"
          />
          <Badge :variant="sourceVariant(field('schedule_enabled').source)">
            {{ sourceLabel(field('schedule_enabled').source) }}
          </Badge>
        </div>
        <div class="grid gap-1">
          <Label for="setting-schedule-time">研究时间</Label>
          <input
            id="setting-schedule-time"
            v-model="draft.schedule_time"
            class="text-input control control--time"
            type="time"
          >
          <Badge :variant="sourceVariant(field('schedule_time').source)">
            {{ sourceLabel(field('schedule_time').source) }}
          </Badge>
        </div>
      </CardContent>
    </Card>

    <Card class="settings-section" role="region" aria-labelledby="scope-settings-heading">
      <CardHeader>
        <CardTitle id="scope-settings-heading" role="heading" aria-level="2">默认范围</CardTitle>
        <CardDescription>发起研究时的默认 API 类别与地区条件。</CardDescription>
      </CardHeader>
      <CardContent class="settings-fields settings-fields--single grid gap-4">
        <fieldset v-if="app" class="scope-fieldset">
          <legend class="scope-legend">默认 API 类别</legend>
          <div class="checkbox-grid">
            <Label
              v-for="[value, text] in categoryOptions"
              :key="value"
              class="check-option"
              :for="`setting-category-${value}`"
            >
              <Checkbox
                :id="`setting-category-${value}`"
                :model-value="draft.default_scope.categories.includes(value)"
                @update:model-value="toggleCategory(value, $event)"
              />
              {{ text }}
            </Label>
          </div>
        </fieldset>
        <QueryError v-else-if="appFailed" :message="errorMessage" @retry="refetchApp()" />
        <Skeleton v-else class="h-24 w-full" />
        <Badge :variant="sourceVariant(field('default_scope').source)">
          {{ sourceLabel(field('default_scope').source) }}
        </Badge>
        <div class="mt-2 flex items-center gap-2">
          <Label for="setting-region">默认地区</Label>
          <NativeSelect
            id="setting-region"
            class="block w-full [&>select]:h-11"
            :model-value="draft.default_scope.region"
            @update:model-value="setRegion(String($event))"
          >
            <NativeSelectOption value="global">{{ regionLabel('global', '全球') }}</NativeSelectOption>
            <NativeSelectOption value="china">{{ regionLabel('china', '中国大陆') }}</NativeSelectOption>
          </NativeSelect>
        </div>
      </CardContent>
    </Card>

    <Card class="settings-section" role="region" aria-labelledby="service-settings-heading">
      <CardHeader>
        <CardTitle id="service-settings-heading" role="heading" aria-level="2">服务设置（只读）</CardTitle>
        <CardDescription>监听地址与数据目录在启动时确定，此处不可修改。</CardDescription>
      </CardHeader>
      <CardContent>
        <dl class="facts">
          <template v-for="item in readOnlyFields" :key="item.key">
            <dt>{{ item.label }}</dt>
            <dd class="flex items-center gap-2">
              {{ item.text }}
              <Badge variant="outline">{{ sourceLabel('read_only') }}</Badge>
            </dd>
          </template>
        </dl>
      </CardContent>
    </Card>

    <div class="settings-actions">
      <Button type="button" :disabled="!dirty || savePending" @click="submit()">
        {{ savePending ? '保存中…' : '保存设置' }}
      </Button>
      <span v-if="dirty" class="muted" role="status" aria-live="polite">有未保存的更改</span>
      <span v-else class="muted">所有更改已生效</span>
    </div>
  </template>
</template>

<style scoped>
.control {
  inline-size: 100%;
  min-block-size: 2.75rem;
  padding: 0.45rem 0.7rem;
  border: 1px solid var(--color-control-border);
  border-radius: 0;
  color: var(--color-text);
  background-color: var(--color-bg-surface);
}
.control--time {
  max-inline-size: 14rem;
}
.settings-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1.25rem;
  margin-block: 1.5rem 0;
  padding-block: 1.25rem;
  border-block-start: 1px solid var(--color-text);
  font: 400 0.8125rem/1.6 var(--font-ui);
}
.test-ok {
  color: var(--color-success);
}
.test-fail {
  color: var(--color-error);
}
.settings-section {
  display: grid;
  grid-template-columns: minmax(12rem, 0.6fr) minmax(0, 2fr);
  align-items: start;
  column-gap: 2.5rem;
  row-gap: 1rem;
  margin-block: 1.75rem 0;
  padding-block: 1.25rem 0;
  overflow: visible;
  border: 0;
  border-block-start: 1px solid var(--color-border);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  color: var(--color-text);
}
.settings-section :deep([data-slot="card-header"]),
.settings-section :deep([data-slot="card-content"]) { min-inline-size: 0; padding: 0; border-radius: 0; }
.settings-section :deep([data-slot="card-title"]) { font: 600 1.25rem/1.4 var(--font-body); }
.settings-section :deep([data-slot="card-description"]) { max-inline-size: 32ch; margin-block-start: 0.5rem; font: 400 0.8125rem/1.75 var(--font-body); color: var(--color-text-secondary); }
.settings-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.25rem 1.5rem; }
.settings-fields--single { grid-template-columns: minmax(0, 1fr); }
.settings-fields > div { min-inline-size: 0; }
.settings-fields :deep(label), .settings-fields .scope-legend { font: 500 0.8125rem/1.5 var(--font-ui); }
.settings-fields :deep([data-slot="badge"]) { justify-self: start; inline-size: fit-content; margin-block-start: 0.2rem; }
.settings-fields .control { min-inline-size: 0; font: 400 0.875rem/1.5 var(--font-ui); }
.settings-fields--single > .flex, .settings-test { flex-wrap: wrap; }
.settings-test { grid-column: 1 / -1; align-items: baseline; padding-block-start: 0.75rem; border-block-start: 1px solid var(--color-border); }
.settings-test > p { flex: 1 1 15rem; margin: 0; font: 400 0.75rem/1.65 var(--font-ui); }
.settings-section :deep(.facts dd) { overflow-wrap: anywhere; flex-wrap: wrap; }
@media (max-width: 1099px) {
  .settings-section { grid-template-columns: minmax(0, 1fr); gap: 1.25rem; }
  .settings-section :deep([data-slot="card-description"]) { max-inline-size: 65ch; }
}
@media (max-width: 600px) {
  .settings-fields { grid-template-columns: minmax(0, 1fr); }
  .settings-fields--single > .flex { align-items: center; }
}
</style>
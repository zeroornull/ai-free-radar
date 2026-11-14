import { computed, onScopeDispose, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { request } from './client'
import { autoRefreshEnabled } from '@/app/refresh'
import type {
  AppRead,
  BriefingRead,
  CreateTaskRequest,
  LeadRead,
  NewsItem,
  Resource,
  ResourceDetailRead,
  ResourceReview,
  ReviewAction,
  ReviewRead,
  RunRead,
  SettingsPatchRequest,
  SettingsRead,
  SettingsResetRequest,
  SettingsTestRead,
  SettingsTestRequest,
  SourceDefinition,
  SourceEntry,
  SourceRead,
  SourceSnapshot,
  TaskDetailRead,
} from './types'

export interface ResourceFilters {
  category: string
  china_policy: string
  status: string
  include_ended?: boolean
}

export interface MessageFilters {
  category: string
  include_ended?: boolean
}

const IDLE_POLL_INTERVAL = 5000
const RUNNING_POLL_INTERVAL = 2000

const documentVisible = ref(typeof document === 'undefined' ? true : document.visibilityState === 'visible')

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    documentVisible.value = document.visibilityState === 'visible'
  })
}

interface PollableQuery {
  refetch: () => Promise<unknown>
}

function useVisiblePolling(query: PollableQuery, interval: MaybeRefOrGetter<number | false>): void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false

  const clear = (): void => {
    if (timer !== undefined) {
      clearTimeout(timer)
      timer = undefined
    }
  }

  const schedule = (): void => {
    clear()
    if (disposed) return
    const delay = toValue(interval)
    if (delay === false || delay <= 0) return
    timer = setTimeout(() => {
      timer = undefined
      void query
        .refetch()
        .catch(() => undefined)
        .finally(() => {
          if (!disposed) schedule()
        })
    }, delay)
  }

  watch(() => toValue(interval), schedule, { immediate: true })
  onScopeDispose(() => {
    disposed = true
    clear()
  })
}

function filterSnapshot(filters: ResourceFilters): ResourceFilters {
  return {
    category: filters.category ?? '',
    china_policy: filters.china_policy ?? '',
    status: filters.status ?? '',
    include_ended: filters.include_ended ?? false,
  }
}

function resourcesPath(filters: ResourceFilters): string {
  const params = new URLSearchParams()
  if (filters.category) params.set('category', filters.category)
  if (filters.china_policy) params.set('china_policy', filters.china_policy)
  if (filters.status) params.set('status', filters.status)
  if (filters.include_ended) params.set('include_ended', 'true')
  const search = params.toString()
  return search ? `/api/resources?${search}` : '/api/resources'
}

let appPollingInstalled = false

export function useAppQuery() {
  const query = useQuery<AppRead, Error>({
    queryKey: ['app'],
    queryFn: () => request<AppRead>('/api/app'),
    retry: false,
    refetchOnWindowFocus: false,
  })
  if (!appPollingInstalled) {
    appPollingInstalled = true
    useVisiblePolling(query, () =>
      autoRefreshEnabled.value && documentVisible.value ? IDLE_POLL_INTERVAL : false,
    )
  }
  return query
}

export interface ReviewMutationPayload {
  action: ReviewAction
  note?: string
}

export function useLeadsQuery() {
  const query = useQuery<LeadRead[], Error>({
    queryKey: ['leads'],
    queryFn: () => request<LeadRead[]>('/api/leads'),
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  })
  useVisiblePolling(query, () =>
    autoRefreshEnabled.value && documentVisible.value ? IDLE_POLL_INTERVAL : false,
  )
  return query
}

export function useReviewsQuery() {
  return useQuery<ResourceReview[], Error>({
    queryKey: ['reviews'],
    queryFn: () => request<ResourceReview[]>('/api/reviews'),
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useReviewMutation(resourceId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation<ReviewRead, Error, ReviewMutationPayload>({
    mutationFn: (payload) => {
      const id = toValue(resourceId)
      return request<ReviewRead>(`/api/resources/${encodeURIComponent(id)}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: payload.action, note: payload.note ?? '' }),
      })
    },
    retry: false,
    onSuccess: (result) => {
      const id = toValue(resourceId)
      queryClient.setQueryData<ResourceDetailRead>(['resources', 'detail', id], (previous) =>
        previous ? { ...previous, review: result.review, actions: result.actions } : previous,
      )
      void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['leads'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['reviews'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['resources'] })
      void queryClient.invalidateQueries({ queryKey: ['messages'] })
      void queryClient.invalidateQueries({ queryKey: ['resources', 'detail', id] })
    },
  })
}

export function useRecheckMutation(resourceId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation<RunRead, Error, void>({
    mutationFn: () => {
      const id = toValue(resourceId)
      return request<RunRead>(`/api/resources/${encodeURIComponent(id)}/recheck`, {
        method: 'POST',
      })
    },
    retry: false,
    onSuccess: (run) => {
      const id = toValue(resourceId)
      queryClient.setQueryData<TaskDetailRead>(['tasks', 'detail', run.id], { run, changes: [], messages: [] })
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'detail', run.id] })
      void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['tasks'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['leads'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['reviews'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['resources'] })
      void queryClient.invalidateQueries({ queryKey: ['messages'] })
      void queryClient.invalidateQueries({ queryKey: ['resources', 'detail', id] })
    },
  })
}

export function useResourcesQuery(filters: MaybeRefOrGetter<ResourceFilters>) {
  const snapshot = computed<ResourceFilters>(() => filterSnapshot(toValue(filters)))
  return useQuery<Resource[], Error>({
    queryKey: computed(() => ['resources', snapshot.value] as const),
    queryFn: () => request<Resource[]>(resourcesPath(snapshot.value)),
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useMessagesQuery(filters: MaybeRefOrGetter<MessageFilters>) {
  const snapshot = computed(() => ({
    category: toValue(filters).category ?? '',
    include_ended: toValue(filters).include_ended ?? false,
  }))
  return useQuery<NewsItem[], Error>({
    queryKey: computed(() => ['messages', snapshot.value] as const),
    queryFn: () => {
      const params = new URLSearchParams()
      if (snapshot.value.category) params.set('category', snapshot.value.category)
      if (snapshot.value.include_ended) params.set('include_ended', 'true')
      const search = params.toString()
      return request<NewsItem[]>(search ? `/api/messages?${search}` : '/api/messages')
    },
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useResourceQuery(id: MaybeRefOrGetter<string>) {
  return useQuery<ResourceDetailRead, Error>({
    queryKey: computed(() => ['resources', 'detail', toValue(id)] as const),
    queryFn: () => request<ResourceDetailRead>(`/api/resources/${encodeURIComponent(toValue(id))}`),
    enabled: computed(() => Boolean(toValue(id))),
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useTasksQuery(options: { sync?: boolean } = {}) {
  const query = useQuery<RunRead[], Error>({
    queryKey: ['tasks'],
    queryFn: () => request<RunRead[]>('/api/tasks'),
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  })
  if (options.sync) {
    useVisiblePolling(query, () => {
      if (!autoRefreshEnabled.value || !documentVisible.value) return false
      return query.data.value?.some((run) => run.status === 'running')
        ? RUNNING_POLL_INTERVAL
        : IDLE_POLL_INTERVAL
    })
  }
  return query
}

export function useTaskQuery(id: MaybeRefOrGetter<string>) {
  const query = useQuery<TaskDetailRead, Error>({
    queryKey: computed(() => ['tasks', 'detail', toValue(id)] as const),
    queryFn: () => request<TaskDetailRead>(`/api/tasks/${encodeURIComponent(toValue(id))}`),
    enabled: computed(() => Boolean(toValue(id))),
    retry: false,
    refetchOnWindowFocus: false,
  })
  useVisiblePolling(query, () => {
    if (!autoRefreshEnabled.value || !documentVisible.value) return false
    return query.data.value?.run.status === 'running' ? RUNNING_POLL_INTERVAL : false
  })
  return query
}

export function useBriefingsQuery() {
  return useQuery<RunRead[], Error>({
    queryKey: ['briefings'],
    queryFn: () => request<RunRead[]>('/api/briefings'),
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useBriefingQuery(id: MaybeRefOrGetter<string>) {
  return useQuery<BriefingRead, Error>({
    queryKey: computed(() => ['briefings', 'detail', toValue(id)] as const),
    queryFn: () => request<BriefingRead>(`/api/briefings/${encodeURIComponent(toValue(id))}`),
    enabled: computed(() => Boolean(toValue(id))),
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useStartTaskMutation() {
  const queryClient = useQueryClient()
  return useMutation<RunRead, Error, CreateTaskRequest>({
    mutationFn: (payload) =>
      request<RunRead>('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    retry: false,
    onSuccess: (run) => {
      queryClient.setQueryData<TaskDetailRead>(['tasks', 'detail', run.id], { run, changes: [], messages: [] })
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'detail', run.id] })
      void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['tasks'], exact: true })
    },
  })
}

export function useBackfillTranslationMutation() {
  const queryClient = useQueryClient()
  return useMutation<RunRead, Error, void>({
    mutationFn: () =>
      request<RunRead>('/api/translations/backfill', {
        method: 'POST',
      }),
    retry: false,
    onSuccess: (run) => {
      queryClient.setQueryData<TaskDetailRead>(['tasks', 'detail', run.id], { run, changes: [], messages: [] })
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'detail', run.id] })
      void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['tasks'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['leads'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['messages'] })
      void queryClient.invalidateQueries({ queryKey: ['resources'] })
    },
  })
}

export function useBackfillMessagesMutation() {
  const queryClient = useQueryClient()
  return useMutation<RunRead, Error, void>({
    mutationFn: () => request<RunRead>('/api/messages/backfill', { method: 'POST' }),
    retry: false,
    onSuccess: (run) => {
      queryClient.setQueryData<TaskDetailRead>(['tasks', 'detail', run.id], { run, changes: [], messages: [] })
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'detail', run.id] })
      void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['tasks'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['leads'], exact: true })
      void queryClient.invalidateQueries({ queryKey: ['messages'] })
      void queryClient.invalidateQueries({ queryKey: ['resources'] })
    },
  })
}

export function useSettingsQuery() {
  return useQuery<SettingsRead, Error>({
    queryKey: ['settings'],
    queryFn: () => request<SettingsRead>('/api/settings'),
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useSaveSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation<SettingsRead, Error, SettingsPatchRequest>({
    mutationFn: (payload) =>
      request<SettingsRead>('/api/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    retry: false,
    onSuccess: (settings) => {
      queryClient.setQueryData<SettingsRead>(['settings'], settings)
      void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
    },
  })
}

export function useResetSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation<SettingsRead, Error, SettingsResetRequest>({
    mutationFn: (payload) =>
      request<SettingsRead>('/api/settings/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    retry: false,
    onSuccess: (settings) => {
      queryClient.setQueryData<SettingsRead>(['settings'], settings)
      void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
    },
  })
}

export function useTestSettingsMutation() {
  return useMutation<SettingsTestRead, Error, SettingsTestRequest>({
    mutationFn: (payload) =>
      request<SettingsTestRead>('/api/settings/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    retry: false,
  })
}


export function useSourcesQuery() {
  return useQuery<SourceRead[], Error>({
    queryKey: ['sources'],
    queryFn: () => request<SourceRead[]>('/api/sources'),
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useSaveSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation<SourceRead, Error, SourceDefinition>({
    mutationFn: (definition) => {
      const id = definition.id
      if (!id) throw new Error('来源 ID 不能为空')
      return request<SourceRead>(`/api/sources/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition),
      })
    },
    retry: false,
    onSuccess: (source) => {
      const id = source.definition.id
      queryClient.setQueryData<SourceRead[]>(['sources'], (previous) =>
        previous === undefined
          ? [source]
          : previous.map((item) => (item.definition.id === id ? source : item)),
      )
      void queryClient.invalidateQueries({ queryKey: ['sources', 'entries', id] })
      void queryClient.invalidateQueries({ queryKey: ['sources', 'snapshots', id] })
    },
  })
}

export function useSourceEntriesQuery(
  id: MaybeRefOrGetter<string>,
  limit = 100,
  offset: MaybeRefOrGetter<number> = 0,
) {
  return useQuery<SourceEntry[], Error>({
    queryKey: computed(
      () => ['sources', 'entries', toValue(id), limit, toValue(offset)] as const,
    ),
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(toValue(offset)),
      })
      return request<SourceEntry[]>(
        `/api/sources/${encodeURIComponent(toValue(id))}/entries?${params.toString()}`,
      )
    },
    enabled: computed(() => Boolean(toValue(id))),
    retry: false,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  })
}

export function useSourceSnapshotsQuery(id: MaybeRefOrGetter<string>, limit = 20) {
  return useQuery<SourceSnapshot[], Error>({
    queryKey: computed(() => ['sources', 'snapshots', toValue(id), limit] as const),
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit) })
      return request<SourceSnapshot[]>(
        `/api/sources/${encodeURIComponent(toValue(id))}/snapshots?${params.toString()}`,
      )
    },
    enabled: computed(() => Boolean(toValue(id))),
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useSourceSnapshotQuery(snapshotId: MaybeRefOrGetter<string>) {
  return useQuery<SourceSnapshot, Error>({
    queryKey: computed(() => ['sources', 'snapshot', toValue(snapshotId)] as const),
    queryFn: () =>
      request<SourceSnapshot>(
        `/api/source-snapshots/${encodeURIComponent(toValue(snapshotId))}`,
      ),
    enabled: computed(() => Boolean(toValue(snapshotId))),
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useReplaySourceRulesMutation(sourceId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation<SourceEntry[], Error, void>({
    mutationFn: () =>
      request<SourceEntry[]>(
        `/api/sources/${encodeURIComponent(toValue(sourceId))}/replay`,
        { method: 'POST' },
      ),
    retry: false,
    onSuccess: () => {
      const id = toValue(sourceId)
      void queryClient.invalidateQueries({ queryKey: ['sources', 'entries', id] })
      void queryClient.invalidateQueries({ queryKey: ['sources'], exact: true })
    },
  })
}

import { ref } from 'vue'

export const autoRefreshEnabled = ref(true)

export function setAutoRefresh(value: boolean): void {
  autoRefreshEnabled.value = value
}

import { createApp } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import App from '@/app/App.vue'
import router from '@/app/router'
import '@/styles/app.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
})

const app = createApp(App)
app.use(VueQueryPlugin, { queryClient })
app.use(router)
app.mount('#app')

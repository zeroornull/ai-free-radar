import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

function apiTarget(): string {
  const value = process.env.AIFREERADAR_API_TARGET ?? 'http://127.0.0.1:8765'
  let target: URL
  try {
    target = new URL(value)
  } catch {
    throw new Error('AIFREERADAR_API_TARGET must be an HTTP loopback origin.')
  }
  if (value.trim() !== value || /[\\\s]/u.test(value) ||
      target.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(target.hostname) ||
      target.username || target.password || target.pathname !== '/' || target.search || target.hash ||
      !/^http:\/\/(?:127\.0\.0\.1|localhost)(?::[0-9]+)?\/?$/u.test(value)) {
    throw new Error('AIFREERADAR_API_TARGET must be an HTTP loopback origin without credentials, path, query, or fragment.')
  }
  return target.origin
}

export default defineConfig(() => {
  const target = apiTarget()
  // The dev proxy makes 5173 requests look same-origin to the backend: browser
  // writes reach /api with Origin 5173, so forward the backend's own origin.
  // This keeps the shipped server strictly same-origin without a dev allowlist.
  const proxyOptions = (): ProxyOptions => ({
    target,
    changeOrigin: true,
    configure: (proxy) => {
      proxy.on('proxyReq', (proxyReq) => proxyReq.setHeader('origin', target))
    },
  })
  return {
    base: '/',
    plugins: [vue(), tailwindcss()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': proxyOptions(),
        '/health': proxyOptions(),
      },
    },
    build: { outDir: '../aifreeradar/static/app', emptyOutDir: true },
  }
})

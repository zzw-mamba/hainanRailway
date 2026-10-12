import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { generationPlugin } from './server/generation.js'
import { amapProxyPlugin } from './server/amap_proxy.js'

export default defineConfig(({ mode }) => {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const existing = loadEnv(mode, root, 'AMAP_')
  const local = loadEnv(mode, process.cwd(), 'VITE_AMAP_')
  const serviceHost = local.VITE_AMAP_SERVICE_HOST || existing.AMAP_SERVICE_HOST || (mode === 'production' ? '/_AMapService' : '')
  return {
    base: './',
    plugins: [vue(), generationPlugin(), amapProxyPlugin(local.VITE_AMAP_SECURITY_CODE || existing.AMAP_SECURITY_CODE)],
    server: { watch: { ignored: ['**/public/data/**'] } },
    // Production uses a same-origin proxy so the security code never enters the built JS.
    // Local development may use the documented plain-text JS API setup.
    define: {
      __AMAP_KEY__: JSON.stringify(local.VITE_AMAP_KEY || existing.AMAP_KEY || ''),
      __AMAP_SERVICE_HOST__: JSON.stringify(serviceHost),
      __AMAP_SECURITY_CODE__: JSON.stringify(mode === 'production' ? '' : (local.VITE_AMAP_SECURITY_CODE || existing.AMAP_SECURITY_CODE || '')),
    },
  }
})

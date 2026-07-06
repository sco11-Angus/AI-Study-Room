import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 后端 API 与 WebSocket (§9)
      '/api': { target: 'http://localhost:5000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:5000', ws: true }
    }
  }
})

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 后端 API 与视频流（MJPEG 长连接直连，不走代理）
      '/api': { target: 'http://localhost:5000', changeOrigin: true }
    }
  }
})

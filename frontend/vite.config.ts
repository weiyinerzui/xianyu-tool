import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 后端端口：本机 8000 被 Docker 容器占用，默认走 8010。
// 需要改端口时直接改这里，或用 loadEnv 读 .env（避免依赖 node 的 process 类型）。
const BACKEND = 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
})

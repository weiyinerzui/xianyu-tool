import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 后端地址：默认 8000，可用环境变量覆盖（无需改代码）。
// 例：BACKEND_URL=http://127.0.0.1:8010 npx vite
// 注意：vite 的 env 只暴露 VITE_ 前缀的变量，因此这里手动读 process.env。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const BACKEND = env.BACKEND_URL || 'http://127.0.0.1:8000'

  return {
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
  }
})
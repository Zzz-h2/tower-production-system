import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端开发服务器：端口 5173，代理 /api 到 FastAPI 后端（8000，项目约定端口）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: true, // 监听 0.0.0.0，允许局域网其他机器访问（开发联调用）
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

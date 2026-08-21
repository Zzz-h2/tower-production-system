import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端开发服务器：端口 5173，代理 /api 到 FastAPI 后端（8000，项目约定端口）
export default defineConfig({
  plugins: [
    vue(),
    // 双保险：向 index.html 注入 no-cache meta（仅对浏览器缓存生效，CDN 层由 CloudBase 缓存配置兜底）
    {
      name: 'inject-no-cache-meta',
      transformIndexHtml(html) {
        return html.replace(
          '<head>',
          '<head>\n    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />\n    <meta http-equiv="Pragma" content="no-cache" />\n    <meta http-equiv="Expires" content="0" />',
        )
      },
    },
  ],
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

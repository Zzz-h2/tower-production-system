# AI 修改提示词：Vite 构建自动产出 404.html（SPA 部署兜底）

> 适用项目：`tower_production_system/frontend/`（Vue3 + Vite5 + vue-router4，SPA）
> 用途：部署到腾讯云 CloudBase 静态网站托管时，访问子路由（如 `/projects`）刷新不再 404（NoSuchKey），由前端 SPA（Vue Router）接管渲染。
> 直接把下面「一~四」整段复制给另一 AI 执行即可。

---

## 一、目标
让 `frontend` 在执行 `npm run build` 时，除正常产出 `dist/index.html` 外，**自动复制一份同内容的 `dist/404.html`**。这样 CloudBase 在访问不存在的路径时返回 `404.html`（内容就是 SPA 本身），浏览器加载后 Vue Router 按 URL 渲染对应页面。

## 二、禁止改动
- ❌ 不改动任何 Vue 业务组件、路由配置（vue-router）、API 调用逻辑（`src/api`）。
- ❌ 不改动 `server.proxy`（`/api` → `http://localhost:8000` 开发代理）配置。
- ❌ 不安装任何新的 npm 依赖（如 `vite-plugin-static-copy` / `vite-plugin-singlefile` 等），用 Node 内置 `fs` 即可。
- ❌ 不改动现有的 `vue()` 插件与 `plugins: [vue()]`。
- ❌ 不改动 `package.json` 里除 `build` 脚本外的其它字段（保持 `"type": "module"`、依赖不变）。

## 三、修改点

### 修改点 1（主方案，推荐，跨平台）：`vite.config.js` 增加自定义插件
文件：`frontend/vite.config.js`
在顶部 import 增加 Node 内置模块，并在 `plugins` 数组里追加一个 `closeBundle` 钩子插件，在打包完成后复制 `index.html` → `404.html`。

**完整文件代码（仅新增，原有逻辑一律保留）：**
```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// 前端开发服务器：端口 5173，代理 /api 到 FastAPI 后端（8000，项目约定端口）
export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'copy-index-to-404',
      apply: 'build', // 仅 build 阶段执行，dev 不受影响
      closeBundle() {
        copyFileSync(
          resolve(__dirname, 'dist/index.html'),
          resolve(__dirname, 'dist/404.html')
        )
        console.log('✅ 已生成 dist/404.html (SPA fallback)')
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
```

### 修改点 2（备选，仅 Windows cmd 环境，最简单）：`package.json` build 脚本
文件：`frontend/package.json`
把 `"build": "vite build"` 改为在后面追加 `&& copy dist\index.html dist\404.html`：
```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build && copy dist\\index.html dist\\404.html",
    "preview": "vite preview"
  }
}
```
⚠️ 注意：`copy` 是 Windows cmd 内置命令，仅在你用 cmd / PowerShell 跑 `npm run build` 时有效；若在 bash / Linux / Mac 下构建需换成 `cp dist/index.html dist/404.html`。因此**优先用修改点 1**（跨平台、无外部依赖）。

## 四、验收
1. 在 `frontend/` 目录执行 `npm run build`。
2. 构建日志应出现 `✅ 已生成 dist/404.html (SPA fallback)`（修改点 1）或 `1 file(s) copied.`（修改点 2）。
3. 检查 `frontend/dist/` 目录下**同时存在 `index.html` 与 `404.html`**，且两者内容一致（Windows 可用 `fc dist\index.html dist\404.html` 比对）。
4. 将 `dist/` 重新上传到 CloudBase 静态网站托管（确认「网站配置 → 基础设置 → 默认错误页」为 `404.html`），访问 `https://<前端域名>/projects` 并刷新（F5），页面正常渲染、不再 404（NoSuchKey）。
5. 回归：开发模式 `npm run dev`（5173）不受影响，`/api` 代理正常。

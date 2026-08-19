# 前端路由改为 Hash 模式（解决 CloudBase 静态托管 SPA 404）

## 目标
将 Vue Router 从 `history` 模式改为 `hash` 模式，使所有路由以 `/#/xxx` 形式存在（例如 `/#/projects`）。这样浏览器访问子页面时，服务器永远只收到 `/`（即 `index.html`），CloudBase 静态托管**无需任何路由规则/错误页配置**即可正常刷新，彻底消除 `NoSuchKey` 404 与 `TOO_MANY_REDIRECTS` 问题。

## 禁止改动
- 不改动任何业务页面组件、API 调用、状态管理（store）逻辑
- 不改动 `baseURL`、跨域、Vite 配置、后端代码
- 不改动 routes 数组里的路径定义（path 仍是 `/projects` 等，hash 模式会自动加 `#` 前缀）

## 修改点

### 文件：`frontend/src/router/index.js`

**修改点 1 — 第 1 行 import**
```js
// 修改前
import { createRouter, createWebHistory } from 'vue-router'
// 修改后
import { createRouter, createWebHashHistory } from 'vue-router'
```

**修改点 2 — 第 14~17 行 createRouter 调用**
```js
// 修改前
export default createRouter({
  history: createWebHistory(),
  routes,
})
// 修改后
export default createRouter({
  history: createWebHashHistory(),
  routes,
})
```

## 验收
1. 本地 `npm run build` 后，`dist/` 重新上传 CloudBase 静态托管（覆盖）。
2. 访问根域名 `https://tower-frontend-cloudbase-d2g5mgnii8ac68cb7.webapps.tcloudbase.com/` → 自动跳转到 `/#/projects`。
3. 在 `/#/projects` 页面按 **F5 刷新** → 正常渲染，不再 404。
4. 点击进入项目详情 `/#/projects/1` → 正常，刷新也不 404。
5. CloudBase 控制台的「路由配置」**留空**（不需要任何规则），「默认错误页」也不需要设。

import axios from 'axios'
import { ElMessage } from 'element-plus'

// 生产 build 由 .env.production 的 VITE_API_BASE 注入后端公网地址（直连绕过网关 /api 剥离问题）；
// 本地 npm run dev 未设该变量时回退 '/api'，由 Vite 代理转发到 localhost:8000
const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 30000,
})

// 401 并发处理幂等锁：避免多接口同时 401 时重复清 token / 重复跳登录页（竞态保护）
let auth401Handling = false

// 请求拦截器：从 localStorage 'tower_auth' 读取 token，注入 Bearer 头
http.interceptors.request.use(
  (config) => {
    try {
      const saved = JSON.parse(localStorage.getItem('tower_auth') || 'null')
      const token = saved?.token
      if (token) {
        config.headers = config.headers || {}
        config.headers.Authorization = `Bearer ${token}`
      }
    } catch (e) {
      // localStorage 解析失败视为未登录，不阻断请求
    }
    return config
  },
  (err) => Promise.reject(err),
)

// 响应拦截器：
// - 成功保持既有契约：直接返回 res.data
// - 401 且非登录接口：会话过期，统一登出并跳登录页（带 redirect 回跳）
// - 登录接口错误：由登录页内联展示后端 detail，不重复 toast
// - 其余错误：统一 ElMessage.error(detail)
http.interceptors.response.use(
  (res) => res.data,
  async (err) => {
    const status = err.response?.status
    const url = err.config?.url || ''
    const isLoginUrl = url.includes('/auth/login')

    // 会话过期（业务接口 401）：并发 401 需幂等保护，避免竞态下重复清 token
    if (status === 401 && !isLoginUrl) {
      if (!auth401Handling) {
        auth401Handling = true
        // 先快照当前 token；仅当 token 未被重新登录覆盖时才清登出，杜绝竞态清掉新 token
        const staleToken = localStorage.getItem('tower_auth')
        try {
          // 动态引入，避免 api <-> store/router 的循环依赖
          const { useAuthStore } = await import('../store/auth')
          const { default: router } = await import('../router')
          const auth = useAuthStore()
          // 仅当 token 未被重新登录覆盖、且仍处于登录态时才清登出并跳登录页，
          // 避免并发 401 的延迟处理在用户已重登后误清新 token / 误跳登录页
          if (localStorage.getItem('tower_auth') === staleToken && auth.isLoggedIn) {
            auth.logout()
            const current = router.currentRoute.value
            const redirect = current && current.name !== 'login' ? current.fullPath : ''
            router.replace({
              path: '/login',
              query: redirect ? { redirect } : {},
            })
          }
        } catch (e) {
          // 动态引入失败（极端情况）也不阻断流程
        }
        // 3 秒后解锁，允许下一次真实会话过期再处理
        setTimeout(() => { auth401Handling = false }, 3000)
      }
      ElMessage.error('登录已过期，请重新登录')
      return Promise.reject(err)
    }

    // 登录接口自身错误：让登录页内联展示后端 detail，避免双弹窗
    if (isLoginUrl) {
      return Promise.reject(err)
    }

    // 透出后端业务 detail 的友好文案：机器可读 detail={code,message} → 取 message；字符串 → 直接用；无 → 兜底
    let msg = '请求失败'
    const raw = err.response?.data?.detail
    if (raw && typeof raw === 'object') msg = raw.message || '请求失败'
    else if (typeof raw === 'string' && raw) msg = raw
    else msg = err.message || '请求失败'
    err.message = msg   // 供调用方（如 ProcessDetailDialog）读取友好文案，而非「Request failed with status code 422」
    // 填报保存接口（…/nodes/{工序}/save）的失败由 ProcessDetailDialog 以分组汇总 toast 呈现，
    // 此处抑制全局 toast 避免重复提示；其余接口仍走全局提示。
    if (!url.endsWith('/save')) ElMessage.error(msg)
    return Promise.reject(err)
  },
)

export default http

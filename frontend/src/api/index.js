import axios from 'axios'
import { ElMessage } from 'element-plus'

// 生产 build 由 .env.production 的 VITE_API_BASE 注入后端公网地址（直连绕过网关 /api 剥离问题）；
// 本地 npm run dev 未设该变量时回退 '/api'，由 Vite 代理转发到 localhost:8000
const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 30000,
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const detail = err.response?.data?.detail || err.message || '请求失败'
    ElMessage.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    return Promise.reject(err)
  },
)

export default http

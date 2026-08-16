import axios from 'axios'
import { ElMessage } from 'element-plus'

// axios 实例：baseURL 走 Vite 代理（/api → FastAPI:8000）
const http = axios.create({
  baseURL: '/api',
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

import axios from 'axios'
import { ElMessage } from 'element-plus'

// 生产环境：直连 CloudRun 后端公网域名（CloudBase HTTP 网关转发会剥离 /api 前缀导致 404，故直连）
const http = axios.create({
  baseURL: 'https://tower-backend-299223-6-1470711810.sh.run.tcloudbase.com/api',
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

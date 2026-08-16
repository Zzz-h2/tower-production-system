import http from './index'

// 项目列表（总览页）：对象参数支持 keyword/person/status/page/page_size
export const fetchProjects = (params = {}) =>
  http.get('/projects', { params })

// 全量交付负责人（下拉框数据源，与筛选结果隔离）
export const fetchAllPersons = () =>
  http.get('/projects/persons')

export const fetchProject = (pid) => http.get(`/projects/${pid}`)

// 看板指标（项目总览页 KPI 卡）
export const fetchDashboardStats = () => http.get('/dashboard/stats')

// 手动添加项目
export const addProject = (payload) => http.post('/projects', payload)

// 编辑 / 删除项目
export const updateProject = (pid, payload) => http.put(`/projects/${pid}`, payload)
export const deleteProject = (pid) => http.delete(`/projects/${pid}`)

// 导入月度调度令（批量建项目）
export const importDispatch = (file) => {
  const form = new FormData()
  form.append('file', file)
  return http.post('/projects/import-dispatch', form)
}

// 节点计划
export const fetchNodePlans = (pid) => http.get(`/projects/${pid}/node-plans`)
export const fetchProcessNodes = (pid, processName) =>
  http.get(`/projects/${pid}/nodes/${encodeURIComponent(processName)}`)
export const saveNodeProgress = (pid, processName, payload) =>
  http.post(`/projects/${pid}/nodes/${encodeURIComponent(processName)}/save`, payload)

// 预警
export const fetchAlerts = (pid) => http.get(`/projects/${pid}/alerts`)

// Excel 导入（排产，既有接口，勿改）
export const importSchedule = (pid, file) => {
  const form = new FormData()
  form.append('file', file)
  return http.post(`/projects/${pid}/import-schedule`, form)
}

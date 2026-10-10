import http from './index'

// 项目列表（总览页）：对象参数支持 keyword/person/status/page/page_size
export const fetchProjects = (params = {}) =>
  http.get('/projects', { params })

// 全量交付负责人（下拉框数据源，与筛选结果隔离）
export const fetchAllPersons = () =>
  http.get('/projects/persons')

// 全量大区负责人（下拉框数据源，与筛选结果隔离）
export const fetchBigAreaPersons = () =>
  http.get('/projects/big-area-persons')

// 项目详情（进度/风险）。v7.4：params 可带 { month }，按该排产归属月口径计算进度与风险，
// 与「节点计划」页同月一致；不传则跨月汇总（历史行为）。
export const fetchProject = (pid, params = {}) =>
  http.get(`/projects/${pid}`, { params })

// 看板指标（项目总览页 KPI 卡，支持调度令月份 month）
export const fetchDashboardStats = (month) =>
  http.get('/dashboard/stats', { params: { month } })

// 导出指定调度令月份计划完成情况（全量，前端本地生成 xlsx）
export const fetchExportProjects = (month) =>
  http.get('/projects/export', { params: { month } })

// 手动添加项目
export const addProject = (payload) => http.post('/projects', payload)

// 编辑 / 删除项目
export const updateProject = (pid, payload) => http.put(`/projects/${pid}`, payload)
export const deleteProject = (pid) => http.delete(`/projects/${pid}`)

// 预览月度调度令（返回表头/样例值/建议映射/系统字段，不写库）
export const previewDispatch = (file) => {
  const form = new FormData()
  form.append('file', file)
  return http.post('/projects/preview-dispatch', form)
}

// 导入月度调度令（批量建项目）
// mapping: {Excel列名: 系统字段名}，不传则由后端自动识别
// planMonth: 调度令归属月 'YYYY-MM'；不传则后端按文件名推断、再退化为当前自然月
export const importDispatch = (file, mapping, planMonth) => {
  const form = new FormData()
  form.append('file', file)
  if (mapping) form.append('mapping', JSON.stringify(mapping))
  if (planMonth) form.append('plan_month', planMonth)
  return http.post('/projects/import-dispatch', form)
}

// 节点计划（多负责人 v6.0：params 可带 { manager } 切到单人视图，缺省为汇总视图）
// v7.4 排产按月隔离：params 另可带 { month: 'YYYY-MM' } → 只取「该月导入的行 ∪ 未标注月行」
export const fetchNodePlans = (pid, params = {}) =>
  http.get(`/projects/${pid}/node-plans`, { params })
export const fetchProcessNodes = (pid, processName, params = {}) =>
  http.get(`/projects/${pid}/nodes/${encodeURIComponent(processName)}`, { params })
export const saveNodeProgress = (pid, processName, payload) =>
  http.post(`/projects/${pid}/nodes/${encodeURIComponent(processName)}/save`, payload)

// 按段填报（v7.1 行级化）：录入某套（计划行）的「总段数 + 已完成段数」，
// 段数唯一挂在 node_id 上，独立记录不折算、不写 actual_qty
// payload: { node_id: int, segment_total: int, segment_done: int }；返回 { ok: true }
export const saveSegmentProgress = (pid, processName, payload) =>
  http.post(`/projects/${pid}/nodes/${encodeURIComponent(processName)}/save-segments`, payload)

// 多负责人管理（v6.0）
// v7.4：可带 month，使 plan_rows / has_imported 表示「该负责人本月是否已导入排产」
export const fetchProjectManagers = (pid, month) =>
  http.get(`/projects/${pid}/managers`, { params: month ? { month } : {} })
export const setManagerMonthlyPlan = (pid, manager, monthlyPlan) =>
  http.put(`/projects/${pid}/managers/${encodeURIComponent(manager)}/monthly-plan`, {
    monthly_plan: monthlyPlan,
  })

// 预警（v7.4：可带 month，按排产归属月口径）
export const fetchAlerts = (pid, month) =>
  http.get(`/projects/${pid}/alerts`, { params: month ? { month } : {} })

// Excel 导入（排产）。多负责人 v6.0：可带 manager（归属负责人）+ monthlyPlan（该负责人本月计划数）
// v7.2：可带 planMonth（本次排产归属月 'YYYY-MM'，默认当前自然月）——
//       决定 has_schedule_plan 的「本月口径」判定与归档归属，不传则由后端按文件名/当前月推断。
export const importSchedule = (pid, file, manager, monthlyPlan, planMonth) => {
  const form = new FormData()
  form.append('file', file)
  if (manager) form.append('manager', String(manager))
  if (monthlyPlan !== undefined && monthlyPlan !== null) {
    form.append('monthly_plan', String(monthlyPlan))
  }
  if (planMonth) form.append('plan_month', String(planMonth))
  return http.post(`/projects/${pid}/import-schedule`, form)
}

// 手动完成（仅 admin）：为「提前完工但无排产计划」的项目补录『附件安装』产出
// payload: { complete_qty: int, complete_date: 'YYYY-MM-DD' }；返回 { message, node_plan_id, completed_sets, remaining_sets }
// 同日重复提交 = 覆盖（改小数值即「减少」已录成套数）
export const manualComplete = (pid, payload) => http.post(`/projects/${pid}/manual-complete`, payload)

// 手动完成记录（2026-10-10）：列出已录入记录（含完成月/套数/负责人），供弹窗查看并纠正
// 返回 { items, month, contract_count, completed_sets, remaining_sets }
export const fetchManualCompletes = (pid, month) =>
  http.get(`/projects/${pid}/manual-completes`, { params: month ? { month } : {} })
// 删除一条手动完成记录（纠正误录 / 减少套数）；id = node_plan_id
export const deleteManualComplete = (pid, nodePlanId) =>
  http.delete(`/projects/${pid}/manual-completes/${nodePlanId}`)

// 「预计完成」登记（2026-10-10 新增）：即将完成但还没有排产计划的项目，登记「预计完成日期 + 当日套数」
// 返回 { items:[{id, forecast_date, forecast_qty, manager}], total_qty }
export const fetchCompletionForecasts = (pid) =>
  http.get(`/projects/${pid}/completion-forecasts`)
// 新增/更新一条（同项目+同日+同负责人 = 覆盖）；返回 { id, items, total_qty }
export const saveCompletionForecast = (pid, payload) =>
  http.post(`/projects/${pid}/completion-forecasts`, payload)
export const deleteCompletionForecast = (pid, forecastId) =>
  http.delete(`/projects/${pid}/completion-forecasts/${forecastId}`)

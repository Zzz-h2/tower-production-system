import http from './index'

// 排产工序配置：工序顺序 + 标准工期（单一来源，前端启动时拉取一次）
export const fetchScheduleConfig = () => http.get('/config/schedule')

// 里程碑倒排：交付截止日 + 可选自定义工序工期 → 返回倒排计划与偏差分析
export const fetchMilestoneBackward = (pid, deliveryDeadline, customDurations = null) =>
  http.post(`/projects/${pid}/milestone-backward`, {
    delivery_deadline: deliveryDeadline,
    custom_durations: customDurations,
  })

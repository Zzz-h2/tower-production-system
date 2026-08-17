import http from './index'

// 里程碑倒排：交付截止日 + 可选自定义工序工期 → 返回倒排计划与偏差分析
export const fetchMilestoneBackward = (pid, deliveryDeadline, customDurations = null) =>
  http.post(`/projects/${pid}/milestone-backward`, {
    delivery_deadline: deliveryDeadline,
    custom_durations: customDurations,
  })

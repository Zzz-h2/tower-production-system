import http from './index'

// 节点异常提报
export const createException = (pid, nodeId, data) =>
  http.post(`/exceptions/projects/${pid}/nodes/${nodeId}`, data)

export const listExceptionsByProject = (pid) =>
  http.get(`/exceptions/projects/${pid}`)

// 项目下已关闭的历史异常记录（按关闭时间倒序）
export const listClosedExceptions = (pid) =>
  http.get(`/exceptions/projects/${pid}/exceptions/closed`)

export const listExceptionsByNode = (nodeId) =>
  http.get(`/exceptions/nodes/${nodeId}`)

export const updateException = (excId, data) =>
  http.put(`/exceptions/${excId}`, data)

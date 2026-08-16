import http from './index'

// 节点异常提报
export const createException = (pid, nodeId, data) =>
  http.post(`/exceptions/projects/${pid}/nodes/${nodeId}`, data)

export const listExceptionsByProject = (pid) =>
  http.get(`/exceptions/projects/${pid}`)

export const listExceptionsByNode = (nodeId) =>
  http.get(`/exceptions/nodes/${nodeId}`)

export const updateException = (excId, data) =>
  http.put(`/exceptions/${excId}`, data)

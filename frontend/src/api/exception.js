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

// 删除单条异常记录（仅 admin；后端 require_admin 兜底校验，非 admin → 403）
// 幂等（2026-11 定稿）：返回 { ok, deleted, id }
//   deleted=1 → 本次确实删掉；deleted=0 → 记录已不存在（重复删 / 从未存在），仍是 HTTP 200
//   调用方按 deleted 区分 success / warning 文案，不要当成失败处理
export const deleteException = (excId) =>
  http.delete(`/exceptions/${excId}`)

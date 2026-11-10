import http from './index'

/**
 * 问题管控看板（v7.10）
 *
 * 数据源是「工序里提报的异常」(`node_exceptions`)，本模块只读看板 + 编辑单条问题。
 */

/**
 * 取看板数据（KPI / 三个维度分布 / 明细列表）。
 *
 * 分层口径：
 *  - month 按**提报月**(created_at) 过滤，与「项目详情 → 异常记录」同口径；
 *  - overdue_only=true 只看「未关闭且已过解决时间」；
 *  - keyword 模糊匹配 项目名 / 问题描述 / 工序 / 责任人。
 *
 * @param {{month?: string, status?: string, severity?: string, project_id?: number,
 *          overdue_only?: boolean, keyword?: string}} params
 * @returns {Promise<{kpis: object, by_status: Array, by_severity: Array,
 *          by_area: Array, items: Array, month: string|null, today: string}>}
 */
export const fetchIssueBoard = (params = {}) => {
  const query = {}
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '' || v === false) return
    query[k] = v
  })
  return http.get('/issues/board', { params: query })
}

/**
 * 编辑单条问题（仅管理员，后端 require_admin）。
 *
 * @param {number} id node_exceptions.id
 * @param {{severity?: string, status?: string, handler?: string,
 *          planned_close_date?: string|null, reason_detail?: string}} payload 只传要改的字段
 * @returns {Promise<object>} 更新后的整行（与看板 items 同构）
 */
export const patchIssue = (id, payload) => http.patch(`/issues/${id}`, payload)

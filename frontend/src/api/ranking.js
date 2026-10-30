import http from './index'

// 出品排名：按交付负责人聚合当月『附件安装』出品数据
export const fetchProductionRanking = (month) =>
  http.get('/ranking/production', { params: { month } })

// 某负责人当月逾期/提前项目清单
export const fetchProductionRankingDetail = (month, person) =>
  http.get('/ranking/production/detail', { params: { month, person } })

// 提报情况总览：当月自然日 × 负责人矩阵（× = 当天有计划但完全未提报，仅判定至昨天）
export const fetchSubmissionBoard = (month) =>
  http.get('/ranking/submission-board', { params: { month } })

/**
 * 提报情况总览：批量保存人工覆盖标记（仅管理员，后端非 admin 返回 403）。
 *
 * 语义是「覆盖记录」而非翻转：
 *   action='missed'  → 该格强制 ×（即使当天有填报/异常）
 *   action='on_time' → 该格强制留空（即使自动判定漏报）
 *   action='auto'    → 删除覆盖行，恢复自动判定（可逆）
 *
 * @param {string} month 'YYYY-MM'
 * @param {Array<{manager: string, date: string, action: 'missed'|'on_time'|'auto'}>} items
 * @returns {Promise<{saved: number, upserted: number, deleted: number, board: object}>}
 *          board 与 GET /ranking/submission-board 同构，可直接用于刷新矩阵
 */
export const saveSubmissionOverrides = (month, items) =>
  http.post('/ranking/submission-board/overrides', { month, items })

/**
 * 出品排名：录入一条「计划外完成」（**仅管理员**，后端非 admin 返回 403）。
 *
 * 口径：month 只影响该月的排名与 KPI；行的累计完成 = 原实绩 + 该月该负责人额外合计；
 * 完成率只加分子不动分母（可能 >100%）；排名按含额外后重排。
 *
 * @param {{month: string, manager: string, project_name: string,
 *          machine_type?: string|null, qty: number}} payload
 * @returns {Promise<{id: number, extra_total: number}>} extra_total = 该月最新合计（KPI 用）
 */
export const addExtraCompletion = (payload) =>
  http.post('/ranking/extra', payload)

/**
 * 出品排名：某负责人当月的「计划外完成」登记明细（详情弹窗用，按录入时间倒序）。
 *
 * 权限：admin 可查任意负责人；大区账号仅能查本大区可见负责人（越权返回 403）。
 *
 * @param {string} month 'YYYY-MM'
 * @param {string} manager 负责人姓名
 * @returns {Promise<{items: Array<{id:number, manager:string, project_name:string,
 *          machine_type:string|null, qty:number, created_at:string}>}>}
 */
export const fetchExtraCompletions = (month, manager) =>
  http.get('/ranking/extra/list', { params: { month, manager } })

/**
 * 出品排名：修改一条已填报的「计划外完成」套数（**仅管理员**，后端非 admin 返回 403）。
 *
 * 只改 qty，不改负责人/月份归属；month 必须与记录原月份一致，否则后端返回 404。
 * 修改后排名、完成率、两张 KPI 卡在下次拉取时自动重算。
 *
 * @param {number} id 记录 id
 * @param {{month: string, qty: number}} payload
 * @returns {Promise<{id: number, extra_total: number}>}
 */
export const updateExtraCompletion = (id, payload) =>
  http.put(`/ranking/extra/${id}`, payload)

/**
 * 出品排名：删除一条已填报的「计划外完成」（**仅管理员**，后端非 admin 返回 403）。
 *
 * month 走查询参数（DELETE 不带 body），必须与记录原月份一致，否则后端返回 404。
 * 删除后该负责人累计完成 / 完成率 / 排名顺序 / KPI 在下次拉取时自动回退。
 *
 * @param {number} id 记录 id
 * @param {string} month 'YYYY-MM'
 * @returns {Promise<{id: number, deleted: boolean, extra_total: number}>}
 */
export const deleteExtraCompletion = (id, month) =>
  http.delete(`/ranking/extra/${id}`, { params: { month } })

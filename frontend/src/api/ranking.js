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

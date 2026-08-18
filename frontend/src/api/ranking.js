import http from './index'

// 出品排名：按交付负责人聚合当月『附件安装』出品数据
export const fetchProductionRanking = (month) =>
  http.get('/ranking/production', { params: { month } })

// 某负责人当月逾期/提前项目清单
export const fetchProductionRankingDetail = (month, person) =>
  http.get('/ranking/production/detail', { params: { month, person } })

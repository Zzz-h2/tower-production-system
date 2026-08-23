import { defineStore } from 'pinia'
import {
  fetchProjects,
  fetchProject,
  fetchNodePlans,
  fetchDashboardStats,
  fetchAllPersons,
  fetchBigAreaPersons,
  addProject as addProjectApi,
} from '../api/node'

export const useProjectStore = defineStore('project', {
  state: () => ({
    projects: [],
    current: null,        // 当前项目详情
    overview: null,       // 节点计划总览（kpis/processes/timeline）
    loading: false,

    allPersons: [],       // 全量交付负责人（下拉框数据源，与筛选结果隔离）
    allBigAreaPersons: [], // 全量大区负责人（下拉框数据源，与筛选结果隔离）

    lastNodeSavedAt: 0,   // 节点填报保存时间戳，供 AlertList 监听实时刷新

    // 看板指标（KPI 卡，字段与 /api/dashboard/stats 一致）
    dashboard: {
      total_projects: 0,
      warning_projects: 0,
      delayed_projects: 0,
      monthly_plan_total: 0,
    },

    // 搜索/筛选条件
    filters: {
      keyword: '',
      person: '',
      bigAreaPerson: '',
      status: 'all',
      month: '',          // 全局共享调度令月份（YYYY-MM），三页联动；ensureMonth 补当前月
    },

    // 分页
    pagination: {
      page: 1,
      page_size: 10,
      total: 0,
    },
  }),
  actions: {
    /**
     * 确保共享月份非空：默认当前自然月（YYYY-MM）。
     */
    ensureMonth() {
      if (!this.filters.month) {
        const d = new Date()
        this.filters.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
      }
      return this.filters.month
    },

    /**
     * 加载项目列表（总览页）。
     * 合并外部传入的筛选/分页条件到 state，再请求后端（服务端分页）。
     */
    async loadProjects(filters = {}) {
      if (filters.keyword !== undefined) this.filters.keyword = filters.keyword
      if (filters.person !== undefined) this.filters.person = filters.person
      if (filters.bigAreaPerson !== undefined) this.filters.bigAreaPerson = filters.bigAreaPerson
      if (filters.status !== undefined) this.filters.status = filters.status
      if (filters.month !== undefined) this.filters.month = filters.month
      if (filters.page !== undefined) this.pagination.page = filters.page
      if (filters.page_size !== undefined) this.pagination.page_size = filters.page_size

      this.loading = true
      try {
        const data = await fetchProjects({
          keyword: this.filters.keyword || undefined,
          person: this.filters.person || undefined,
          big_area_person: this.filters.bigAreaPerson || undefined,
          status: this.filters.status || 'all',
          month: this.filters.month || undefined,
          page: this.pagination.page,
          page_size: this.pagination.page_size,
        })
        this.projects = data.items || []
        this.pagination.total = data.total || 0
      } finally {
        this.loading = false
      }
    },

    /** 加载看板指标（随共享月份联动）。 */
    async loadDashboard() {
      try {
        this.dashboard = await fetchDashboardStats(this.filters.month || undefined)
      } catch (e) {
        // 错误已由 axios 拦截器统一提示
      }
    },

    /** 加载全量交付负责人（下拉框数据源，与筛选结果隔离）。 */
    async loadAllPersons() {
      try {
        const res = await fetchAllPersons()
        this.allPersons = res.items || []
      } catch (err) {
        console.error('加载交付负责人失败', err)
        this.allPersons = []
      }
    },

    /** 加载全量大区负责人（下拉框数据源，与筛选结果隔离）。 */
    async loadAllBigAreaPersons() {
      try {
        const res = await fetchBigAreaPersons()
        this.allBigAreaPersons = res.items || []
      } catch (err) {
        console.error('加载大区负责人失败', err)
        this.allBigAreaPersons = []
      }
    },

    /** 手动添加项目，成功后刷新列表（保留当前筛选/分页）。 */
    async addProject(payload) {
      const created = await addProjectApi(payload)
      await this.loadProjects()
      return created
    },

    /** 重置筛选条件与页码。 */
    resetFilters() {
      this.filters = { keyword: '', person: '', bigAreaPerson: '', status: 'all' }
      this.pagination.page = 1
    },

    async loadDetail(pid) {
      this.current = await fetchProject(pid)
      return this.current
    },
    async loadOverview(pid) {
      this.overview = await fetchNodePlans(pid)
      return this.overview
    },
  },
})

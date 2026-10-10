import { defineStore } from 'pinia'
import { fetchScheduleConfig } from '../api/milestone'
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
    personsLoaded: false,        // 下拉选项是否已成功加载（失败时不得据此清理筛选值）
    bigAreaPersonsLoaded: false,

    // 排产工序配置（启动时拉取一次，前端唯一来源；不再手工复制 11 道工序/工期）
    scheduleConfig: {
      loaded: false,
      processNames: [],
      defaultDurations: {},
    },

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

    /**
     * 加载全量交付负责人（下拉框数据源，与筛选结果隔离）。
     * @returns {Promise<boolean>} 是否加载成功（失败时不得据此判定筛选值失效）
     */
    async loadAllPersons() {
      try {
        const res = await fetchAllPersons()
        this.allPersons = res.items || []
        this.personsLoaded = true
        return true
      } catch (err) {
        // 错误已由 axios 拦截器统一提示；兜底置空但不置 loaded（避免误清筛选值）
        this.allPersons = []
        this.personsLoaded = false
        return false
      }
    },

    /** 加载全量大区负责人（下拉框数据源，与筛选结果隔离）。 */
    async loadAllBigAreaPersons() {
      try {
        const res = await fetchBigAreaPersons()
        this.allBigAreaPersons = res.items || []
        this.bigAreaPersonsLoaded = true
        return true
      } catch (err) {
        // 错误已由 axios 拦截器统一提示；兜底置空但不置 loaded（避免误清筛选值）
        this.allBigAreaPersons = []
        this.bigAreaPersonsLoaded = false
        return false
      }
    },

    /**
     * 下拉选项重载后，校验当前筛选选中值是否仍然存在于存活选项中。
     *
     * 背景：筛选值（person / bigAreaPerson）是自由字符串，项目删除/改名后该值可能
     * 已不存在；el-select 单值 + filterable 会把失效值**原样渲染成标签**，
     * 导致「项目已删除，筛选栏仍残留旧记录，列表恒 0 条」。此方法负责清空这类孤儿值。
     *
     * 安全边界：
     *   - 仅在「选项确实加载成功」时校验（加载失败会把列表置空，此时清空会误伤）；
     *   - 大区账号的区域锁定值（lockedBigArea）受后端强制隔离，不参与校验。
     *
     * @param {object} [opts]
     * @param {string} [opts.lockedBigArea=''] 大区账号锁定的区域名（非空时跳过校验）
     * @returns {Array<{label:string,value:string}>} 被清空的筛选项（供上层提示）
     */
    reconcilePersonFilter({ lockedBigArea = '' } = {}) {
      const cleared = []

      if (this.personsLoaded && this.filters.person
          && !this.allPersons.includes(this.filters.person)) {
        cleared.push({ label: '交付负责人', value: this.filters.person })
        this.filters.person = ''
      }

      const areaLocked = !!lockedBigArea && this.filters.bigAreaPerson === lockedBigArea
      if (!areaLocked && this.bigAreaPersonsLoaded && this.filters.bigAreaPerson
          && !this.allBigAreaPersons.includes(this.filters.bigAreaPerson)) {
        cleared.push({ label: '大区负责人', value: this.filters.bigAreaPerson })
        this.filters.bigAreaPerson = ''
      }

      return cleared
    },

    /** 手动添加项目，成功后刷新列表（保留当前筛选/分页）。 */
    async addProject(payload) {
      const created = await addProjectApi(payload)
      await this.loadProjects()
      return created
    },

    /** 拉取排产工序配置（工序顺序 + 标准工期），仅拉取一次。 */
    async loadScheduleConfig() {
      if (this.scheduleConfig.loaded) return
      try {
        const res = await fetchScheduleConfig()
        this.scheduleConfig = {
          loaded: true,
          processNames: res?.process_names || [],
          defaultDurations: res?.default_durations || {},
        }
      } catch (err) {
        // 错误已由 axios 拦截器统一提示；保持空配置
      }
    },

    async loadDetail(pid) {
      this.current = await fetchProject(pid)
      return this.current
    },
    async loadOverview(pid, manager) {
      const params = manager ? { manager } : {}
      this.overview = await fetchNodePlans(pid, params)
      return this.overview
    },
  },
})

import { defineStore } from 'pinia'
import http from '../api'

const STORAGE_KEY = 'tower_auth'

/**
 * 从 localStorage 恢复登录态。
 * 兼容旧结构：旧版存储的是 { username, role, label }，没有 token —— 一律视为未登录（不抛错）。
 * @returns {{ token: string, user: object } | null}
 */
function readSaved() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || !parsed.token) return null
    return parsed
  } catch (e) {
    return null
  }
}

function writeSaved(token, user) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user }))
}

/**
 * 认证 Store（Pinia）。
 * 登录态以服务端签发的 access_token 为准，持久化到 localStorage（key: tower_auth）。
 * 角色：admin（全量 + 管理写操作）；big_area（仅本大区 + 可填报本大区）。
 */
export const useAuthStore = defineStore('auth', {
  state: () => {
    const saved = readSaved()
    const user = saved?.user || {}
    return {
      token: saved?.token || '',
      username: user.username || '',
      role: user.role || '',             // 'admin' | 'big_area'
      bigAreaName: user.big_area_name || '',
      label: user.label || '',
    }
  },
  getters: {
    // 登录态：存在 token 即视为已登录（刷新不丢）
    isLoggedIn: (s) => !!s.token,
    // 管理员：拥有全量数据 + 管理写操作
    isAdmin: (s) => s.role === 'admin',
    // 大区账号：仅本大区数据
    isBigArea: (s) => s.role === 'big_area',
    // 管理写操作（编辑/删除/导入调度令/排产导入等）——仅管理员
    canEdit: (s) => s.role === 'admin',
    // 填报/提报操作（节点进度填报）——管理员或大区账号均可
    canFill: (s) => s.role === 'admin' || s.role === 'big_area',
    // 大区账号锁定的大区名（空串表示不限大区/管理员）
    lockedBigAreaName: (s) => s.bigAreaName,
  },
  actions: {
    /**
     * 登录：POST /api/auth/login，成功后将 token + user 写入 state 与 localStorage。
     * @param {string} username
     * @param {string} password
     * @returns {Promise<object>} 后端响应体 { access_token, token_type, expires_in, user }
     */
    async login(username, password) {
      const res = await http.post('/auth/login', { username, password })
      const token = res.access_token
      const user = res.user
      this.token = token
      this.username = user.username
      this.role = user.role
      this.bigAreaName = user.big_area_name || ''
      this.label = user.label || ''
      writeSaved(token, user)
      return res
    },

    /**
     * 用当前 token 拉取 /api/auth/me，校验并刷新 user 信息。
     * token 无效时后端返回 401，由 axios 拦截器统一登出跳转。
     * @returns {Promise<object>} user
     */
    async fetchMe() {
      const res = await http.get('/auth/me')
      const user = res.user
      this.username = user.username
      this.role = user.role
      this.bigAreaName = user.big_area_name || ''
      this.label = user.label || ''
      if (this.token) writeSaved(this.token, user)
      return user
    },

    /**
     * 登出：清空 state 与 localStorage（JWT 无状态，本地清理即可）。
     */
    logout() {
      this.token = ''
      this.username = ''
      this.role = ''
      this.bigAreaName = ''
      this.label = ''
      localStorage.removeItem(STORAGE_KEY)
    },
  },
})

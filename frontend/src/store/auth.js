import { defineStore } from 'pinia'

// 预设账号（纯前端校验；如需安全改为后端接口校验，见二期）
const PRESET_ACCOUNTS = [
  { username: 'admin', password: 'admin123', role: 'admin', label: '管理员' },
  { username: 'user',  password: 'user123',  role: 'normal', label: '普通账号' },
]

const STORAGE_KEY = 'tower_auth'

export const useAuthStore = defineStore('auth', {
  state: () => {
    // 刷新后从 localStorage 恢复登录态
    let saved = null
    try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null') } catch (e) {}
    return {
      isLoggedIn: !!saved,
      username: saved?.username || '',
      role: saved?.role || '',        // 'admin' | 'normal'
      label: saved?.label || '',
    }
  },
  getters: {
    // 核心权限：管理员可编辑，普通账号不可
    canEdit: (s) => s.isLoggedIn && s.role === 'admin',
    isAdmin: (s) => s.role === 'admin',
  },
  actions: {
    login(username, password) {
      const acc = PRESET_ACCOUNTS.find(
        (a) => a.username === username && a.password === password
      )
      if (!acc) {
        throw new Error('用户名或密码错误')
      }
      this.isLoggedIn = true
      this.username = acc.username
      this.role = acc.role
      this.label = acc.label
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ username: acc.username, role: acc.role, label: acc.label })
      )
    },
    logout() {
      this.isLoggedIn = false
      this.username = ''
      this.role = ''
      this.label = ''
      localStorage.removeItem(STORAGE_KEY)
    },
  },
})

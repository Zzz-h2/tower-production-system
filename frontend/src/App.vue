<template>
  <div class="app-root">
    <header v-if="showHeader" class="app-header">
      <span class="app-logo">塔筒生产进度管控系统</span>
      <div class="app-user" v-if="auth.isLoggedIn">
        <span class="user-name">
          当前用户：{{ auth.username }}
          <el-tag size="small" :type="auth.isAdmin ? 'danger' : 'info'">
            {{ auth.isAdmin ? '管理员' : '普通账号' }}
          </el-tag>
        </span>
        <el-button size="small" @click="onLogout">退出登录</el-button>
      </div>
    </header>
    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './store/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const showHeader = computed(() => route.name !== 'login')

const onLogout = () => {
  auth.logout()
  router.replace('/login')
}
</script>

<style scoped>
.app-root { min-height: 100vh; background: #f4f6f9; }
.app-header {
  height: 56px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 24px; background: #1a365d; color: #fff;
}
.app-logo { font-weight: 600; font-size: 16px; }
.app-user { display: flex; align-items: center; gap: 12px; }
.user-name { font-size: 14px; display: flex; align-items: center; gap: 6px; }
</style>

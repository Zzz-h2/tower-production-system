<template>
  <div class="app-root">
    <header v-if="showHeader" class="app-header">
      <span class="app-logo">塔筒生产进度管控系统</span>
      <div class="app-user" v-if="auth.isLoggedIn">
        <span class="user-name">
          当前用户：{{ auth.username }}
          <el-tag size="small" :type="auth.isAdmin ? 'danger' : 'info'">
            {{ auth.label || (auth.isAdmin ? '管理员' : '普通账号') }}
          </el-tag>
          <el-tag v-if="auth.isBigArea && auth.bigAreaName" size="small" type="warning">
            {{ auth.bigAreaName === 'ALL' ? '全部大区' : auth.bigAreaName }}
          </el-tag>
        </span>
        <el-button size="small" @click="onLogout">退出登录</el-button>
      </div>
    </header>
    <router-view />
    <!-- 空闲超时倒计时弹窗：仅登录态渲染 -->
    <IdleWarningDialog
      v-if="auth.isLoggedIn"
      :visible="warningVisible"
      :remaining="remaining"
      :loading="extending"
      @extend="onExtend"
      @logout="onIdleLogout"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './store/auth'
import { useProjectStore } from './store/project'
import { useIdleLogout } from './composables/useIdleLogout'
import IdleWarningDialog from './components/IdleWarningDialog.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const projectStore = useProjectStore()
const showHeader = computed(() => route.name !== 'login')

// 会话空闲检测：仅在已登录时启用，登出/卸载时自动清理定时器与监听
const { remaining, warningVisible, extend, logoutNow } = useIdleLogout()
const extending = ref(false)

// 登录态下启动即拉取排产工序配置（单一来源，供里程碑设置等使用）
onMounted(() => {
  if (auth.isLoggedIn) projectStore.loadScheduleConfig()
})

/**
 * 页面从隐藏恢复可见（切换标签页、系统休眠唤醒）：主动校验一次 token，
 * 若后端已因空闲拒绝，交给 axios 401 拦截器统一登出并跳转。
 */
const onVisibilityChange = () => {
  if (document.visibilityState !== 'visible') return
  if (!auth.isLoggedIn) return
  auth.fetchMe().catch(() => {
    // 失败由 api 拦截器处理（401 登出跳转 / 其他错误 toast）
  })
}
onMounted(() => document.addEventListener('visibilitychange', onVisibilityChange))
onBeforeUnmount(() => document.removeEventListener('visibilitychange', onVisibilityChange))

const onExtend = async () => {
  if (extending.value) return
  extending.value = true
  try {
    // 续期失败时 useIdleLogout 内部会立即转登出流程
    await extend()
  } finally {
    extending.value = false
  }
}

const onIdleLogout = () => {
  logoutNow('manual')
}

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

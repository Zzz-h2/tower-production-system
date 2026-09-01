<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <h2 class="login-title">塔筒生产进度管控系统</h2>
      <p class="login-sub">请登录后进入系统</p>
      <el-form :model="form" @submit.prevent="onSubmit" label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名" clearable />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password @keyup.enter="onSubmit" />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="loading" @click="onSubmit">登录</el-button>
      </el-form>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="login-err" />
      <div class="login-tip">
        普通用户登陆请使用：大区负责人姓名+dq@123456<br />
        例如：张三+dq@123456<br />
        有任何问题请联系：张恒-15353262798
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../store/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const form = reactive({ username: '', password: '' })
const loading = ref(false)
const error = ref('')

const onSubmit = async () => {
  error.value = ''
  if (!form.username || !form.password) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success(`欢迎，${auth.label}`)
    // 登录后回到被拦截前想去的页面（默认项目列表）
    const redirect = route.query.redirect
    router.replace(typeof redirect === 'string' && redirect ? redirect : '/projects')
  } catch (e) {
    // 登录失败：优先展示后端 detail（如「用户名或密码错误」）
    const detail = e.response?.data?.detail
    error.value = typeof detail === 'string' && detail ? detail : (e.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f4f6f9; }
.login-card { width: 360px; padding: 8px 12px; }
.login-title { text-align: center; color: #1a365d; margin: 8px 0 4px; }
.login-sub { text-align: center; color: #718096; margin: 0 0 18px; }
.login-btn { width: 100%; margin-top: 8px; }
.login-err { margin-top: 12px; }
.login-tip { margin-top: 16px; font-size: 12px; color: #718096; line-height: 1.8; }
</style>

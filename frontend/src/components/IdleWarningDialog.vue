<template>
  <el-dialog
    :model-value="visible"
    title="会话即将超时"
    width="420px"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :append-to-body="true"
    class="idle-warning-dialog"
  >
    <div class="idle-warning-body">
      <p class="idle-warning-text">
        检测到您已长时间未操作，会话将在 <strong class="idle-warning-num">{{ remaining }}</strong> 秒后失效。
      </p>
      <p class="idle-warning-tip">如需继续操作，请点击「继续使用」。</p>
    </div>
    <template #footer>
      <div class="idle-warning-footer">
        <el-button type="primary" :loading="loading" @click="onExtend">继续使用</el-button>
        <el-button :disabled="loading" @click="onLogout">退出登录</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, default: false },
  remaining: { type: Number, default: 0 },
  // 续期请求进行中：由父组件控制（父组件持有 async 的 extend，emit 不会等待 Promise）
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['extend', 'logout'])

const onExtend = () => {
  emit('extend')
}

const onLogout = () => {
  emit('logout')
}
</script>

<style scoped>
.idle-warning-body { padding: 4px 2px 0; }
.idle-warning-text { margin: 0; font-size: 14px; line-height: 1.9; color: #2d3748; }
.idle-warning-num { color: #e53e3e; font-size: 18px; padding: 0 2px; }
.idle-warning-tip { margin: 6px 0 0; font-size: 12px; color: #718096; }
.idle-warning-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>

<style>
/* 弹窗标题/按钮沿用项目主色深蓝 #1a365d */
.idle-warning-dialog .el-dialog__header { border-bottom: 1px solid #e2e8f0; margin-right: 0; padding: 16px 20px; }
.idle-warning-dialog .el-dialog__title { color: #1a365d; font-size: 16px; font-weight: 600; }
.idle-warning-dialog .el-dialog__body { background: #ffffff; padding: 18px 20px; }
.idle-warning-dialog .el-dialog__footer { border-top: 1px solid #e2e8f0; padding: 12px 20px; background: #f4f6f9; }
</style>

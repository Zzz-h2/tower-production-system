<template>
  <div class="block-card import-card">
    <div class="block-header">
      <span class="icon"></span>
      <span class="block-title">📥 导入排产计划</span>
      <span class="block-subtitle">支持 .xlsx / .xls，将按 (工序, 计划日期) 聚合生成节点计划</span>
    </div>
    <el-upload
      drag
      :accept="'.xlsx,.xls'"
      :show-file-list="false"
      :http-request="!props.disabled ? doUpload : () => {}"
      :disabled="props.disabled || uploading"
    >
      <div class="upload-hint" :class="{ 'is-disabled': props.disabled }">
        <div style="font-size:20px; margin-bottom:6px;">📂</div>
        <div style="font-weight:600;">
          {{ props.disabled ? '仅管理员可导入排产计划' : '点击或拖拽 Excel 文件到此处' }}
        </div>
        <div v-if="!props.disabled" style="font-size:12px; color:#64748b; margin-top:4px;">上传后立即解析入库，覆盖该项目原有节点计划</div>
      </div>
    </el-upload>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importSchedule } from '../api/node'

const props = defineProps({
  pid: { type: String, required: true },
  disabled: { type: Boolean, default: false },   // 外部控制是否禁用（普通账号仅管理员可导入）
})
const emit = defineEmits(['imported'])

const uploading = ref(false)

async function doUpload({ file }) {
  uploading.value = true
  try {
    const res = await importSchedule(props.pid, file)
    ElMessage.success(res.message || '导入成功')
    const warnText = (res.warnings || []).map((w) => `⚠️ ${w}`).join('<br/>')
    if (warnText) {
      ElMessage.warning({ message: warnText, duration: 6000, dangerouslyUseHTMLString: true })
    }
    emit('imported')   // 父组件刷新节点计划总览
  } catch (e) {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    uploading.value = false
  }
}
</script>

<style scoped>
.import-card { margin-bottom: 16px; }
.upload-hint { padding: 18px 0; color: #1a365d; }
.is-disabled {
  color: #a0aec0 !important;
  cursor: not-allowed;
}
:deep(.el-upload.is-disabled) {
  cursor: not-allowed;
}
:deep(.el-upload.is-disabled .el-upload-dragger) {
  border-color: #e2e8f0 !important;
  background: #f7fafc !important;
}
</style>

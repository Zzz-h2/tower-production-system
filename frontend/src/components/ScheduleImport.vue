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
      :http-request="doUpload"
      :disabled="uploading"
    >
      <div class="upload-hint">
        <div style="font-size:20px; margin-bottom:6px;">📂</div>
        <div style="font-weight:600;">点击或拖拽 Excel 文件到此处</div>
        <div style="font-size:12px; color:#64748b; margin-top:4px;">上传后立即解析入库，覆盖该项目原有节点计划</div>
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
</style>

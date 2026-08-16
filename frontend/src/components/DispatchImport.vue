<template>
  <div class="dispatch-import">
    <el-upload
      drag
      :accept="'.xlsx,.xls'"
      :show-file-list="false"
      :http-request="doUpload"
      :disabled="uploading"
    >
      <div class="upload-hint">
        <div style="font-size:20px; margin-bottom:6px;">📂</div>
        <div style="font-weight:600;">点击或拖拽调度令 Excel 文件到此处</div>
        <div style="font-size:12px; color:#64748b; margin-top:4px;">
          将自动建项目、初始化 12 道工序并计算风险（必填：项目名称/钢塔厂家/本月计划/交付负责人）
        </div>
      </div>
    </el-upload>

    <div v-if="result" class="result-box">
      <el-alert
        :title="result.message"
        type="success"
        :closable="false"
        show-icon
      />
      <div class="result-detail">
        成功 <b>{{ result.success }}</b> 条 · 跳过 <b>{{ result.skipped }}</b> 条
      </div>
      <ul v-if="result.errors && result.errors.length" class="error-list">
        <li v-for="(e, i) in result.errors" :key="i">{{ e }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importDispatch } from '../api/node'

const emit = defineEmits(['imported'])

const uploading = ref(false)
const result = ref(null)

async function doUpload({ file }) {
  uploading.value = true
  result.value = null
  try {
    const res = await importDispatch(file)
    result.value = res
    ElMessage.success(res.message || '导入完成')
    emit('imported')   // 父组件刷新列表与看板
  } catch (e) {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    uploading.value = false
  }
}
</script>

<style scoped>
.dispatch-import { padding: 4px 0; }
.upload-hint { padding: 18px 0; color: #1a365d; }
.result-box { margin-top: 12px; }
.result-detail { margin: 8px 0; font-size: 13px; color: #64748b; }
.error-list { margin: 6px 0 0; padding-left: 18px; color: #e53e3e; font-size: 12px; }
</style>

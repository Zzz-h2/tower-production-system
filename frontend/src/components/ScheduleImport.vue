<template>
  <div class="block-card import-card">
    <div class="block-header">
      <span class="icon"></span>
      <span class="block-title">📥 导入排产计划</span>
      <span class="block-subtitle">支持 .xlsx / .xls，将按 (工序, 计划日期) 聚合生成节点计划</span>
    </div>

    <!-- 排产归属月（v7.2）：默认取页面当前共享月份，可手动改。
         该月份决定「本月是否上传过排产」的判定，以及被替换旧行的归档归属。 -->
    <div class="month-row">
      <span class="month-label">本次排产归属月</span>
      <el-date-picker
        v-model="planMonth"
        type="month"
        value-format="YYYY-MM"
        placeholder="选择归属月（默认当前月）"
        :disabled="props.disabled || uploading"
        class="month-picker"
        :clearable="false"
      />
      <span class="month-hint">导入后该项目在「{{ planMonth || '当前月' }}」将被标记为已上传排产</span>
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
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { importSchedule } from '../api/node'
import { useProjectStore } from '../store/project'

const props = defineProps({
  pid: { type: String, required: true },
  disabled: { type: Boolean, default: false },   // 外部控制是否禁用（普通账号仅管理员可导入）
  manager: { type: String, default: '' },          // 多负责人 v6.0：本次导入归属的负责人
  managerMonthlyPlan: { type: [Number, String], default: 0 },  // 该负责人申报的本月计划数
})
const emit = defineEmits(['imported'])

const store = useProjectStore()
const uploading = ref(false)

// 默认归属月 = 页面当前共享月份（store.filters.month，未设置则为当前自然月）
function currentMonth() {
  if (store.filters.month) return store.filters.month
  if (typeof store.ensureMonth === 'function') {
    store.ensureMonth()
    return store.filters.month || ''
  }
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}
const planMonth = ref(currentMonth())
// 本组件在「项目详情-节点计划」页是**常驻挂载**的。若只在挂载时取一次全局月份，
// 用户之后切换页面月份时选择器不跟随 → 排产被归到错误的月份。
// 故：全局月份变化 → 选择器同步跟随；同一个月上下文内用户的手动改动保持不变。
watch(() => store.filters.month, (m) => {
  if (m) planMonth.value = m
})

async function doUpload({ file }) {
  uploading.value = true
  try {
    const res = await importSchedule(
      props.pid,
      file,
      props.manager || undefined,
      props.managerMonthlyPlan || 0,
      planMonth.value || undefined,
    )
    ElMessage.success(res.message || '导入成功')
    // 大文件兜底：warnings 可能多达数百条（62 套 × 11 工序），巨型 toast 会糊满整页导致"页面显示错误"。
    // 只展示前 10 条 + 汇总条数，完整明细在浏览器控制台可查。
    const warnings = res.warnings || []
    if (warnings.length) {
      const MAX_SHOW = 10
      const shown = warnings.slice(0, MAX_SHOW).map((w) => `⚠️ ${w}`)
      if (warnings.length > MAX_SHOW) {
        shown.push(`…等共 ${warnings.length} 条提示（其余从略，详见控制台）`)
        console.warn('[ScheduleImport] 完整提示列表:', warnings)
      }
      ElMessage.warning({
        message: shown.join('<br/>'),
        duration: 8000,
        showClose: true,
        dangerouslyUseHTMLString: true,
      })
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
.month-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: #f7fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.month-label { font-size: 13px; font-weight: 600; color: #1a365d; }
.month-picker { width: 170px; }
.month-hint { font-size: 12px; color: #718096; }
</style>

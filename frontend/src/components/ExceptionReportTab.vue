<template>
  <div class="exception-tab">
    <el-form :model="form" label-width="90px" size="small">
      <el-form-item label="责任分类">
        <el-select v-model="form.responsibility_category" placeholder="请选择" style="width:100%;">
          <el-option label="供应商" value="供应商" />
          <el-option label="内部生产" value="内部生产" />
          <el-option label="物流运输" value="物流运输" />
          <el-option label="天气/不可抗力" value="天气/不可抗力" />
          <el-option label="其他" value="其他" />
        </el-select>
      </el-form-item>
      <el-form-item label="异常原因">
        <el-input v-model="form.reason_detail" type="textarea" :rows="3" placeholder="请详细描述异常原因" />
      </el-form-item>
      <el-form-item label="处理人">
        <el-input v-model="form.handler" placeholder="请输入处理人姓名" />
      </el-form-item>
      <el-form-item label="计划关闭">
        <el-date-picker v-model="form.planned_close_date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width:100%;" />
      </el-form-item>
      <el-form-item label="处理措施">
        <el-input v-model="form.measures" type="textarea" :rows="3" placeholder="请输入处理措施" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :disabled="!auth.canFill" @click="onSubmit">提交异常</el-button>
      </el-form-item>
    </el-form>

    <div v-if="exceptionList.length" class="exception-history">
      <div class="history-title">历史异常记录（{{ exceptionList.length }}）</div>
      <el-timeline>
        <el-timeline-item v-for="e in exceptionList" :key="e.id" :type="e.status === 'closed' ? 'success' : 'warning'">
          <div class="exc-item">
            <span class="exc-status" :class="e.status">{{ statusText[e.status] }}</span>
            <span class="exc-category">{{ e.responsibility_category }}</span>
            <p>{{ e.reason_detail }}</p>
            <p v-if="e.handler">处理人：{{ e.handler }}</p>
            <p v-if="e.planned_close_date">计划关闭：{{ e.planned_close_date }}</p>
            <p v-if="e.measures">处理措施：{{ e.measures }}</p>
            <el-button v-if="e.status !== 'closed'" size="small" type="success" @click="onClose(e.id)">关闭</el-button>
          </div>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { createException, listExceptionsByNode, updateException } from '../api/exception'
import { useAuthStore } from '../store/auth'

const props = defineProps({
  pid: { type: String, default: '' },
  nodeId: { type: Number, default: null },
  // v8.0 异常精确到套：父组件（ProcessDetailDialog）二级「套」下拉的选中值。
  // null = 整套/不指定（老口径，后端走中位数代表值反推）；数字 = 精确到某一套。
  setSeq: { type: Number, default: null },
  setD0: { type: String, default: '' },
})
const emit = defineEmits(['changed'])
const auth = useAuthStore() // 提报权限：admin 或大区账号（大区仅本大区，后端已隔离）

const form = ref({
  responsibility_category: '',
  reason_detail: '',
  handler: '',
  planned_close_date: '',
  measures: '',
})
const exceptionList = ref([])
const statusText = { pending: '待处理', processing: '处理中', closed: '已关闭' }

async function load() {
  if (!props.nodeId) {
    exceptionList.value = []
    return
  }
  const res = await listExceptionsByNode(props.nodeId)
  exceptionList.value = res.items || []
}

/**
 * 构造提交载荷。
 *
 * 「计划关闭」是可选日期（后端 schema 为 Optional[date]），但 el-date-picker 未选值时
 * form.planned_close_date 是空串 ''，直接提交会被后端按 date 解析而报
 * 422（date_from_datetime_parsing: input is too short）。
 * 故在此处把空串归一为 null（口径与 AlertList「编辑异常」一致：
 * `planned_close_date: editForm.planned_close_date || null`）。
 * 刻意**不改 form 的初始值**：date-picker 的双向绑定依赖字符串/Date，
 * 改初始值为 null 可能影响清空与回显行为。
 *
 * @returns {{responsibility_category: string, reason_detail: string, handler: string,
 *            planned_close_date: string|null, measures: string}} 提交载荷
 */
function buildPayload() {
  return {
    ...form.value,
    // 本表单唯一的日期字段；其它字段（责任分类/异常原因/处理人/处理措施）均为文本，
    // 无空串→日期解析问题，保持原值直传（空串即视为未填，业务口径不变）。
    planned_close_date: form.value.planned_close_date || null,
    // v8.0 异常精确到套：未选套（null/undefined）时显式传 null，
    // 后端 schema 为 Optional，历史异常与「整套/不指定」口径一致（三档反推第③档）。
    set_seq: props.setSeq ?? null,
    set_d0: props.setD0 || null,
  }
}

async function onSubmit() {
  if (!props.nodeId) {
    ElMessage.warning('请先选择节点')
    return
  }
  if (!form.value.responsibility_category || !form.value.reason_detail) {
    ElMessage.warning('请填写责任分类和异常原因')
    return
  }
  await createException(props.pid, props.nodeId, buildPayload())
  ElMessage.success('异常提报成功')
  form.value = { responsibility_category: '', reason_detail: '', handler: '', planned_close_date: '', measures: '' }
  load()
  emit('changed')   // 通知父组件触发预警列表刷新
}

async function onClose(id) {
  await updateException(id, { status: 'closed' })
  ElMessage.success('异常已关闭')
  load()
  emit('changed')
}

watch(() => props.nodeId, load)
onMounted(load)
</script>

<style scoped>
.exception-tab { padding: 16px; }
.exception-history { margin-top: 24px; }
.history-title { font-weight: 600; margin-bottom: 12px; color: #1a365d; }
.exc-item { font-size: 13px; color: #4a5568; }
.exc-item p { margin: 4px 0; }
.exc-status { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; margin-right: 8px; }
.exc-status.pending { background: #fffaf0; color: #f6ad55; }
.exc-status.processing { background: #e0f2fe; color: #0ea5e9; }
.exc-status.closed { background: #f0fff4; color: #38a169; }
.exc-category { color: #718096; }
</style>

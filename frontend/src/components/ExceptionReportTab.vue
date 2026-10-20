<template>
  <div class="exception-tab">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" size="small">
      <el-form-item label="责任分类" prop="responsibility_category">
        <el-select v-model="form.responsibility_category" placeholder="请选择" style="width:100%;">
          <el-option label="供应商" value="供应商" />
          <el-option label="内部生产" value="内部生产" />
          <el-option label="物流运输" value="物流运输" />
          <el-option label="天气/不可抗力" value="天气/不可抗力" />
          <el-option label="其他" value="其他" />
        </el-select>
      </el-form-item>
      <el-form-item label="异常原因" prop="reason_detail">
        <el-input v-model="form.reason_detail" type="textarea" :rows="3" placeholder="请详细描述异常原因" />
      </el-form-item>
      <el-form-item label="处理人">
        <el-input v-model="form.handler" placeholder="请输入处理人姓名" />
      </el-form-item>
      <!-- 计划关闭日（2026-11）：改为**必填**。到期未关闭 → 暂停自动失效、恢复逾期判定。 -->
      <el-form-item label="计划关闭" prop="planned_close_date" required>
        <el-date-picker
          v-model="form.planned_close_date"
          value-format="YYYY-MM-DD"
          placeholder="选择日期（必填）"
          :disabled-date="disabledPastDate"
          style="width:100%;"
        />
        <div class="field-hint">
          到期未关闭 → 该异常暂停自动失效，下游工序恢复按原计划日判逾期（不等于关闭）。
        </div>
      </el-form-item>
      <el-form-item label="处理措施">
        <el-input v-model="form.measures" type="textarea" :rows="3" placeholder="请输入处理措施" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :disabled="!auth.canFill" @click="onSubmit">提交异常</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createException } from '../api/exception'
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
const formRef = ref(null)
// 计划关闭日（2026-11）：必填 + 不得早于今天。
// 前后端同一条口径：后端 schemas/exception.py 的 field_validator 会再次拒绝过去日期，
// 前端置灰只是提前拦一次，避免无谓请求。
const rules = {
  responsibility_category: [{ required: true, message: '请选择责任分类', trigger: 'change' }],
  reason_detail: [{ required: true, message: '请填写异常原因', trigger: 'blur' }],
  planned_close_date: [
    { required: true, message: '请选择计划关闭日期（必填）', trigger: 'change' },
    {
      validator: (rule, value, callback) => {
        if (!value) return callback()
        const today = new Date()
        today.setHours(0, 0, 0, 0)
        const picked = new Date(`${value}T00:00:00`)
        if (picked < today) return callback(new Error('计划关闭日期不能早于今天'))
        return callback()
      },
      trigger: 'change',
    },
  ],
}

// el-date-picker 的 disabled-date：今天之前的日期置灰不可选
function disabledPastDate(d) {
  const day = new Date(d)
  day.setHours(0, 0, 0, 0)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return day < today
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
  // 计划关闭日必填 + 不得早于今天（表单校验，失败直接返回并高亮错误项）
  if (formRef.value) {
    const ok = await formRef.value.validate().catch(() => false)
    if (!ok) return
  }
  if (!form.value.responsibility_category || !form.value.reason_detail) {
    ElMessage.warning('请填写责任分类和异常原因')
    return
  }
  if (!form.value.planned_close_date) {
    ElMessage.warning('请填写计划关闭日期（必填）')
    return
  }
  await createException(props.pid, props.nodeId, buildPayload())
  ElMessage.success('异常提报成功')
  form.value = { responsibility_category: '', reason_detail: '', handler: '', planned_close_date: '', measures: '' }
  formRef.value?.clearValidate()
  // 历史记录列表已于 2026-11 移除（改由 ExceptionRecordTable 展示），
  // 此事件仅用于通知父级重载异常记录表格 / 预警列表 / KPI。
  emit('changed')
}
</script>

<style scoped>
.exception-tab { padding: 16px; }
.field-hint { font-size: 11px; color: #94a3b8; line-height: 1.6; margin-top: 2px; }
</style>

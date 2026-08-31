<template>
  <el-dialog
    :model-value="modelValue"
    :title="`手动完成：${project?.project_name || ''}`"
    width="560px"
    :close-on-click-modal="false"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="mc-dialog-body">
      <el-form ref="formRef" :model="form" label-width="90px" @submit.prevent>
        <el-form-item label="完成套数" required>
          <el-input-number
            v-model="form.qty"
            :min="1"
            :precision="0"
            :step="1"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="完成时间" required>
          <el-date-picker
            v-model="form.date"
            type="date"
            value-format="YYYY-MM-DD"
            format="YYYY-MM-DD"
            :clearable="false"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <div class="mc-summary">
        合同总数 <b>{{ project?.contract_count || 0 }}</b> 套 · 已完成 <b>{{ project?.completed_sets || 0 }}</b> 套 · 剩余未完成 <b>{{ project?.remaining_sets || 0 }}</b> 套
      </div>
      <div class="mc-hint">完成套数将计入该项目「附件安装」工序的已完成数量，并同步刷新进度与排名统计。同日重复提交会覆盖当日记录。</div>
    </div>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { manualComplete } from '../api/node'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  project: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'completed'])

// 本地时区「今天」（勿用 toISOString，东八区凌晨会偏前一天）
function fmtToday() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

const formRef = ref(null)
const form = ref({ qty: 1, date: fmtToday() })
const submitting = ref(false)

const canSubmit = computed(() => Number.isInteger(Number(form.value.qty)) && Number(form.value.qty) > 0 && !!form.value.date)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    form.value = { qty: 1, date: fmtToday() }
    formRef.value?.clearValidate?.()
  },
)

async function submit() {
  if (!props.project) return
  if (!canSubmit.value) {
    ElMessage.warning('请填写正整数完成套数')
    return
  }
  submitting.value = true
  try {
    const res = await manualComplete(props.project.id, {
      complete_qty: form.value.qty,
      complete_date: form.value.date,
    })
    ElMessage.success(res.message || '✅ 已手动完成')
    emit('completed')
    emit('update:modelValue', false)
  } catch (e) {
    // 400/403 已由 axios 拦截器统一 toast；这里只保证弹窗不关、可重试
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.mc-dialog-body { padding: 4px 0 8px; }
.mc-summary {
  margin-top: 2px;
  font-size: 13px;
  color: #4a5568;
  background: #f7fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
}
.mc-summary b { color: #1a365d; font-variant-numeric: tabular-nums; }
.mc-hint { margin-top: 10px; font-size: 12px; color: #718096; line-height: 1.6; }
</style>

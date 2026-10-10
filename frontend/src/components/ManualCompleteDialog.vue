<template>
  <el-dialog
    :model-value="modelValue"
    :title="`手动完成 / 预计完成：${project?.project_name || ''}`"
    width="760px"
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
        <el-form-item v-if="managers.length > 1" label="负责人" required>
          <el-select
            v-model="form.manager"
            placeholder="选择本次完成归属的负责人"
            style="width: 100%"
          >
            <el-option v-for="m in managers" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="mc-summary">
        合同总数 <b>{{ summary.contract_count }}</b> 套 · 已完成 <b>{{ summary.completed_sets }}</b> 套 · 剩余未完成 <b>{{ summary.remaining_sets }}</b> 套
      </div>
      <div class="mc-hint">
        完成套数计入该项目「附件安装」工序的已完成数量，并同步刷新进度与排名统计。<br/>
        <b>同一天重复提交 = 覆盖该日记录</b>（想减少已录成套数：点下方记录的「修改」把套数改小，或直接「删除」整条）。
      </div>

      <!-- 已录入记录（2026-10-10 新增）：可见 + 可改小 + 可删除，解决「只能加不能减」 -->
      <div class="mc-records" v-loading="loadingRecords">
        <div class="mc-records-head">
          <span class="mc-records-title">已录入的手动完成记录</span>
          <span class="mc-records-tip" v-if="editing">正在修改 {{ form.date }} 这条，改完点「保存」覆盖</span>
          <span class="mc-records-tip" v-else>共 {{ records.length }} 条（按完成时间倒序）</span>
        </div>
        <el-table :data="records" size="small" max-height="190" empty-text="暂无手动完成记录">
          <el-table-column label="完成时间" prop="plan_date" width="108" />
          <el-table-column label="完成套数" width="88">
            <template #default="{ row }">
              <b class="mc-num">{{ row.actual_qty || row.plan_qty || 0 }}</b>
            </template>
          </el-table-column>
          <el-table-column label="完成月" width="82">
            <template #default="{ row }">
              <span class="mc-month">{{ (row.plan_date || '').slice(0, 7) || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="负责人" prop="manager" min-width="80">
            <template #default="{ row }">{{ row.manager || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="118" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="editRow(row)">修改</el-button>
              <el-button link type="danger" size="small" @click="removeRow(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 预计完成登记（2026-10-10 新增）：即将完成但还没有排产计划的项目 -->
      <div class="mc-records mc-forecast">
        <div class="mc-records-head">
          <span class="mc-records-title">📅 预计完成登记（未排产、即将完成的项目）</span>
          <span class="mc-records-tip">记录「预计哪天完成、当天多少套」；不改变上面的已完成套数</span>
        </div>
        <el-form :model="fform" label-width="96px" class="mc-forecast-form" @submit.prevent>
          <el-form-item label="预计完成日期">
            <el-date-picker
              v-model="fform.date"
              type="date"
              value-format="YYYY-MM-DD"
              format="YYYY-MM-DD"
              :clearable="false"
              style="width: 148px"
            />
          </el-form-item>
          <el-form-item label="预计完成套数">
            <el-input-number v-model="fform.qty" :min="1" :precision="0" :step="1" style="width: 118px" />
          </el-form-item>
          <el-form-item v-if="managers.length > 1" label="负责人">
            <el-select v-model="fform.manager" placeholder="选择负责人" style="width: 128px">
              <el-option v-for="m in managers" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" plain :loading="forecastSaving" @click="saveForecast">
              登记预计完成
            </el-button>
          </el-form-item>
        </el-form>
        <el-table :data="forecasts" size="small" max-height="150" empty-text="暂无预计完成登记">
          <el-table-column label="预计完成日期" prop="forecast_date" width="118" />
          <el-table-column label="预计套数" width="88">
            <template #default="{ row }">
              <b class="mc-num">{{ row.forecast_qty }}</b>
            </template>
          </el-table-column>
          <el-table-column label="预计完成月" width="96">
            <template #default="{ row }">
              <span class="mc-month">{{ (row.forecast_date || '').slice(0, 7) || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="负责人" prop="manager" min-width="80">
            <template #default="{ row }">{{ row.manager || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="118" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="editForecast(row)">修改</el-button>
              <el-button link type="danger" size="small" @click="removeForecast(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  manualComplete,
  fetchManualCompletes,
  deleteManualComplete,
  fetchCompletionForecasts,
  saveCompletionForecast,
  deleteCompletionForecast,
} from '../api/node'

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

// 把「交付负责人」按 '/'（含全角'／'）拆分为负责人列表（去空+去重+保序），对齐后端 split_managers
function splitManagers(dp) {
  if (!dp) return []
  const seen = new Set()
  const out = []
  for (const part of String(dp).split(/[/／]/)) {
    const s = part.trim()
    if (s && !seen.has(s)) {
      seen.add(s)
      out.push(s)
    }
  }
  return out
}

const formRef = ref(null)
const form = ref({ qty: 1, date: fmtToday(), manager: null })
const submitting = ref(false)
const records = ref([])
const loadingRecords = ref(false)
const editing = ref(false)      // 是否处于「修改已有记录」状态（仅影响提示文案）
// 概览数字以接口为准（项目级合同口径），避免用列表行里「本月口径」的数字造成误解
const summary = ref({ contract_count: 0, completed_sets: 0, remaining_sets: 0 })

// 「预计完成」登记（2026-10-10 新增）
const forecasts = ref([])
const forecastSaving = ref(false)
const fform = ref({ qty: 1, date: fmtToday(), manager: null })

const forecastCanSubmit = computed(
  () =>
    Number.isInteger(Number(fform.value.qty)) &&
    Number(fform.value.qty) > 0 &&
    !!fform.value.date &&
    (managers.value.length <= 1 || !!fform.value.manager),
)

// 多负责人项目才需要前端选择归属负责人；单负责人后端会自动取 delivery_person
const managers = computed(() => splitManagers(props.project?.delivery_person))

const canSubmit = computed(
  () =>
    Number.isInteger(Number(form.value.qty)) &&
    Number(form.value.qty) > 0 &&
    !!form.value.date &&
    (managers.value.length <= 1 || !!form.value.manager),
)

async function loadRecords() {
  if (!props.project?.id) return
  loadingRecords.value = true
  try {
    const res = await fetchManualCompletes(props.project.id)
    records.value = res.items || []
    summary.value = {
      contract_count: Number(res.contract_count || 0),
      completed_sets: Number(res.completed_sets || 0),
      remaining_sets: Number(res.remaining_sets || 0),
    }
  } catch (e) {
    records.value = []
  } finally {
    loadingRecords.value = false
  }
}

function resetForm() {
  form.value = { qty: 1, date: fmtToday(), manager: null }
  editing.value = false
  formRef.value?.clearValidate?.()
}

// ---------- 预计完成登记 ----------
async function loadForecasts() {
  if (!props.project?.id) return
  try {
    const res = await fetchCompletionForecasts(props.project.id)
    forecasts.value = res.items || []
  } catch (e) {
    forecasts.value = []
  }
}

function resetForecastForm() {
  fform.value = { qty: 1, date: fmtToday(), manager: null }
}

// 修改某条预计登记：回填表单 → 再点「登记预计完成」即覆盖同日同负责人的那条
function editForecast(row) {
  fform.value = {
    qty: Number(row.forecast_qty || 1),
    date: String(row.forecast_date || '').slice(0, 10) || fmtToday(),
    manager: row.manager || null,
  }
}

async function saveForecast() {
  if (!props.project) return
  if (!forecastCanSubmit.value) {
    ElMessage.warning(managers.value.length > 1 ? '请选择归属的负责人' : '请填写预计完成日期与正整数套数')
    return
  }
  forecastSaving.value = true
  try {
    const payload = {
      forecast_date: fform.value.date,
      forecast_qty: fform.value.qty,
    }
    if (managers.value.length > 1 && fform.value.manager) {
      payload.manager = fform.value.manager
    }
    const res = await saveCompletionForecast(props.project.id, payload)
    ElMessage.success(res.message || '✅ 已登记预计完成')
    resetForecastForm()
    await loadForecasts()
    emit('completed')
  } catch (e) {
    // 400/403 已由拦截器提示
  } finally {
    forecastSaving.value = false
  }
}

async function removeForecast(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${String(row.forecast_date || '').slice(0, 10)} 这条预计完成登记（${row.forecast_qty} 套）？`,
      '删除预计完成登记',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch (e) {
    return
  }
  try {
    await deleteCompletionForecast(props.project.id, row.id)
    ElMessage.success('✅ 已删除该预计完成登记')
    await loadForecasts()
    emit('completed')
  } catch (e) {
    // 错误已由拦截器提示
  }
}

// 修改某条记录：把日期/套数/负责人回填到表单 → 保存即覆盖该日记录（可改小 = 减少）
function editRow(row) {
  form.value = {
    qty: Number(row.actual_qty || row.plan_qty || 1),
    date: String(row.plan_date || '').slice(0, 10) || fmtToday(),
    manager: row.manager || null,
  }
  editing.value = true
  formRef.value?.clearValidate?.()
}

// 删除某条记录：确认后整条撤销（同时清理其实际完成量）
async function removeRow(row) {
  const qty = Number(row.actual_qty || row.plan_qty || 0)
  try {
    await ElMessageBox.confirm(
      `确认删除 ${String(row.plan_date || '').slice(0, 10)} 这条手动完成记录（${qty} 套）？删除后该套数将从已完成中扣除。`,
      '删除手动完成记录',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch (e) {
    return   // 用户取消
  }
  try {
    await deleteManualComplete(props.project.id, row.node_plan_id)
    ElMessage.success('✅ 已删除该手动完成记录')
    if (form.value.date === String(row.plan_date || '').slice(0, 10)) resetForm()
    await loadRecords()
    emit('completed')       // 通知父级刷新总览/列表
  } catch (e) {
    // 错误已由拦截器提示
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    resetForm()
    resetForecastForm()
    summary.value = {
      contract_count: Number(props.project?.contract_count || 0),
      completed_sets: Number(props.project?.completed_sets || 0),
      remaining_sets: Number(props.project?.remaining_sets || 0),
    }
    loadRecords()
    loadForecasts()
  },
)

async function submit() {
  if (!props.project) return
  if (!canSubmit.value) {
    ElMessage.warning(managers.value.length > 1 ? '请选择归属的负责人' : '请填写正整数完成套数')
    return
  }
  submitting.value = true
  try {
    const payload = {
      complete_qty: form.value.qty,
      complete_date: form.value.date,
    }
    // 多负责人项目：显式带上选择的负责人，否则后端按 400 拒绝
    if (managers.value.length > 1 && form.value.manager) {
      payload.manager = form.value.manager
    }
    const res = await manualComplete(props.project.id, payload)
    ElMessage.success(res.message || '✅ 已手动完成')
    // 保存后不关闭弹窗：留在记录列表里，方便核对 / 立刻改小或删除
    resetForm()
    await loadRecords()
    emit('completed')
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
.mc-hint b { color: #c05621; }

/* 已录入记录表（可见 + 可改小 + 可删） */
.mc-records {
  margin-top: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.mc-records-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: #f7fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-wrap: wrap;
}
.mc-records-title { font-size: 13px; font-weight: 600; color: #1a365d; }
.mc-records-tip { font-size: 12px; color: #718096; }
.mc-num { color: #1a365d; font-variant-numeric: tabular-nums; }
.mc-month { font-size: 12px; color: #3182ce; }

/* 预计完成登记区（2026-10-10 新增）：与「已完成」区分开的浅蓝底 */
.mc-forecast { border-color: #bee3f8; }
.mc-forecast .mc-records-head { background: #ebf8ff; border-bottom-color: #bee3f8; }
.mc-forecast .mc-records-title { color: #2c5282; }
.mc-forecast-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  padding: 10px 12px 0;
}
.mc-forecast-form :deep(.el-form-item) { margin-bottom: 8px; }
</style>

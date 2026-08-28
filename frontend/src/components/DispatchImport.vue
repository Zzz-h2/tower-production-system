<template>
  <div class="dispatch-import">
    <!-- 步骤一：选择文件 -->
    <el-upload
      v-if="step === 1"
      drag
      :accept="'.xlsx,.xls'"
      :show-file-list="false"
      :http-request="doPreview"
      :disabled="previewing || disabled"
    >
      <div class="upload-hint">
        <div style="font-size:20px; margin-bottom:6px;">📂</div>
        <div style="font-weight:600;">
          {{ previewing ? '正在解析文件…' : '点击或拖拽调度令 Excel 文件到此处' }}
        </div>
        <div style="font-size:12px; color:#64748b; margin-top:4px;">
          （必填：项目名称/钢塔厂家/本月计划出品/交付负责人）
        </div>
      </div>
    </el-upload>

    <!-- 步骤二：字段映射确认 -->
    <div v-else class="mapping-panel">
      <div class="mapping-head">
        <span class="file-name">📄 {{ fileName }}</span>
        <span class="col-count">共 {{ rows.length }} 列</span>
      </div>

      <!-- 必填字段状态 -->
      <div class="field-status">
        <span class="status-label">必填字段：</span>
        <el-tag
          v-for="f in requiredFields"
          :key="f.field"
          :type="missingFields.includes(f.field) ? 'danger' : 'success'"
          size="small"
          effect="light"
          class="status-tag"
        >
          {{ f.label }}
          <span v-if="missingFields.includes(f.field)" class="missing-flag">未映射</span>
        </el-tag>
      </div>

      <el-alert
        v-if="missingFields.length"
        type="error"
        :closable="false"
        show-icon
        class="tip-alert"
      >
        <template #title>
          以下必填字段尚未关联任何 Excel 列：
          <b style="color:#e53e3e;">{{ missingLabels.join('、') }}</b>
          ，请在右侧下拉框中选择对应列后再导入
        </template>
      </el-alert>

      <el-alert
        v-if="duplicatedFields.length"
        type="warning"
        :closable="false"
        show-icon
        class="tip-alert"
      >
        <template #title>
          <span v-for="d in duplicatedFields" :key="d.field" class="dup-item">
            系统字段「{{ d.label }}」被 {{ d.columns.length }} 列同时选择（{{ d.columns.join('、') }}），最终生效的是最左侧那一列
          </span>
        </template>
      </el-alert>

      <!-- 映射表 -->
      <el-table :data="rows" border size="small" max-height="380" class="mapping-table">
        <el-table-column prop="header" label="Excel 表头" min-width="180" show-overflow-tooltip />
        <el-table-column label="样例值（前5条有效数据）" min-width="220">
          <template #default="{ row }">
            <span v-if="row.samples" class="sample-text">{{ row.samples }}</span>
            <span v-else class="sample-empty">（该列无有效数据）</span>
          </template>
        </el-table-column>
        <el-table-column label="映射到系统字段" width="220">
          <template #default="{ row }">
            <el-select
              v-model="row.field"
              placeholder="不映射"
              size="small"
              clearable
              style="width:100%"
            >
              <el-option label="不映射" value="" />
              <el-option
                v-for="f in systemFields"
                :key="f.field"
                :value="f.field"
              >
                <span :class="{ 'required-option': f.required }">{{ f.label }}</span>
                <span v-if="f.required" class="required-star">*</span>
              </el-option>
            </el-select>
          </template>
        </el-table-column>
      </el-table>

      <div class="actions">
        <el-button size="small" :disabled="importing" @click="resetAll">重新选择文件</el-button>
        <el-button
          type="primary"
          size="small"
          :loading="importing"
          :disabled="missingFields.length > 0"
          @click="doImport"
        >
          确认导入
        </el-button>
      </div>
    </div>

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
      <div v-if="step === 2" style="margin-top:10px;">
        <el-button size="small" @click="resetAll">继续导入其他文件</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importDispatch, previewDispatch } from '../api/node'

const emit = defineEmits(['imported'])

defineProps({
  disabled: { type: Boolean, default: false },  // 普通账号禁用导入（按钮级权限）
})

const step = ref(1)            // 1=选文件 2=确认映射
const previewing = ref(false)
const importing = ref(false)
const result = ref(null)

const fileName = ref('')
const pickedFile = ref(null)   // 预览用的原始 File，导入时复用
const systemFields = ref([])
const rows = ref([])           // [{ header, samples, field }]

const requiredFields = computed(() => systemFields.value.filter((f) => f.required))

// 已建立映射的系统字段 → Excel 列
const fieldToColumns = computed(() => {
  const map = {}
  for (const r of rows.value) {
    if (!r.field) continue
    ;(map[r.field] = map[r.field] || []).push(r.header)
  }
  return map
})

// 必填字段中未被任何列选中的
const missingFields = computed(() =>
  requiredFields.value.filter((f) => !fieldToColumns.value[f.field]).map((f) => f.field),
)
const missingLabels = computed(() =>
  requiredFields.value.filter((f) => missingFields.value.includes(f.field)).map((f) => f.label),
)

// 同一系统字段被多列选中（允许提交，仅提示）
const duplicatedFields = computed(() => {
  const labelOf = (field) => (systemFields.value.find((f) => f.field === field) || {}).label || field
  return Object.entries(fieldToColumns.value)
    .filter(([, cols]) => cols.length > 1)
    .map(([field, cols]) => ({ field, label: labelOf(field), columns: cols }))
})

// 提交给后端的映射：{ Excel列名: 系统字段名 }
const mappingPayload = computed(() => {
  const payload = {}
  for (const r of rows.value) {
    if (r.field) payload[r.header] = r.field
  }
  return payload
})

async function doPreview({ file }) {
  previewing.value = true
  result.value = null
  try {
    const res = await previewDispatch(file)
    fileName.value = file.name
    pickedFile.value = file
    systemFields.value = res.system_fields || []
    const samples = res.samples || {}
    const suggested = res.suggested_mapping || {}
    rows.value = (res.headers || []).map((header) => ({
      header,
      samples: (samples[header] || []).join(' / '),
      field: suggested[header] || '',
    }))
    step.value = 2
  } catch (e) {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    previewing.value = false
  }
}

async function doImport() {
  if (missingFields.value.length) return
  importing.value = true
  try {
    const res = await importDispatch(pickedFile.value, mappingPayload.value)
    result.value = res
    ElMessage.success(res.message || '导入完成')
    emit('imported', res)   // 父组件刷新列表与看板；响应透传（含 accounts_ready 时提示开通账号）
  } catch (e) {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    importing.value = false
  }
}

function resetAll() {
  step.value = 1
  pickedFile.value = null
  fileName.value = ''
  rows.value = []
  systemFields.value = []
  result.value = null
}
</script>

<style scoped>
.dispatch-import { padding: 4px 0; }
.upload-hint { padding: 18px 0; color: var(--color-primary); }

.mapping-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 6px;
  padding: 12px;
}
.mapping-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  color: var(--color-primary);
}
.file-name { font-weight: 600; font-size: 13px; }
.col-count { font-size: 12px; color: var(--color-sub); }

.field-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}
.status-label { font-size: 12px; color: var(--color-sub); }
.status-tag { margin-right: 2px; }
.missing-flag { color: var(--color-red); margin-left: 4px; font-weight: 600; }

.tip-alert { margin-bottom: 10px; }
.dup-item { display: block; }

.mapping-table { margin-bottom: 12px; }
.sample-text { color: #475569; font-size: 12px; }
.sample-empty { color: #94a3b8; font-size: 12px; }
.required-option { color: var(--color-primary); }
.required-star { color: var(--color-red); margin-left: 2px; }

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
/* 主按钮对齐项目深蓝主色（Element Plus 默认蓝偏亮） */
.actions :deep(.el-button--primary) {
  background-color: var(--color-primary);
  border-color: var(--color-primary);
}
.actions :deep(.el-button--primary:hover),
.actions :deep(.el-button--primary:focus) {
  background-color: #24436f;
  border-color: #24436f;
}

.result-box { margin-top: 12px; }
.result-detail { margin: 8px 0; font-size: 13px; color: #64748b; }
.error-list { margin: 6px 0 0; padding-left: 18px; color: #e53e3e; font-size: 12px; }
</style>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`多负责人管理：${project?.project_name || ''}`"
    width="720px"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-if="project" class="mm-head">
      <div class="mm-delivery">
        交付负责人：<b>{{ project.delivery_person || '—' }}</b>
        <span class="mm-sub">（自动识别 {{ managers.length }} 位负责人，可分别导入排产计划 / 申报本月计划数）</span>
      </div>
    </div>

    <el-alert
      v-if="!auth.isAdmin"
      type="info"
      :closable="false"
      title="当前账号为只读/填报权限：可查看负责人划分与导入状态，无法修改本月计划数（仅管理员可编辑）。"
      style="margin: 10px 0;"
    />

    <el-table :data="managers" border stripe style="width: 100%;" :row-style="{ height: '52px' }">
      <el-table-column label="负责人" prop="manager" min-width="120">
        <template #default="{ row }">
          <span style="font-weight:600; color:#1a365d;">{{ row.manager }}</span>
        </template>
      </el-table-column>
      <el-table-column label="本月计划数" width="180">
        <template #default="{ row }">
          <el-input-number
            v-model="row._plan"
            :min="0"
            size="small"
            :disabled="!auth.isAdmin"
            style="width: 130px;"
            @change="() => onPlanChange(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="排产状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.has_imported ? 'success' : 'info'" size="small">
            {{ row.has_imported ? '已导入' : '未导入' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain :disabled="!auth.canEdit" @click="openImport(row)">导入</el-button>
          <el-button size="small" @click="goView(row)">查看</el-button>
          <el-button
            size="small"
            type="success"
            plain
            :disabled="!auth.isAdmin || row._plan === row.monthly_plan"
            @click="savePlan(row)"
          >存计划</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 嵌套：单负责人导入弹窗（复用 ScheduleImport，预填 manager + 本月计划数） -->
    <el-dialog
      v-model="importVisible"
      :title="`导入排产计划 · ${importRow?.manager || ''}`"
      width="560px"
      append-to-body
      destroy-on-close
    >
      <ScheduleImport
        v-if="importRow"
        :pid="String(project.id)"
        :manager="importRow.manager"
        :managerMonthlyPlan="importRow._plan || 0"
        :disabled="!auth.canEdit"
        @imported="onManagerImported"
      />
      <div class="mm-import-actions">
        <span class="mm-import-hint">导入时请确认已选择「{{ importRow?.manager }}」的本月计划数；导入将仅覆盖该负责人名下排产工序。</span>
        <el-button size="small" @click="importVisible = false">关闭</el-button>
      </div>
    </el-dialog>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchProjectManagers, setManagerMonthlyPlan } from '../api/node'
import { useAuthStore } from '../store/auth'
import ScheduleImport from './ScheduleImport.vue'

const props = defineProps({
  modelValue: Boolean,
  project: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'imported'])
const auth = useAuthStore()
const router = useRouter()

const managers = ref([])
const importVisible = ref(false)
const importRow = ref(null)

watch(
  () => [props.modelValue, props.project],
  ([open]) => { if (open) load() },
  { immediate: true },
)

async function load() {
  if (!props.project?.id) return
  try {
    const res = await fetchProjectManagers(String(props.project.id))
    managers.value = (res.managers || []).map((m) => ({ ...m, _plan: m.monthly_plan || 0 }))
  } catch (e) {
    managers.value = []
  }
}

// 本月计划数变更：仅管理员可保存（el-input-number 步进也会触发，后端幂等）
function onPlanChange(row) {
  if (!auth.isAdmin) return
}

async function savePlan(row) {
  if (!auth.isAdmin) return
  try {
    await setManagerMonthlyPlan(String(props.project.id), row.manager, Number(row._plan) || 0)
    row.monthly_plan = Number(row._plan) || 0
    ElMessage.success(`已设置「${row.manager}」本月计划数为 ${row.monthly_plan}`)
  } catch (e) {
    // 错误由 axios 拦截器统一提示
  }
}

function openImport(row) {
  importRow.value = row
  importVisible.value = true
}
async function onManagerImported() {
  importVisible.value = false
  ElMessage.success('排产计划导入成功')
  await load()
  emit('imported')
}
function goView(row) {
  emit('update:modelValue', false)
  router.push(`/projects/${props.project.id}?manager=${encodeURIComponent(row.manager)}`)
}
</script>

<style scoped>
.mm-head { margin-bottom: 4px; }
.mm-delivery { font-size: 14px; color: #1a365d; }
.mm-sub { font-size: 12px; color: #718096; margin-left: 6px; }
.mm-import-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}
.mm-import-hint { font-size: 12px; color: #718096; }
</style>

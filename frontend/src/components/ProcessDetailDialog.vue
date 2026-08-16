<template>
  <el-dialog
    :model-value="modelValue"
    :title="`工序：${processName}`"
    width="720px"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template v-if="detail">
      <el-tabs v-model="innerMode">
        <el-tab-pane label="📋 节点详情" name="detail">
          <div v-for="row in detail.nodes" :key="row.id" class="row-card">
            <div class="row-bar" :style="{ background: colorOf(row.status) }"></div>
            <div style="flex:1;">
              <div style="font-size:13px; color:#64748b;">{{ row.plan_date }}</div>
              <div style="font-weight:600;">计划 {{ row.plan_qty }} 套 / 实际 {{ row.actual_qty }} 套</div>
            </div>
            <span class="status-pill" :style="pillStyle(row.status)">{{ row.label }}</span>
            <div style="font-size:12px; color:#718096;">{{ row.deviation_label }}</div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="📝 填报进度" name="input" />
        <el-tab-pane label="⚠️ 异常提报" name="exception">
          <div v-if="detail.nodes.length" class="exc-node-select">
            <div class="exc-node-label">选择节点：</div>
            <el-select v-model="selectedNodeId" placeholder="选择要提报异常的节点" style="width: 100%;">
              <el-option
                v-for="n in detail.nodes"
                :key="n.id"
                :label="`${n.plan_date} · 计划 ${n.plan_qty} 套 / 实际 ${n.actual_qty} 套`"
                :value="n.id"
              />
            </el-select>
          </div>
          <ExceptionReportTab
            v-if="selectedNodeId"
            :pid="pid"
            :node-id="selectedNodeId"
            @changed="onExceptionChanged"
          />
        </el-tab-pane>
      </el-tabs>

      <!-- 填报模式（四分组手风琴） -->
      <template v-if="innerMode === 'input'">
        <el-segmented v-model="activeGroup" :options="groupOptions" block style="margin-bottom:14px;" />
        <div v-if="groupNodes.length === 0" class="empty-hint">当前分组「{{ groupLabel }}」没有可保存的节点。</div>
        <template v-else>
          <div v-for="node in groupNodes" :key="node.id" class="row-card">
            <div class="row-bar" :style="{ background: colorOf(statusOf(node)) }"></div>
            <div style="flex:1; font-size:13px; color:#64748b;">{{ node.plan_date }}</div>
            <div style="flex:1; font-weight:600;">计划 {{ node.plan_qty }} 套</div>
            <el-input-number
              v-model="inputValues[node.id]"
              :min="0"
              :max="maxOf(node)"
              size="small"
            />
            <span class="status-pill" :style="pillStyle(statusOf(node))">{{ labelOf(node) }}</span>
          </div>
        </template>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:16px;">
          <el-button @click="innerMode = 'detail'">← 返回详情</el-button>
          <el-button type="primary" @click="save" :loading="saving">💾 保存节点进度</el-button>
        </div>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchProcessNodes, saveNodeProgress } from '../api/node'
import { useProjectStore } from '../store/project'
import ExceptionReportTab from './ExceptionReportTab.vue'

const props = defineProps({
  modelValue: Boolean,
  pid: { type: String, required: true },
  processName: { type: String, default: '' },
  mode: { type: String, default: 'detail' },
})
const emit = defineEmits(['update:modelValue', 'saved'])
const store = useProjectStore()

const detail = ref(null)
const innerMode = ref('detail')
const activeGroup = ref('today')
const inputValues = ref({})
const saving = ref(false)
const selectedNodeId = ref(null)

// 异常提报后触发预警列表刷新（复用节点保存事件总线）
function onExceptionChanged() {
  store.lastNodeSavedAt = Date.now()
}

const groupOptions = [
  { label: '🔵 今日待填报', value: 'today' },
  { label: '🔴 逾期未完成', value: 'overdue' },
  { label: '⚪ 未来计划', value: 'future' },
  { label: '🟢 已完成', value: 'done' },
]
const groupLabelMap = { today: '今日待填报', overdue: '逾期未完成', future: '未来计划', done: '已完成' }
const groupLabel = computed(() => groupLabelMap[activeGroup.value] || activeGroup.value)
const groupNodes = computed(() => detail.value?.groups?.[activeGroup.value] || [])

const statusColors = {
  done: '#38a169', pending: '#718096', in_progress: '#3182ce', warning: '#3182ce', overdue: '#e53e3e',
}
const statusBgs = {
  done: '#f0fff4', pending: '#f7fafc', in_progress: '#ebf8ff', warning: '#ebf8ff', overdue: '#fff5f5',
}
const colorOf = (s) => statusColors[s] || '#718096'
const pillStyle = (s) => ({ background: statusBgs[s] || '#f7fafc', color: statusColors[s] || '#718096' })
const statusOf = (node) => {
  const n = detail.value?.nodes?.find((x) => x.id === node.id)
  return n ? n.status : 'pending'
}
const labelOf = (node) => {
  const n = detail.value?.nodes?.find((x) => x.id === node.id)
  return n ? n.label : '—'
}
// 分组差异化上限：done=当前值只能减；overdue/future=计划数；today=前序联动（后端校验）
const maxOf = (node) => {
  if (activeGroup.value === 'done') return node.actual_qty
  if (activeGroup.value === 'overdue' || activeGroup.value === 'future') return node.plan_qty
  return node.plan_qty   // today：上限计划数，前端宽松，后端做前序联动校验
}

async function load() {
  if (!props.processName) return
  detail.value = await fetchProcessNodes(props.pid, props.processName)
  inputValues.value = {}
  Object.keys(detail.value.groups).forEach((g) => {
    detail.value.groups[g].forEach((n) => {
      inputValues.value[n.id] = n.actual_qty
    })
  })
}

async function save() {
  saving.value = true
  try {
    const values = groupNodes.value.map((n) => ({ node_id: n.id, qty: inputValues.value[n.id] ?? 0 }))
    const res = await saveNodeProgress(props.pid, props.processName, {
      group: activeGroup.value,
      values,
    })
    ElMessage.success(res.message)
    emit('saved')          // 父组件关闭弹窗 + 刷新
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.modelValue, props.processName, props.mode],
  ([open]) => {
    if (open) {
      innerMode.value = props.mode || 'detail'
      activeGroup.value = 'today'
      selectedNodeId.value = null
      load()
    }
  },
)
</script>

<style scoped>
.empty-hint { color: #64748b; font-size: 13px; padding: 12px 0; }
.exc-node-select { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.exc-node-label { font-size: 13px; color: #1a365d; font-weight: 600; white-space: nowrap; }
</style>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`工序：${processName}`"
    width="88vw"
    :style="{ maxWidth: '1200px' }"
    :close-on-click-modal="false"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template v-if="detail">
      <el-tabs v-model="innerMode">
        <el-tab-pane label="📋 节点详情" name="detail">
          <div v-for="row in detail.nodes" :key="row.id" class="row-card row-grid-detail">
            <div class="row-bar" :style="{ background: colorOf(row.status) }"></div>
            <div style="min-width:0;">
              <div class="row-dates">
                <div class="date-block">
                  <span class="date-key">计划</span>
                  <span class="date-val">{{ row.plan_date }}</span>
                </div>
                <div class="date-block">
                  <span class="date-key">实际</span>
                  <span v-if="(row.actual_qty || 0) > 0" class="date-val">{{ row.report_date || '—' }}</span>
                  <span v-else class="date-val date-empty">暂无</span>
                </div>
              </div>
              <div style="font-weight:600; white-space:nowrap;">
                计划 <span class="qty-num">{{ row.plan_qty }}</span> 套 / 实际 <span class="qty-num">{{ row.actual_qty }}</span> 套
              </div>
            </div>
            <span class="status-pill" :style="pillStyle(row.status)">{{ row.label }}</span>
            <div style="font-size:12px; color:#718096; text-align:right; white-space:nowrap;">{{ row.deviation_label }}</div>
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
        <div style="font-size:12px; color:#718096; margin-bottom:10px;">
          {{ auth.isAdmin
            ? '管理员可为每行指定历史日期补录；已保存过的节点，日期会沿用上次保存值，无变更提交不会重置为今天。未开始/未填写的节点日期默认当天（不显示历史值）。'
            : '普通账号仅可填报今日，日期已锁定' }}
        </div>
        <el-segmented v-model="activeGroup" :options="groupOptions" block style="margin-bottom:14px;" />
        <div v-if="groupNodes.length === 0" class="empty-hint">当前分组「{{ groupLabel }}」没有可保存的节点。</div>
        <template v-else>
          <div v-for="node in groupNodes" :key="node.id" class="row-card row-grid">
            <div class="row-bar" :style="{ background: colorOf(statusOf(node)) }"></div>
            <div class="cell-plan-date">{{ node.plan_date }}</div>
            <div class="cell-plan-qty">
              <span class="qty-num">{{ node.plan_qty }}</span><span class="qty-unit">套</span>
            </div>
            <el-input-number
              class="cell-qty-input"
              v-model="inputValues[node.id]"
              :min="0"
              :max="maxOf(node)"
              size="small"
              :disabled="!auth.isAdmin && activeGroup === 'done'"
            />
            <span class="cell-status status-pill" :style="pillStyle(statusOf(node))">{{ labelOf(node) }}</span>
            <!-- 填报日期：标签显示当前日期（未填写灰底/已填写蓝底），管理员点击「更改填报日期」弹 popover 选日历 -->
            <div class="cell-report-date">
              <span class="rd-tag" :class="{ 'rd-today': (node.actual_qty || 0) === 0 }">
                📅 {{ reportDates[node.id] || fmtToday() }}
              </span>
              <el-popover
                placement="left-start"
                :width="260"
                trigger="click"
                v-model:visible="datePickerOpen[node.id]"
              >
                <template #reference>
                  <el-button
                    size="small"
                    :disabled="!auth.isAdmin || activeGroup === 'done'"
                    class="rd-btn"
                  >更改填报日期</el-button>
                </template>
                <div class="rd-picker-panel">
                  <el-date-picker
                    v-model="reportDates[node.id]"
                    type="date"
                    value-format="YYYY-MM-DD"
                    format="YYYY-MM-DD"
                    :clearable="false"
                    style="width: 100%;"
                    @change="onDatePicked(node.id, $event)"
                  />
                  <div class="rd-picker-hint">
                    上次保存：<b>{{ savedDates[node.id] || '无' }}</b>
                  </div>
                </div>
              </el-popover>
            </div>
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
import { useAuthStore } from '../store/auth'
import ExceptionReportTab from './ExceptionReportTab.vue'

const props = defineProps({
  modelValue: Boolean,
  pid: { type: String, required: true },
  processName: { type: String, default: '' },
  mode: { type: String, default: 'detail' },
})
const emit = defineEmits(['update:modelValue', 'saved'])
const store = useProjectStore()
const auth = useAuthStore() // isAdmin 决定日期选择器是否可编辑

// 填报日期：默认今天，格式 YYYY-MM-DD
function fmtToday() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
// popover 内选择日期后：写回 reportDates 并收起 popover（v-model 已同步，此处幂等安全）
function onDatePicked(nodeId, newVal) {
  reportDates.value[nodeId] = newVal
  datePickerOpen.value[nodeId] = false
}
// 每行独立填报日期（按 node.id 存储）；管理员可改历史日期，普通账号锁定今天
const reportDates = ref({})
// 原始已保存填报日期（供 popover「上次保存」提示）
const savedDates = ref({})
// 每行 popover 可见状态（按 node.id）
const datePickerOpen = ref({})
// 跨组脏值判定基线：load 时记录每个节点原始 qty 与 report_date
const originalValues = ref({})

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
  reportDates.value = {}
  Object.keys(detail.value.groups).forEach((g) => {
    detail.value.groups[g].forEach((n) => {
      inputValues.value[n.id] = n.actual_qty
      const nd = detail.value.nodes.find((x) => x.id === n.id)
      const saved = nd?.report_date || ''
      reportDates.value[n.id] = (n.actual_qty || 0) > 0
        ? (saved || fmtToday())   // 已填写：保留上次保存的实际填报日期
        : fmtToday()              // 未填写（含未开始）：强制当天
      savedDates.value[n.id] = saved || ''   // 记录原始已保存日期，供 popover 提示
    })
  })
  // 加载时记下每个节点的原始 qty 与 report_date，作为脏值判定基线
  originalValues.value = {}
  Object.keys(detail.value.groups).forEach((g) => {
    detail.value.groups[g].forEach((n) => {
      originalValues.value[n.id] = {
        qty: n.actual_qty,
        report_date: reportDates.value[n.id],
      }
    })
  })
}

async function save() {
  saving.value = true
  try {
    const dirtyByGroup = { today: [], overdue: [], future: [], done: [] }
    Object.keys(detail.value.groups).forEach((g) => {
      detail.value.groups[g].forEach((n) => {
        const o = originalValues.value[n.id] || { qty: 0, report_date: fmtToday() }
        const curQty = inputValues.value[n.id] ?? 0
        const curRd = reportDates.value[n.id] || fmtToday()
        if (curQty !== o.qty || curRd !== o.report_date) {
          dirtyByGroup[g].push({ node_id: n.id, qty: curQty, report_date: curRd })
        }
      })
    })
    const groupsToSave = Object.entries(dirtyByGroup).filter(([, arr]) => arr.length)
    if (!groupsToSave.length) {
      ElMessage.info('当前没有可保存的修改')
      return
    }
    // 并发提交；任一组失败也汇总已成功的部分，避免无提示
    const settled = await Promise.allSettled(
      groupsToSave.map(([g, values]) =>
        saveNodeProgress(props.pid, props.processName, { group: g, values }),
      ),
    )
    const ok = settled.filter((r) => r.status === 'fulfilled')
    const bad = settled.filter((r) => r.status === 'rejected')
    const totalSaved = ok.reduce((s, r) => s + ((r.value?.saved) ?? 0), 0)
    if (bad.length) {
      const firstErr = bad[0].reason?.message || '请求失败'
      ElMessage.error(`部分保存失败：${bad.length} 个分组未保存（${firstErr}）`)
    }
    if (totalSaved > 0) {
      ElMessage.success(`已保存 ${totalSaved} 条节点进度`)
    }
    if (ok.length) emit('saved')          // 父组件关闭弹窗 + 刷新
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
      // 不在此重置 reportDates：load() 内部已有 重置+按节点回填 逻辑，避免双重处理
      originalValues.value = {} // 脏值基线同样由 load() 重新初始化
      load()
    }
  },
)
</script>

<style scoped>
.empty-hint { color: #64748b; font-size: 13px; padding: 12px 0; }
.exc-node-select { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.exc-node-label { font-size: 13px; color: #1a365d; font-weight: 600; white-space: nowrap; }

/* 填报进度行：6 列 grid（色条/计划日期/计划套数/数量输入/状态/日期标签+更改按钮） */
.row-grid {
  display: grid;
  grid-template-columns: 6px 130px 110px 120px 110px 280px;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
}
/* 节点详情行：色条/信息/状态/偏差 */
.row-grid-detail {
  display: grid;
  grid-template-columns: 6px 1fr auto 100px;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
}
/* 计划/实际日期：左右两列独立块，间距 18px，块最小宽 130px，防止挤压；tabular-nums 防数字抖位 */
.row-dates { display:flex; gap:18px; align-items:center; }
.date-block { display:flex; gap:6px; align-items:baseline; min-width:130px; padding:2px 0; }
.date-key { color:#1a365d; font-size:13px; font-weight:700; }
.date-val { color:#1a365d; font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap; font-size:14px; }
.date-empty { color:#a0aec0; font-style:italic; font-weight:400; }
.cell-plan-date { font-size:13px; color:#64748b; white-space:nowrap; }
.cell-plan-qty { display:inline-flex; align-items:baseline; gap:4px; white-space:nowrap; }
.qty-num { font-weight:600; font-variant-numeric:tabular-nums; font-size:15px; }
.qty-unit { color:#718096; font-size:13px; }
.cell-qty-input { width:120px; }
/* 恢复步进按钮后适配：默认组件宽度会被内建样式控制，此处覆盖；步进按钮 28px×2 + 输入区约 64px 可容纳 3 位数 */
.cell-qty-input :deep(.el-input-number__decrease),
.cell-qty-input :deep(.el-input-number__increase) { width: 28px; }
.cell-qty-input :deep(.el-input__inner) { text-align:center; font-variant-numeric:tabular-nums; }
.cell-status { white-space:nowrap; justify-self:start; }
/* 色条宽度与 grid 第 1 列（6px）对齐，覆盖全局 theme.css 的 .row-card .row-bar{width:4px} */
.row-grid .row-bar, .row-grid-detail .row-bar { width: 6px; }
.cell-report-date { display:flex; align-items:center; gap:10px; }
.rd-tag {
  display:inline-flex; align-items:center; gap:4px;
  padding: 3px 10px; border-radius: 6px;
  background: #ebf8ff; color: #1a365d;
  font-size:12px; font-weight:600;
  font-variant-numeric:tabular-nums; min-width:92px; text-align:center;
}
.rd-today { background:#f7fafc; color:#2d3748; }   /* 未开始/未填写的「今天」标识稍灰 */
.rd-btn { padding: 4px 10px; font-size:12px; }
.rd-picker-panel { padding: 4px 0; }
.rd-picker-hint { margin-top: 8px; font-size: 11px; color: #64748b; }
@media (max-width:1100px) {
  .row-grid { grid-template-columns: 6px 110px 90px 110px 100px 240px; gap:10px; }
  /* 窄屏第 4 列为 110px，input 宽度同步，避免右侧 10px 溢出 */
  .cell-qty-input { width: 110px; }
}
</style>

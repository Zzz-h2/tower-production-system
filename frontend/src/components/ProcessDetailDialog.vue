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
          <!-- 独立工序（累计完成总数 / 累计发运总数）：仅渲染一张占位汇总卡
               「完成」= 所有日报行 actual_qty 之和；每次填报产生的日期行
               只在「填报进度 → 已完成」分组中展示，不进节点详情主视图。 -->
          <template v-if="isIndependent">
            <div class="row-card row-grid-detail">
              <div class="row-bar" :style="{ background: colorOf(independentStatus.status) }"></div>
              <div class="row-info">
                <div class="row-qty-line">
                  <span class="qty-text">
                    共计 <span class="qty-num">{{ independentContract }}</span> 套 / 完成 <span class="qty-num">{{ independentFilled }}</span> 套
                  </span>
                  <span v-if="latestIndependentDate" class="latest-date">
                    <span class="ld-key">最新完成日期</span>
                    <span class="ld-val">{{ latestIndependentDate }}</span>
                  </span>
                </div>
              </div>
              <span class="status-pill" :style="pillStyle(independentStatus.status)">{{ independentStatus.label }}</span>
              <div class="deviation-label">-</div>
            </div>
          </template>
          <!-- 11 道排产工序：按节点逐行展示（保持原行为，未做任何改动） -->
          <template v-else>
            <div v-for="row in detail.nodes" :key="row.id" class="row-card row-grid-detail">
              <div class="row-bar" :style="{ background: colorOf(row.status) }"></div>
              <div class="row-info">
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
                <div class="row-qty-line">
                  <span class="qty-text">
                    计划 <span class="qty-num">{{ row.plan_qty }}</span> 套 / 实际 <span class="qty-num">{{ row.actual_qty }}</span> 套
                  </span>
                </div>
              </div>
              <span class="status-pill" :style="pillStyle(row.status)">{{ row.label }}</span>
              <div class="deviation-label">{{ row.deviation_label }}</div>
            </div>
          </template>
        </el-tab-pane>
        <el-tab-pane label="📝 填报进度" name="input" />
        <el-tab-pane v-if="!isIndependent" label="⚠️ 异常提报" name="exception">
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
            ? '管理员可为每行指定历史日期补录（含"已完成"组可编辑）；已保存过的节点，日期会沿用上次保存值，无变更提交不会重置为今天。未开始/未填写的节点日期默认当天（不显示历史值）。'
            : '大区账号仅可填报本大区节点；未填写节点默认当天，填报日期已锁定（仅可填报今日，且仅限本大区数据）' }}
        </div>
        <el-segmented v-model="activeGroup" :options="groupOptions" block style="margin-bottom:14px;" />
        <div v-if="groupNodes.length === 0" class="empty-hint">当前分组「{{ groupLabel }}」没有可保存的节点。</div>
        <template v-else>
          <!-- 独立工序（累计完成/累计发运）· 今日待填报：单卡增量输入（管理员可改填报日期，大区账号置灰） -->
          <div v-if="isIndependent && activeGroup === 'today'" class="fill-card">
            <div class="fill-card-left">
              <span class="fill-card-label">本次填报</span>
              <el-input-number
                v-model="inputValues[groupNodes[0].id]"
                :min="0"
                :max="independentRemaining"
                size="default"
                class="fill-card-input"
              />
              <span class="fill-card-unit">套</span>
              <span class="fill-card-pending" :title="`合同 ${independentContract} − 已填报 ${independentFilled} − 本次 ${inputValues[groupNodes[0].id] || 0}`">
                待完成 <span class="qty-num">{{ independentRemainingAfter }}</span> 套
              </span>
            </div>
            <div class="fill-card-right">
              <!-- 与 11 道排产工序的「更改填报日期」机制一致：修改本次填报的 report_date（管理员可改，大区账号置灰） -->
              <div class="cell-report-date">
                <span class="rd-tag" :class="{ 'rd-today': (reportDates[groupNodes[0].id] || fmtToday()) === fmtToday() }">
                  📅 {{ reportDates[groupNodes[0].id] || fmtToday() }}
                </span>
                <el-popover
                  placement="left-start"
                  :width="260"
                  trigger="click"
                  v-model:visible="datePickerOpen[groupNodes[0].id]"
                >
                  <template #reference>
                    <el-button
                      size="small"
                      :disabled="!auth.isAdmin"
                      class="rd-btn"
                    >更改填报日期</el-button>
                  </template>
                  <div class="rd-picker-panel">
                    <el-date-picker
                      v-model="reportDates[groupNodes[0].id]"
                      type="date"
                      value-format="YYYY-MM-DD"
                      format="YYYY-MM-DD"
                      :clearable="false"
                      style="width: 100%;"
                      @change="onDatePicked(groupNodes[0].id, $event)"
                    />
                    <div class="rd-picker-hint">
                      上次保存：<b>{{ savedDates[groupNodes[0].id] || '无' }}</b>
                    </div>
                  </div>
                </el-popover>
              </div>
              <span class="status-pill" :style="pillStyle('in_progress')">🔵 进行中</span>
            </div>
          </div>
          <!-- 独立工序· 已完成：每条记录一张卡（按日期降序；管理员可改日期/数量，大区账号置灰） -->
          <div v-else-if="isIndependent && activeGroup === 'done'">
            <div v-for="node in groupNodes" :key="node.id" class="record-card">
              <div class="record-card-left">
                <span class="record-card-date">📅 {{ reportDates[node.id] || node.plan_date }}</span>
                <el-input-number
                  v-model="inputValues[node.id]"
                  :min="0"
                  size="small"
                  class="cell-qty-input"
                  :disabled="!auth.isAdmin"
                />
                <span class="qty-unit">套</span>
              </div>
              <div class="record-card-right">
                <!-- 与 11 道排产工序的「更改填报日期」机制一致：移动该条记录到所选日期（管理员可改，大区账号置灰） -->
                <div class="cell-report-date">
                  <el-popover
                    placement="left-start"
                    :width="260"
                    trigger="click"
                    v-model:visible="datePickerOpen[node.id]"
                  >
                    <template #reference>
                      <el-button
                        size="small"
                        :disabled="!auth.isAdmin"
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
                <span class="status-pill" :style="pillStyle('done')">🟢 已完成</span>
              </div>
            </div>
          </div>
          <!-- 11 道排产工序：原有 row-grid 行为 -->
          <div v-else v-for="node in groupNodes" :key="node.id" class="row-card row-grid">
            <div class="row-bar" :style="{ background: colorOf(statusOf(node)) }"></div>
            <div class="row-left-section">
              <span v-if="!isIndependent" class="cell-plan-date">{{ node.plan_date }}</span>
              <span class="cell-plan-qty">
                <span class="qty-num">{{ node.plan_qty }}</span><span class="qty-unit">套</span>
              </span>
            </div>
            <div class="row-center-section">
              <el-input-number
                class="cell-qty-input"
                v-model="inputValues[node.id]"
                :min="0"
                :max="maxOf(node)"
                size="small"
                :disabled="!auth.canFill || (activeGroup === 'done' && !auth.isAdmin && !isIndependent)"
              />
              <span v-if="isIndependent" class="cell-pending" :title="`总套数 ${node.plan_qty} − 当前填报 ${inputValues[node.id] ?? node.actual_qty ?? 0}`">
                待完成 <span class="qty-num">{{ pendingOf(node) }}</span> 套
              </span>
            </div>
            <div v-if="!isIndependent" class="cell-report-date">
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
                    :disabled="!auth.isAdmin"
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
            <div class="row-status-section">
              <span class="cell-status status-pill" :style="pillStyle(statusOf(node))">{{ labelOf(node) }}</span>
            </div>
          </div>
        </template>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:16px;">
          <el-button @click="innerMode = 'detail'">← 返回详情</el-button>
          <el-button type="primary" :disabled="!auth.canFill" @click="save" :loading="saving">💾 保存节点进度</el-button>
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
  manager: { type: String, default: '' },   // 多负责人 v6.0：仅查看/提报该负责人名下节点
})
const emit = defineEmits(['update:modelValue', 'saved'])
const store = useProjectStore()
const auth = useAuthStore() // canFill 决定填报/日期是否可编辑（admin 或大区账号；后端已按大区隔离）

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
// 每行独立填报日期（按 node.id 存储）；管理员可改历史日期，大区账号锁定今天（仅本大区）
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

// ---- 失败信息紧凑渲染工具（纯函数，放最前，不依赖响应式状态） ----
// 从后端 message 中抽出关键事实，便于紧凑展示
function parseQuotaMsg(msg) {
  // 后端格式：「【数量校验未通过】{工序} 节点 {日期} 拟填报 {qty} 套，但截至 {日期} 前序工序（…）累计实际仅 {prev} 套。…」
  const m1 = String(msg || '').match(/节点\s+(\S+)\s+拟填报/)
  const m2 = String(msg || '').match(/拟填报\s+(\d+)\s+套/)
  const m3 = String(msg || '').match(/累计实际仅\s+(\d+)\s+套/)
  return { nodeDate: m1?.[1] || null, qty: m2?.[1] || null, prev: m3?.[1] || null }
}
// 每个错误 code 一条带 emoji 的短摘要
const CODE_FRIENDLY = {
  PREV_PROC_QUOTA_EXCEEDED: '🔴 数量校验未通过：请先完成前序工序的实际填报后再试',
  QTY_EXCEED_PLAN: '⚠️ 数量超计划：节点实际数量不能超过计划数',
  DONE_READONLY: '🔒 已完成分组不可编辑（仅管理员可调整）',
  BAD_REPORT_DATE: '📅 填报日期格式错误（应为 YYYY-MM-DD）',
  NODE_NOT_IN_GROUP: '⚠️ 节点与所选分组不匹配',
  UNKNOWN_GROUP: '⚠️ 未知分组',
}
// HTML 转义，防 XSS
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}
// 把每组的失败压缩成一行（PREV 走量化模板，其它走去【】前缀的原 message）
function shortItem(group, detail) {
  const label = groupLabelMap[group] || group
  if (detail?.code === 'PREV_PROC_QUOTA_EXCEEDED') {
    const f = parseQuotaMsg(detail?.message || '')
    const date = f.nodeDate ? `（${f.nodeDate}）` : ''
    if (f.qty != null && f.prev != null) {
      return `${label}${date}：拟报 ${f.qty} 套 / 前序仅 ${f.prev} 套`
    }
    return `${label}：前序累计不足`
  }
  const clean = (detail?.message || '请求失败').replace(/^【.+?】/, '')
  return `${label}：${clean}`
}

const groupOptions = computed(() => {
  const all = [
    { label: '🔵 今日待填报', value: 'today' },
    { label: '🔴 逾期未完成', value: 'overdue' },
    { label: '⚪ 未来计划', value: 'future' },
    { label: '🟢 已完成', value: 'done' },
  ]
  // 独立工序（累计完成总数 / 累计发运总数）：无日期语义，
  // 后端分组里 overdue/future 恒为空，仅保留 today/done
  if (isIndependent.value) return all.filter(g => g.value === 'today' || g.value === 'done')
  return all
})
const groupLabelMap = { today: '今日待填报', overdue: '逾期未完成', future: '未来计划', done: '已完成' }
const groupLabel = computed(() => groupLabelMap[activeGroup.value] || activeGroup.value)
const groupNodes = computed(() => detail.value?.groups?.[activeGroup.value] || [])

// 独立工序（累计完成总数/累计发运总数）：无日期语义 → 隐藏日期列与异常提报页签
const isIndependent = computed(() => !!detail.value?.is_independent)

const statusColors = {
  done: '#38a169', pending: '#718096', in_progress: '#3182ce', warning: '#3182ce', overdue: '#e53e3e',
  matches_dispatch: '#38a169',
}
const statusBgs = {
  done: '#f0fff4', pending: '#f7fafc', in_progress: '#ebf8ff', warning: '#ebf8ff', overdue: '#fff5f5',
  matches_dispatch: '#f0fff4',
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
// 分组差异化上限：done=当前值只能减；overdue/future=计划数；today=前序联动（后端校验）；
// 独立工序不限上限（累计指标可自由填报，后端同样不设上限）
const maxOf = (node) => {
  if (isIndependent.value) return undefined
  if (activeGroup.value === 'done') return node.actual_qty
  if (activeGroup.value === 'overdue' || activeGroup.value === 'future') return node.plan_qty
  return node.plan_qty   // today：上限计划数，前端宽松，后端做前序联动校验
}
// 独立工序：本次输入后剩余套数（实时反映用户输入）—— 仅用于非独立（11 道排产）
const pendingOf = (node) => {
  if (!isIndependent.value) return null
  const total = Number(node.plan_qty) || 0
  const cur = Number(inputValues.value[node.id] ?? node.actual_qty ?? 0)
  return Math.max(0, total - cur)
}

// 独立工序：合同总数（合同占位行的 plan_qty = contract_count）
const independentContract = computed(() => {
  if (!isIndependent.value || !detail.value) return 0
  const placeholder = detail.value.nodes.find((n) => !n.plan_date)
  return Number(placeholder?.plan_qty) || 0
})
// 独立工序：累计已填报（所有行 actual_qty 之和）
const independentFilled = computed(() => {
  if (!detail.value) return 0
  return detail.value.nodes.reduce((s, n) => s + (Number(n.actual_qty) || 0), 0)
})
// 独立工序：剩余可填报
const independentRemaining = computed(() => {
  return Math.max(0, independentContract.value - independentFilled.value)
})
// 独立工序：本次输入后剩余（取 today tab 占位行的 inputValue，未填视为 0）
const independentRemainingAfter = computed(() => {
  const delta = Number(
    groupNodes.value[0] ? (inputValues.value[groupNodes.value[0].id] ?? 0) : 0
  ) || 0
  return Math.max(0, independentRemaining.value - delta)
})
// 独立工序：所有日报行（plan_date 非空）最新填报日期 —— 节点详情「最新完成日期」用
const latestIndependentDate = computed(() => {
  if (!isIndependent.value || !detail.value) return null
  const dates = detail.value.nodes
    .filter((n) => n.plan_date && n.report_date)
    .map((n) => n.report_date)
    .sort()
  return dates.length ? dates[dates.length - 1] : null
})
// 独立工序：节点详情汇总卡状态（合同已完成 → done；否则 in_progress；无日期偏差）
const independentStatus = computed(() => {
  const done = independentContract.value > 0 && independentFilled.value >= independentContract.value
  return {
    status: done ? 'done' : 'in_progress',
    label: done ? '🟢 已完成' : '🔵 进行中',
  }
})

async function load() {
  if (!props.processName) return
  const params = props.manager ? { manager: props.manager } : {}
  detail.value = await fetchProcessNodes(props.pid, props.processName, params)
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
        saveNodeProgress(props.pid, props.processName, { group: g, values, manager: props.manager || undefined }),
      ),
    )
    const ok = settled.filter((r) => r.status === 'fulfilled')
    const bad = settled.filter((r) => r.status === 'rejected')
    const totalSaved = ok.reduce((s, r) => s + ((r.value?.saved) ?? 0), 0)
    if (bad.length) {
      // 仅取失败（rejected）分组，按 code 聚合压缩展示
      const items = groupsToSave
        .map(([g], i) => ({ g, result: settled[i] }))
        .filter(({ result }) => result?.status === 'rejected')
        .map(({ g, result }) => {
          const detail = result.reason?.response?.data?.detail
          const code = (detail && typeof detail === 'object') ? detail.code : 'UNKNOWN'
          return { group: g, code, short: shortItem(g, detail) }
        })
      const buckets = {}
      items.forEach(({ code, short }) => {
        const key = code || 'UNKNOWN'
        ;(buckets[key] = buckets[key] || []).push(short)
      })
      const body = Object.entries(buckets)
        .map(([code, lines]) => {
          const headline = CODE_FRIENDLY[code] || `⚠️ ${esc(code)}`
          const detailLines = lines
            .map((s) => `<div style="margin-left:14px; color:#4a5568; font-size:13px; line-height:1.7;">• ${esc(s)}</div>`)
            .join('')
          return `<div style="margin-top:6px;"><b>${esc(headline)}</b>${detailLines}</div>`
        })
        .join('')
      ElMessage.error({
        dangerouslyUseHTMLString: true,
        message: `<div style="line-height:1.6; max-width:540px;"><b>保存失败（${bad.length} / ${groupsToSave.length} 个分组）</b>${body}</div>`,
        duration: 6000,
        showClose: true,
      })
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

/* 独立工序·今日待填报：单卡增量输入布局（充足留白） */
.fill-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: box-shadow .15s;
}
.fill-card:hover { box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08); }
.fill-card-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1;
  min-width: 0;
}
.fill-card-label {
  font-size: 14px;
  font-weight: 600;
  color: #1a365d;
  white-space: nowrap;
}
.fill-card-input { width: 160px; }
.fill-card-input :deep(.el-input-number__decrease),
.fill-card-input :deep(.el-input-number__increase) { width: 32px; }
.fill-card-input :deep(.el-input__inner) { text-align: center; font-variant-numeric: tabular-nums; font-size: 15px; }
.fill-card-unit { color: #718096; font-size: 13px; }
.fill-card-pending {
  font-size: 14px;
  color: #4a5568;
  white-space: nowrap;
  padding-left: 14px;
  border-left: 1px solid #e2e8f0;
  margin-left: 4px;
}
.fill-card-pending .qty-num { color: #e53e3e; font-size: 16px; padding: 0 2px; }
.fill-card-right { display: flex; align-items: center; }

/* 独立工序·已完成：每条记录一张卡（按日期降序） */
.record-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 18px 24px;
  margin-bottom: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: box-shadow .15s;
}
.record-card:hover { box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08); }
.record-card-left {
  display: flex;
  align-items: center;
  gap: 20px;
  flex: 1;
  min-width: 0;
}
.record-card-date {
  font-size: 14px;
  font-weight: 600;
  color: #1a365d;
  font-variant-numeric: tabular-nums;
  padding: 4px 12px;
  background: #ebf8ff;
  border-radius: 6px;
  white-space: nowrap;
}
.record-card-qty {
  font-size: 14px;
  color: #4a5568;
  white-space: nowrap;
}
.record-card-qty .qty-num { color: #38a169; font-size: 16px; padding: 0 2px; }
.record-card-right { display: flex; align-items: center; }

/* 填报进度行：色条 / 左（日期+套数）/ 中（输入+待完成/已填报）/ 报告日期（非独立）/ 1fr 弹性空间 / 状态（最右） */
.row-grid {
  display: grid;
  grid-template-columns: 6px auto auto auto 1fr;
  align-items: center;
  gap: 14px;
  padding: 12px 18px;
}
.row-left-section { display: flex; align-items: baseline; gap: 14px; white-space: nowrap; }
.row-center-section { display: flex; align-items: center; gap: 12px; min-width: 0; }
.row-status-section { display: flex; align-items: center; justify-self: end; }

/* 节点详情行：色条/信息/状态/偏差 */
.row-grid-detail {
  display: grid;
  grid-template-columns: 6px 1fr auto auto;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;  /* 紧凑化：14 → 10 */
}
.row-info { min-width: 0; }
/* 数量行：左 "共计X/完成Y"  右 "最新完成日期 2026-xx-xx"，紧凑一行 */
.row-qty-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  white-space: nowrap;
  font-weight: 600;
}
.latest-date { font-size: 12px; color: #64748b; white-space: nowrap; display: inline-flex; align-items: baseline; gap: 4px; }
.latest-date .ld-key { color: #718096; font-size: 12px; font-weight: 600; }
.latest-date .ld-val { color: #1a365d; font-size: 12px; font-variant-numeric: tabular-nums; }
.deviation-label { font-size: 12px; color: #718096; text-align: right; white-space: nowrap; }

/* 计划/实际日期：左右两列独立块，间距 18px，块最小宽 130px，防止挤压；tabular-nums 防数字抖位 */
.row-dates { display: flex; gap: 18px; align-items: center; }
.date-block { display: flex; gap: 6px; align-items: baseline; min-width: 130px; padding: 2px 0; }
.date-key { color: #1a365d; font-size: 13px; font-weight: 700; }
.date-val { color: #1a365d; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; font-size: 14px; }
.date-empty { color: #a0aec0; font-style: italic; font-weight: 400; }
.cell-plan-date { font-size: 13px; color: #64748b; white-space: nowrap; }
.cell-plan-qty { display: inline-flex; align-items: baseline; gap: 4px; white-space: nowrap; }
.qty-num { font-weight: 600; font-variant-numeric: tabular-nums; font-size: 15px; }
.qty-unit { color: #718096; font-size: 13px; }
.cell-qty-input { width: 120px; }
/* 恢复步进按钮后适配：默认组件宽度会被内建样式控制，此处覆盖；步进按钮 28px×2 + 输入区约 64px 可容纳 3 位数 */
.cell-qty-input :deep(.el-input-number__decrease),
.cell-qty-input :deep(.el-input-number__increase) { width: 28px; }
.cell-qty-input :deep(.el-input__inner) { text-align: center; font-variant-numeric: tabular-nums; }
.cell-status { white-space: nowrap; }
.cell-pending { font-size: 12px; color: #64748b; white-space: nowrap; }
.cell-done-record { display: inline-flex; align-items: center; font-size: 13px; color: #1a365d; font-weight: 600; white-space: nowrap; }
.cell-done-date { margin-left: 8px; white-space: nowrap; }
/* 色条宽度与 grid 第 1 列（6px）对齐，覆盖全局 theme.css 的 .row-card .row-bar{width:4px} */
.row-grid .row-bar, .row-grid-detail .row-bar { width: 6px; }
.cell-report-date { display: flex; align-items: center; gap: 10px; }
.rd-tag {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 10px; border-radius: 6px;
  background: #ebf8ff; color: #1a365d;
  font-size: 12px; font-weight: 600;
  font-variant-numeric: tabular-nums; min-width: 92px; text-align: center;
  white-space: nowrap;
}
.rd-today { background: #f7fafc; color: #2d3748; }   /* 未开始/未填写的「今天」标识稍灰 */
.rd-btn { padding: 4px 10px; font-size: 12px; }
.rd-picker-panel { padding: 4px 0; }
.rd-picker-hint { margin-top: 8px; font-size: 11px; color: #64748b; }

@media (max-width: 1100px) {
  .row-grid { gap: 10px; padding: 10px 14px; }
  .row-left-section { gap: 10px; }
  .row-center-section { gap: 8px; }
  .cell-qty-input { width: 110px; }
  .row-grid-detail { padding: 8px 14px; gap: 10px; }
  .latest-date { font-size: 11px; }
}
</style>

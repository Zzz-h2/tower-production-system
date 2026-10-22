<template>
  <div class="exc-record-table">
    <!-- ① 计数条：共 N · 生效 A · 超期 E · 已关闭 C
         口径 = 当前**工序范围**（scopedItems：弹窗锁定的工序 + 工序下拉，均未选时即项目全量），
         **不含状态筛选**（状态下拉只是切视图，不改变"共几条"的分母）；
         右侧「当前显示 x / y」的 y 与此处「共」同源（恒等），两个数字永远自洽。 -->
    <div class="exc-count-bar">
      <span class="exc-count-item">
        <span class="exc-count-key">共</span><span class="exc-count-val">{{ scopedSummary.total }}</span><span class="exc-count-unit">条</span>
      </span>
      <span class="exc-count-item exc-count-active" :class="{ 'exc-count-zero': !scopedSummary.active }">
        <span class="exc-count-key">生效</span><span class="exc-count-val">{{ scopedSummary.active }}</span>
      </span>
      <span class="exc-count-item exc-count-warning" :class="{ 'exc-count-zero': !scopedSummary.warning }">
        <span class="exc-count-key">预警</span><span class="exc-count-val">{{ scopedSummary.warning }}</span>
      </span>
      <span class="exc-count-item exc-count-expired" :class="{ 'exc-count-zero': !scopedSummary.expired }">
        <span class="exc-count-key">超期</span><span class="exc-count-val">{{ scopedSummary.expired }}</span>
      </span>
      <span class="exc-count-item exc-count-closed" :class="{ 'exc-count-zero': !scopedSummary.closed }">
        <span class="exc-count-key">已关闭</span><span class="exc-count-val">{{ scopedSummary.closed }}</span>
      </span>
      <span class="exc-count-hint">
        超期 = 已过计划关闭日但未关闭：<b>不等于关闭</b>，暂停已失效、下游按原计划日恢复逾期判定。
      </span>
    </div>

    <!-- ② 筛选：状态 = 视图（只切行，不改计数） / 工序 = 范围（改计数）
         工序下拉仅在未锁定工序时出现（弹窗里已由 prop 锁定，无需重复选） -->
    <div class="exc-filters">
      <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 130px" size="small">
        <el-option label="全部状态" value="all" />
        <el-option label="生效中" value="active" />
        <el-option label="预警（关闭日当天）" value="warning" />
        <el-option label="已超期" value="expired" />
        <el-option label="已关闭" value="closed" />
      </el-select>
      <el-select
        v-if="!lockProcess"
        v-model="filterProcess"
        placeholder="工序"
        clearable
        filterable
        style="width: 160px"
        size="small"
      >
        <el-option label="全部工序" value="all" />
        <el-option v-for="p in processOptions" :key="p" :label="p" :value="p" />
      </el-select>
      <span class="exc-filter-tip">
        当前显示 {{ filteredItems.length }} / {{ scopedItems.length }} 条
        <span v-if="lockProcess">（已限定工序：{{ processName }}）</span>
      </span>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- ③ 9 列表格 -->
    <el-table
      :data="filteredItems"
      v-loading="loading"
      size="small"
      border
      stripe
      :row-class-name="rowClass"
      style="width: 100%"
    >
      <el-table-column prop="process_name" label="工序" width="110" />
      <el-table-column label="套号" width="110">
        <template #default="{ row }">
          <span :class="{ 'set-unspecified': !row.set_seq }">{{ row.set_label }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="responsibility_category" label="责任分类" width="110" />
      <el-table-column prop="reason_detail" label="异常原因" min-width="200" show-overflow-tooltip />
      <el-table-column label="处理人" width="100">
        <template #default="{ row }">{{ row.handler || '—' }}</template>
      </el-table-column>
      <el-table-column label="提报时间" width="130">
        <template #default="{ row }">
          <span class="date-cell">{{ fmtDateTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <!-- 计划关闭日 + 剩余/超期天数
           文案与配色按 PRD：「已超 N 天」+ 橙 #dd6b20（与该行其它异常语义一致）；
           深红 #c53030 是「逾期」的语义色，用在这里会和「延期状态」混淆。 -->
      <el-table-column label="计划关闭日" width="180">
        <template #default="{ row }">
          <span class="date-cell">{{ row.planned_close_date || '—' }}</span>
          <span v-if="row.is_active && row.days_to_close !== null" class="days-tag days-active">
            剩 {{ row.days_to_close }} 天
          </span>
          <span v-else-if="row.is_expired && row.days_overdue" class="days-tag days-expired">
            已超 {{ row.days_overdue }} 天
          </span>
          <span v-else-if="!row.planned_close_date" class="days-tag days-none">永不到期</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <span class="exc-status-pill" :style="statusStyle(row.display_status)">
            {{ statusLabel(row.display_status) }}
          </span>
        </template>
      </el-table-column>
      <!-- 操作列（2026-11）：「编辑」对**所有行**可见（含已关闭行，便于补录/修正处理措施与原因）；
           「关闭」仅未关闭行可见，已关闭行显示关闭时间。
           编辑 / 删除后由 onSaveEdit / onDelete 重新拉取（保留筛选）并 emit('changed')。 -->
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <div class="exc-ops">
            <el-button size="small" plain @click="onEdit(row)">编辑</el-button>
            <el-button
              v-if="!row.is_closed"
              size="small"
              type="success"
              plain
              :loading="closingId === row.id"
              @click="onClose(row)"
            >关闭</el-button>
            <span v-else class="closed-tip">{{ fmtDateTime(row.closed_at) }}</span>
          </div>
        </template>
      </el-table-column>
      <template #empty>
        <div class="exc-empty">
          {{ lockProcess ? `工序「${processName}」暂无异常记录` : '本项目暂无异常记录' }}
        </div>
      </template>
    </el-table>

    <!-- ④ 编辑异常记录弹窗（2026-11 新增）
         可改：责任分类 / 异常原因 / 处理人 / 计划关闭日 / 处理措施（与提报表单同一组字段）。
         • 状态**不在此弹窗改** —— 关闭仍走行内「关闭」按钮，避免「编辑」把状态改乱；
         • 计划关闭日：必填 + 不得早于今天；但**历史 NULL 记录**只要用户不碰这一项就不提交
           （后端 exclude_unset 保留原值），不会被新校验卡住；
         • 删除按钮仅 admin 可见（后端 require_admin 才是真正的权限边界）。 -->
    <el-dialog
      v-model="editVisible"
      title="编辑异常记录"
      width="620px"
      destroy-on-close
      append-to-body
    >
      <template v-if="editingRow">
        <div class="exc-edit-meta">
          <span class="exc-edit-meta-item">{{ editingRow.process_name }}</span>
          <span class="exc-edit-meta-item">{{ editingRow.set_label }}</span>
          <span class="exc-edit-meta-item">提报：{{ fmtDateTime(editingRow.created_at) }}</span>
          <span class="exc-status-pill" :style="statusStyle(editingRow.display_status)">
            {{ statusLabel(editingRow.display_status) }}
          </span>
        </div>
        <el-form :model="editForm" label-width="96px" size="default">
          <el-form-item label="责任分类" required>
            <el-select v-model="editForm.responsibility_category" placeholder="请选择" style="width: 100%">
              <el-option v-for="c in CATEGORY_OPTIONS" :key="c" :label="c" :value="c" />
            </el-select>
          </el-form-item>
          <el-form-item label="异常原因" required>
            <el-input
              v-model="editForm.reason_detail"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              placeholder="请详细描述异常原因"
            />
          </el-form-item>
          <el-form-item label="处理人">
            <el-input v-model="editForm.handler" placeholder="请输入处理人姓名" maxlength="50" />
          </el-form-item>
          <el-form-item label="计划关闭日">
            <el-date-picker
              v-model="editForm.planned_close_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
              :disabled-date="disabledPastDate"
              style="width: 100%"
            />
            <div class="field-hint">
              到期未关闭 → 暂停自动失效、下游恢复按原计划日判逾期（<b>不等于关闭</b>）。
              历史记录若原本无该日期，不修改则保持原状（永不到期）。
            </div>
          </el-form-item>
          <el-form-item label="处理措施">
            <el-input
              v-model="editForm.measures"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              placeholder="请输入处理措施"
            />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <div class="exc-edit-footer">
          <!-- 删除：左对齐 + danger 文字按钮，与右侧「取消/保存」拉开距离，降低误触 -->
          <el-button
            v-if="auth.isAdmin"
            type="danger"
            plain
            :loading="deleting"
            @click="onDelete"
          >删除</el-button>
          <div class="exc-edit-footer-right">
            <el-button @click="editVisible = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="onSaveEdit">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteException, listExceptionsByProject, updateException } from '../api/exception'
import { useAuthStore } from '../store/auth'

/**
 * 项目级异常记录表（2026-11）。
 *
 * 数据源：``GET /api/exceptions/projects/{pid}`` → ``{items, summary}``，
 * items 每条已由后端 ``decorate_exception_records`` 补好
 * ``display_status``(active|expired|closed) / ``days_to_close`` / ``days_overdue`` / ``set_label``，
 * 前端**不做任何状态推断**（到期失效的口径只有后端一处实现）。
 * 后端的 ``summary`` 按「项目」统计，锁定工序时不适用，故计数条改用本地
 * ``scopedSummary``（与表格同一份过滤后集合）聚合。
 *
 * 关闭异常走 ``PUT /api/exceptions/{id}``（status=closed）→ 关闭后重新拉取并
 * ``emit('changed')`` 让父级刷新 KPI / 工序卡片 / 预警列表。
 *
 * 编辑 / 删除（2026-11 新增）：
 *   - 「编辑」对**所有行**可见（含已关闭行），弹窗可改 责任分类 / 异常原因 / 处理人 /
 *     计划关闭日 / 处理措施 共 5 个字段（``PUT /api/exceptions/{id}``）；状态不在此改。
 *   - 「删除」在编辑弹窗内，二次确认，仅 admin 可见（``DELETE /api/exceptions/{id}``，
 *     后端 ``require_admin`` 兜底，非 admin 越权直调返回 403）。
 *   - 两者成功后都 ``load()``（保留当前筛选与工序范围）+ ``emit('changed')``。
 *
 * 复用：本组件被「工序详情弹窗（锁定工序）」与「项目详情页（全量）」两处复用，
 * 编辑/删除逻辑只有这一份实现，两处自动生效。
 */
const props = defineProps({
  pid: { type: String, required: true },
  /** 限定到某道工序（不传 = 整个项目全部异常） */
  processName: { type: String, default: '' },
  /** 外部变更令牌：数值变化即重新拉取（提报成功后由父组件 +1） */
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['changed'])

/** 登录态：删除按钮仅 admin 显示（真正的权限边界在后端 require_admin） */
const auth = useAuthStore()

/** 责任分类选项（与提报表单 / AlertList 编辑弹窗保持同一组值，避免两处口径漂移） */
const CATEGORY_OPTIONS = ['供应商', '内部生产', '物流运输', '天气/不可抗力', '其他']

const loading = ref(false)
const items = ref([])
const filterStatus = ref('all')
const filterProcess = ref('all')
const closingId = ref(null)

/** 是否锁定到单道工序（锁定后隐藏工序筛选，并只展示该工序记录） */
const lockProcess = computed(() => !!String(props.processName || '').trim())

/**
 * 「工序范围」内的记录 —— 计数条与表格**共用**这一份集合。
 *
 * 口径（2026-11 定稿）：**工序 = 范围，状态 = 视图**。
 *   - 范围：prop ``processName``（弹窗锁定工序）+ 工序下拉 ``filterProcess``（项目页可选）；
 *     两者都是「在看哪道工序」，决定范围的边界 → 参与计数。
 *   - 视图：状态下拉 ``filterStatus`` 只切视图 → **不参与**计数（见 filteredItems）。
 * 未选任何工序时为项目全量，与后端 ``summary``（按项目统计）一致。
 */
const scopedItems = computed(() => {
  const pn = String(props.processName || '').trim()
  const fp = String(filterProcess.value || '').trim()
  // 已由 prop 锁定工序时，工序下拉隐藏 → 忽略其残余值（锁定优先，防御性兜底）
  const picked = !pn && fp && fp !== 'all' ? fp : ''
  if (!pn && !picked) return items.value
  return items.value.filter((e) => {
    const name = String(e.process_name || '')
    if (pn && name !== pn) return false
    if (picked && name !== picked) return false
    return true
  })
})

/**
 * 计数条口径（🔴 与表格同源，别再读后端 summary）。
 *
 * 后端 ``summary`` 是按**项目**统计的，一旦组件被锁定到某道工序
 * （ProcessDetailDialog 传入 ``processName``），就会出现
 * 「共 2 条 / 生效 1 / 超期 0 / 已关闭 1」但表格一条都没有的自相矛盾。
 * 因此这里在**前端**按同一份 ``scopedItems`` 重算：
 *   total   = 该工序范围总条数
 *   active  = 其中 display_status === 'active'
 *   expired = 其中 display_status === 'expired'
 *   closed  = 其中 display_status === 'closed'
 * 状态筛选（filterStatus）**不参与**计数 —— 下拉只切视图，
 * "共几条"始终表示该工序范围的总量；只有「当前显示 x / y」的 x 才叠加筛选，
 * 且 y 恒等于 ``scopedSummary.total``（两个数字不可能再互相矛盾）。
 * 注意：display_status 由后端 decorate_exception_records 统一推断，前端只做聚合、不推断状态。
 */
const scopedSummary = computed(() => {
  const acc = { total: 0, active: 0, warning: 0, expired: 0, closed: 0 }
  const list = scopedItems.value || []
  acc.total = list.length
  list.forEach((e) => {
    const status = e && e.display_status
    if (status === 'active') acc.active += 1
    else if (status === 'warning') acc.warning += 1
    else if (status === 'expired') acc.expired += 1
    else if (status === 'closed') acc.closed += 1
  })
  return acc
})

/** 工序下拉选项（从数据中派生，保持出现顺序稳定） */
const processOptions = computed(() => {
  const set = new Set()
  items.value.forEach((e) => {
    const pn = String(e.process_name || '').trim()
    if (pn) set.add(pn)
  })
  return [...set]
})

/**
 * 表格行 = 工序范围（scopedItems，已含 prop 工序 + 工序下拉）再叠加**状态视图**。
 *
 * 「当前显示 x / y」中 x = 这里的条数、y = ``scopedItems.length``（= 计数条的「共」），
 * 所以 x ≤ y 且 y 与计数条恒等 —— 两个数字口径永远自洽。
 * 工序筛选已在 scopedItems 内生效，此处不再重复判断（避免两处过滤口径漂移）。
 */
const filteredItems = computed(() =>
  scopedItems.value.filter((e) => {
    if (filterStatus.value && filterStatus.value !== 'all'
        && e.display_status !== filterStatus.value) {
      return false
    }
    return true
  })
)

// 状态三段配色（2026-11 定稿）：色相**统一走「异常」橙 #dd6b20**，
// 靠「填充形态」区分严重度，而非换色相——
//   生效中 = 浅橙底 + 橙字（普通态）
//   已超期 = **实心橙底 + 白字**（与项目级「异常」pill 的实心样式统一；超期需处理，视觉更重）
//   已关闭 = 浅绿底 + 绿字
// 🔴 刻意不复用「逾期」深红 #c53030：深红在本系统专指"延期/逾期"状态，
//    用在异常到期上会与延期语义混淆（PRD 明确）。
const STATUS_STYLE = {
  active: { background: '#fffaf0', color: '#dd6b20', border: '1px solid #fbd38d' },
  // 2026-10 预警态：计划关闭日当天 —— 最后一天窗口，用预警黄（#d69e2e）与生效橙区分
  warning: { background: '#fffff0', color: '#b7791f', border: '1px solid #f6e05e' },
  expired: { background: '#dd6b20', color: '#ffffff', border: '1px solid #dd6b20' },
  closed: { background: '#f0fff4', color: '#38a169', border: '1px solid #9ae6b4' },
}
const STATUS_LABEL = { active: '生效中', warning: '⚠️ 预警', expired: '已超期', closed: '已关闭' }
const statusStyle = (s) => STATUS_STYLE[s] || STATUS_STYLE.closed
const statusLabel = (s) => STATUS_LABEL[s] || '已关闭'

/** 行级浅色底：统一走橙系（超期行橙更浓一档），不再用淡红 → 与「逾期」语义彻底分开 */
function rowClass({ row }) {
  if (row.display_status === 'expired') return 'exc-row-expired'
  if (row.display_status === 'warning') return 'exc-row-warning'
  if (row.display_status === 'active') return 'exc-row-active'
  return ''
}

/** 时间格式化：后端可能返回 'YYYY-MM-DD HH:MM:SS' / ISO 串 / null */
function fmtDateTime(value) {
  if (!value) return '—'
  const text = String(value).replace('T', ' ')
  return text.slice(0, 16)
}

/**
 * 拉取项目全部异常（含已关闭 / 已超期）。
 *
 * 只取 ``items``；后端同时返回的 ``summary`` 是按**项目**统计的，
 * 锁定工序时口径不一致，故计数条改由 ``scopedSummary`` 从 items 本地聚合。
 */
async function load() {
  if (!props.pid) return
  loading.value = true
  try {
    const res = await listExceptionsByProject(props.pid)
    items.value = res?.items || []
  } catch (e) {
    // 错误已由 axios 拦截器统一提示；保持上一次数据，避免表格闪空
  } finally {
    loading.value = false
  }
}

/** 关闭异常：写库后重新拉取（KPI/卡片由父级通过 changed 事件失效缓存） */
async function onClose(row) {
  if (!row || row.is_closed) return
  try {
    await ElMessageBox.confirm(
      `确认关闭「${row.process_name} · ${row.set_label}」这条异常？关闭后该套的暂停解除，后续工序按解决时间重算计划日。`,
      '关闭异常',
      { type: 'warning', confirmButtonText: '确认关闭', cancelButtonText: '取消' },
    )
  } catch (e) {
    return   // 用户取消
  }
  closingId.value = row.id
  try {
    await updateException(row.id, { status: 'closed' })
    ElMessage.success('异常已关闭')
    await load()
    emit('changed')
  } catch (e) {
    // 错误已由 axios 拦截器统一提示
  } finally {
    closingId.value = null
  }
}

watch(() => props.pid, load)
watch(() => props.refreshKey, load)
onMounted(load)

// ==================== 编辑 / 删除（2026-11 新增） ====================

const editVisible = ref(false)
/** 正在编辑的行（原始数据快照，用于「仅改动时提交日期」与弹窗头部信息） */
const editingRow = ref(null)
/** 该行**原始**计划关闭日（'YYYY-MM-DD'；历史 NULL → ''） */
const editOriginalClose = ref('')
const saving = ref(false)
const deleting = ref(false)

/** 编辑表单（与提报表单同一组字段；状态不在其中 —— 关闭仍走「关闭」按钮） */
const editForm = reactive({
  responsibility_category: '',
  reason_detail: '',
  handler: '',
  planned_close_date: '',
  measures: '',
})

/**
 * 「今天」的 'YYYY-MM-DD'（**业务时区 = 东八区**，与后端 ``core/timeutil.business_today`` 同口径）。
 *
 * 为什么不用 ``new Date()`` 直接取本地年月日：后端校验以 Asia/Shanghai 为准，
 * 若浏览器所在时区不同（跨国/系统时区设错），跨零点时段会出现「前端放行、后端 422」。
 * 这里显式按 Asia/Shanghai 取日期，保证两边对「今天」的理解完全一致。
 *
 * @returns {string} 'YYYY-MM-DD'
 */
function todayStr() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const pick = (type) => (parts.find((p) => p.type === type) || {}).value || ''
  return `${pick('year')}-${pick('month')}-${pick('day')}`
}

/** el-date-picker 的 disabled-date：早于业务今天（东八区）的日期置灰不可选，与后端校验口径一致 */
function disabledPastDate(d) {
  const day = new Date(d)
  day.setHours(0, 0, 0, 0)
  const today = new Date(`${todayStr()}T00:00:00`)
  today.setHours(0, 0, 0, 0)
  return day < today
}

/**
 * 打开编辑弹窗：把该行 5 个可编辑字段回填到表单。
 *
 * 已关闭行同样可编辑（PRD：允许补录/修正处理措施与原因）；
 * 状态字段刻意不回填、也不提交 —— 关闭语义只属于「关闭」按钮。
 *
 * @param {object} row 表格行（后端 decorate 后的异常记录）
 */
function onEdit(row) {
  if (!row || !row.id) return
  editingRow.value = row
  editOriginalClose.value = String(row.planned_close_date || '').slice(0, 10)
  editForm.responsibility_category = row.responsibility_category || ''
  editForm.reason_detail = row.reason_detail || ''
  editForm.handler = row.handler || ''
  editForm.planned_close_date = editOriginalClose.value
  editForm.measures = row.measures || ''
  editVisible.value = true
}

/**
 * 保存编辑（PUT /api/exceptions/{id}，只提交本弹窗负责的 5 个字段）。
 *
 * 「计划关闭日」的两条规则在这里同时满足：
 *   1. **必填 + 不得早于今天**：一旦该字段与原始值不同（用户确实动了它），
 *      就必须非空且 ≥ 今天，前端先行拦截（后端 schema 会再拦一次，过去日期 → 422）；
 *   2. **历史 NULL 记录不被卡**：原始值为空且用户没动 → **不放进 payload**，
 *      后端 ``exclude_unset`` 保留原值（NULL = 永不到期），不会触发新校验。
 *
 * @returns {Promise<void>}
 */
async function onSaveEdit() {
  const row = editingRow.value
  if (!row || !row.id) return
  if (!String(editForm.responsibility_category || '').trim()) {
    ElMessage.warning('请选择责任分类')
    return
  }
  if (!String(editForm.reason_detail || '').trim()) {
    ElMessage.warning('请填写异常原因')
    return
  }

  const payload = {
    responsibility_category: editForm.responsibility_category,
    reason_detail: editForm.reason_detail,
    handler: editForm.handler || '',
    measures: editForm.measures || '',
  }

  const origClose = String(editOriginalClose.value || '').slice(0, 10)
  const nextClose = String(editForm.planned_close_date || '').slice(0, 10)
  if (nextClose !== origClose) {
    if (!nextClose) {
      ElMessage.warning('计划关闭日期为必填，不能清空（可改为今天或之后的日期）')
      return
    }
    if (nextClose < todayStr()) {
      ElMessage.warning('计划关闭日期不能早于今天')
      return
    }
    payload.planned_close_date = nextClose
  }

  saving.value = true
  try {
    await updateException(row.id, payload)
    ElMessage.success('异常记录已更新')
    editVisible.value = false
    await load()          // 重新拉取：filterStatus / filterProcess 均为组件内 ref → 筛选自动保留
    emit('changed')       // 父级刷新 KPI / 工序卡片 / 详情
  } catch (e) {
    // 错误已由 axios 拦截器统一提示（422 等）；弹窗保持打开，便于用户修正后重试
  } finally {
    saving.value = false
  }
}

/**
 * 删除该条异常（DELETE /api/exceptions/{id}，**仅 admin**）。
 *
 * 二次确认文案明确两点用户必须知道的后果：
 *   ① 删除后不可恢复；② 该异常带来的「暂停 / 延期重算」影响同时解除。
 * 删除只清 ``node_exceptions`` 该行，不影响已填报的实际进度与排产计划行。
 *
 * 幂等（2026-11 定稿）：接口对「已不存在」也返回 200，靠 ``deleted`` 区分：
 *   - ``deleted === 1`` → 本次确实删掉 → success 提示；
 *   - ``deleted === 0`` → 已不存在（连点两次 / 超时重试 / 他人已删）→ **warning 温和提示**，
 *     绝不弹红色 error（用户没做错任何事，只是状态已收敛）。
 * 两种情况都关弹窗 + ``load()`` + ``emit('changed')``，保证幂等后视图一致。
 *
 * @returns {Promise<void>}
 */
async function onDelete() {
  const row = editingRow.value
  if (!row || !row.id) return
  try {
    await ElMessageBox.confirm(
      `确认删除「${row.process_name} · ${row.set_label}」这条异常记录？`
      + '删除后不可恢复；该异常对应的暂停影响同时解除（已填报的实际进度、排产计划不受影响）。',
      '删除异常记录',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch (e) {
    return   // 用户取消
  }
  deleting.value = true
  try {
    const res = await deleteException(row.id)
    const deletedRows = Number(res?.deleted || 0)
    if (deletedRows > 0) {
      ElMessage.success('异常记录已删除')
    } else {
      // 幂等：记录已不存在（可能已被删除），温和提示即可
      ElMessage.warning('该异常记录已不存在（可能已被删除）')
    }
    editVisible.value = false
    await load()
    emit('changed')
  } catch (e) {
    // 错误已由 axios 拦截器统一提示（403 非 admin 等）
  } finally {
    deleting.value = false
  }
}

</script>

<style scoped>
.exc-record-table { padding: 4px 0; }

/* ① 计数条 */
.exc-count-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 18px;
  padding: 8px 14px;
  margin-bottom: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  color: #4a5568;
}
.exc-count-item { display: inline-flex; align-items: baseline; gap: 4px; white-space: nowrap; }
.exc-count-key { color: #718096; }
.exc-count-val { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; color: #1a365d; }
.exc-count-unit { color: #a0aec0; }
/* 生效中：浅底橙字（普通态） */
.exc-count-active .exc-count-val { color: #dd6b20; }
/* 预警（计划关闭日当天）：深黄字，与生效橙、超期实心橙、逾期深红都能区分 */
.exc-count-warning .exc-count-val { color: #b7791f; font-weight: 600; }
/* 超期：同一「异常」橙，改用**实心填充**区分（白字橙底小徽章），
   与状态列 pill 的「浅底 / 实心」两级完全一致；不换色相 → 不会与「逾期」深红混淆。 */
.exc-count-expired .exc-count-val {
  color: #ffffff;
  background: #dd6b20;
  display: inline-block;
  padding: 0 7px;
  border-radius: 9px;
  line-height: 20px;
}
.exc-count-closed .exc-count-val { color: #38a169; }
/* 🟢 值为 0 时统一弱化（生效/超期/已关闭 三数一致）：
   去掉实心橙底与浅绿字，回落为灰字 —— 0 无信息量，强色块只会变成视觉噪音
   （用户反馈「超期的标志也太格格不入了」，圈的就是 0 值实心橙徽章）。
   权重 >0 才恢复各自强调样式，保持「实心 = 需处理」的既有视觉语言。
   选择器特意比 .exc-count-expired .exc-count-val 多一级，确保能覆盖实心橙底。 */
.exc-count-item.exc-count-zero .exc-count-val {
  color: #a0aec0;
  background: transparent;
  display: inline;
  padding: 0;
  border-radius: 0;
  line-height: inherit;
}
.exc-count-hint { flex-basis: 100%; color: #94a3b8; font-size: 11px; line-height: 1.6; }

/* ② 筛选条 */
.exc-filters { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.exc-filter-tip { font-size: 12px; color: #718096; margin-left: auto; }

/* ③ 表格单元格 */
.date-cell { font-variant-numeric: tabular-nums; }
.days-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 9px;
  font-size: 11px;
  line-height: 17px;
  white-space: nowrap;
}
.days-active { background: #fffaf0; color: #dd6b20; }
/* 超期标签统一走「异常」橙 #dd6b20（PRD）：深红 #c53030 属「逾期」语义，此处不复用 */
.days-expired { background: #fffaf0; color: #dd6b20; font-weight: 600; }
.days-none { background: #f7fafc; color: #a0aec0; }
.set-unspecified { color: #94a3b8; }
.exc-status-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
}
.closed-tip { font-size: 11px; color: #a0aec0; font-variant-numeric: tabular-nums; }
.exc-empty { padding: 18px 0; color: #718096; font-size: 13px; }

/* 操作列：编辑 + 关闭（或关闭时间）同一行，避免窄列换行抖动 */
.exc-ops { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.exc-ops .el-button + .el-button { margin-left: 0; }

/* ④ 编辑弹窗 */
.exc-edit-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  padding: 7px 12px;
  margin-bottom: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  color: #4a5568;
}
.exc-edit-meta-item { white-space: nowrap; font-variant-numeric: tabular-nums; }
/* 删除左、取消/保存右：两端对齐拉开距离，降低误触删除的概率 */
.exc-edit-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.exc-edit-footer-right { display: flex; align-items: center; }
.field-hint { font-size: 11px; color: #94a3b8; line-height: 1.6; margin-top: 2px; }

/* 行级浅底（:deep 穿透到 el-table 生成的 tr） */
/* 行级底色：同为橙系，超期的橙更浓一档（不用淡红，避免读成"逾期"） */
:deep(.exc-row-active) { background: #fffdf8; }
:deep(.exc-row-warning) { background: #fffbea; }   /* 预警（关闭日当天）：极浅黄，比超期更淡 */
:deep(.exc-row-expired) { background: #fff7ed; }
</style>

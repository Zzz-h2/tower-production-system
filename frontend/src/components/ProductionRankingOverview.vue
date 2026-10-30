<template>
  <div class="ranking-wrap">
    <!-- ① 工具条 -->
    <div class="block-card">
      <div class="toolbar">
        <el-date-picker
          v-model="store.filters.month"
          type="month"
          :clearable="false"
          value-format="YYYY-MM"
          placeholder="选择调度令月份"
          style="width: 160px"
          @change="load"
        />
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <span class="hint">统计口径：多负责人按单人分别排名；累计计划套数=各负责人申报的本月计划数之和；累计完成套数=附件安装实际完成；完成率=累计完成套数÷累计计划套数×100%；按调度令月份归类</span>
      </div>
    </div>

    <!-- ② 统计卡片 -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-value">{{ stats.persons }}</div>
        <div class="kpi-label">负责人数量</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{{ fmtQty(stats.totalPlan) }}</div>
        <div class="kpi-label">累计计划套数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:#38a169;">{{ fmtQty(stats.totalActual) }}</div>
        <div class="kpi-label">累计完成套数</div>
      </div>
      <!-- 2026-11 新增：计划外完成（非本月调度令、人工录入）—— 数值取接口 extra_total，
           与各行 extra_qty 之和一致；已计入上方「累计完成套数」与完成率分子。 -->
      <div class="kpi-card">
        <div class="kpi-value" style="color:#805ad5;">{{ fmtQty(extraTotal) }}</div>
        <div class="kpi-label">计划外完成套数</div>
      </div>
      <!-- 2026-10-30：按要求「整体完成率」与「计划外完成套数」互换位序，整体完成率固定在最右侧 -->
      <div class="kpi-card">
        <div class="kpi-value" style="color:#3182ce;">{{ stats.avgRate }}</div>
        <div class="kpi-label">整体完成率</div>
      </div>
    </div>

    <!-- ③ 排名表格 -->
    <div class="block-card">
      <div class="block-header">
        <span class="icon"></span><span class="block-title">出品排名</span>
        <el-tag type="info" size="small">{{ rows.length }}</el-tag>
      </div>
      <el-table :data="rows" border stripe style="width: 100%" :row-style="{ height: '48px' }">
        <el-table-column label="排名" width="200" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.rank === 1" type="warning" size="small">🏆 冠军</el-tag>
            <span v-else>{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column label="负责人" prop="manager" width="140" align="center">
          <template #default="{ row }">
            <span style="font-weight:600; color:#1a365d;">{{ row.manager }}</span>
          </template>
        </el-table-column>
        <el-table-column label="项目数" prop="project_count" width="110" align="center" />
        <el-table-column label="累计计划套数" width="160" align="center">
          <template #default="{ row }">{{ fmtQty(row.total_plan) }}</template>
        </el-table-column>
        <el-table-column label="累计完成套数" width="160" align="center">
          <template #default="{ row }">
            <!-- 2026-10-30：去掉「+N」内联标签（它会把数字挤偏），改为**当天增长标识**：
                 ↑ 用绝对定位悬浮在数字右侧（.today-up），有无标识都不影响数字居中。
                 判据 = 今天有填报新增 OR **今天录入了计划外完成**（次日自动消失）。 -->
            <el-tooltip v-if="hasTodayFlag(row)" placement="top" :content="todayTip(row)">
              <span class="actual-cell is-today">
                {{ fmtQty(row.total_actual) }}<span class="today-up">↑</span>
              </span>
            </el-tooltip>
            <span v-else class="actual-cell">{{ fmtQty(row.total_actual) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="完成率" min-width="300" align="center">
          <template #default="{ row }">
            <template v-if="row.completion_rate === null || row.completion_rate === undefined">
              <span style="color:#a0aec0;">—</span>
            </template>
            <el-progress
              v-else
              :percentage="Math.min(100, row.completion_rate)"
              :color="rateColor(row.completion_rate)"
              :format="() => row.completion_rate.toFixed(1) + '%'"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" align="center" fixed="right">
          <template #default="{ row }">
            <!-- 2026-10-30：按用户要求，「详情 / 额外」由纯链接改为描边按钮（可见边框） -->
            <el-button type="primary" plain size="small" @click="openDetail(row)">详情</el-button>
            <!-- 2026-11：计划外完成录入入口（仅管理员；后端同样 require_admin） -->
            <el-button
              v-if="auth.isAdmin"
              type="success"
              plain
              size="small"
              @click="openExtra(row)"
            >额外</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!rows.length && !loading" description="当月暂无出品数据" />
    </div>

    <!-- ④ 详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      :title="`${detailPerson} · 逾期/提前项目清单（${store.filters.month}）`"
      width="88vw"
      :style="{ maxWidth: '1280px' }"
    >
      <el-table
        :data="detailRows"
        border
        stripe
        style="width: 100%"
        :row-style="{ height: '52px' }"
        :max-height="'60vh'"
        :header-cell-style="{ whiteSpace: 'nowrap', background: '#f7fafc', color: '#1a365d' }"
        :cell-style="{ whiteSpace: 'nowrap' }"
      >
        <el-table-column label="项目名称" prop="project_name" min-width="260" show-overflow-tooltip />
        <el-table-column label="机号" prop="machine_no" width="110">
          <template #default="{ row }">{{ row.machine_no || '-' }}</template>
        </el-table-column>
        <el-table-column label="异常类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.exception_type === '逾期' ? 'danger' : 'primary'" size="small">
              {{ row.exception_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工序" prop="process_name" min-width="120" />
        <el-table-column label="计划日期" prop="plan_date" width="130" />
        <el-table-column label="计划/实际" min-width="150">
          <template #default="{ row }">
            <span style="white-space: nowrap; font-variant-numeric: tabular-nums;">
              {{ row.plan_qty }} / {{ row.actual_qty }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="偏差天数" prop="deviation_days" width="100" align="center" />
      </el-table>
      <el-empty v-if="!detailRows.length" description="该负责人当月无逾期或提前项目" />

      <!-- 2026-10-30：详情弹窗内的「计划外完成明细」（与上方清单并行拉取） -->
      <div class="extra-detail-block">
        <div class="extra-detail-title">
          计划外完成明细（本月 {{ extraMonthTotal }} 套）
        </div>
        <el-table
          :data="detailExtraRows"
          border
          size="small"
          style="width: 100%"
          :row-style="{ height: '40px' }"
          :header-cell-style="{ whiteSpace: 'nowrap', background: '#f7fafc', color: '#1a365d' }"
        >
          <el-table-column label="项目" prop="project_name" min-width="240" show-overflow-tooltip />
          <el-table-column label="机型" width="160">
            <template #default="{ row }">{{ row.machine_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="套数" prop="qty" width="90" align="center" />
          <el-table-column label="录入时间" prop="created_at" width="170" align="center" />
        </el-table>
        <div v-if="!detailExtraRows.length" class="extra-detail-empty">本月无计划外完成登记</div>
      </div>
    </el-dialog>

    <!-- ⑤ 计划外完成弹窗（2026-11，仅管理员）：上半新增录入 / 下半已填报记录可改套数 -->
    <el-dialog
      v-model="extraVisible"
      :title="`计划外完成（${store.filters.month}）`"
      width="780px"
      append-to-body
      :close-on-click-modal="false"
    >
      <!-- ① 新增录入（原有模块，样式与字段未改） -->
      <div class="extra-section-title">新增录入</div>
      <el-form label-width="110px" label-position="right">
        <el-form-item label="负责人" required>
          <el-select v-model="extraForm.manager" placeholder="选择负责人" style="width: 100%" @change="loadExtraEdit">
            <el-option v-for="m in managerOptions" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目" required>
          <el-input v-model="extraForm.project_name" placeholder="项目名称（自由填写，可不在项目列表）" maxlength="255" />
        </el-form-item>
        <el-form-item label="机型">
          <el-input v-model="extraForm.machine_type" placeholder="选填" maxlength="128" />
        </el-form-item>
        <el-form-item label="额外完成套数" required>
          <el-input-number v-model="extraForm.qty" :min="1" :step="1" :precision="0" style="width: 160px" />
          <span class="extra-hint">计入 {{ store.filters.month }} 该负责人的累计完成（不改计划分母）</span>
        </el-form-item>
      </el-form>

      <!-- ② 已填报记录（2026-10-30 新增）：查看 / 直接在表内改套数并保存 -->
      <el-divider content-position="left">已填报记录（可调整套数）</el-divider>
      <div class="extra-edit-block">
        <div class="extra-edit-head">
          <span class="extra-edit-summary">
            当前负责人本月共 <b>{{ extraEditRows.length }}</b> 条，合计
            <b>{{ fmtQty(extraEditTotal) }}</b> 套
          </span>
          <el-button size="small" :icon="Refresh" :loading="extraEditLoading" @click="loadExtraEdit">刷新</el-button>
        </div>
        <el-table
          v-loading="extraEditLoading"
          :data="extraEditRows"
          border
          size="small"
          style="width: 100%"
          max-height="260"
          :row-style="{ height: '40px' }"
          :header-cell-style="{ whiteSpace: 'nowrap', background: '#f7fafc', color: '#1a365d' }"
        >
          <el-table-column label="项目" prop="project_name" min-width="150" show-overflow-tooltip />
          <el-table-column label="机型" width="100" show-overflow-tooltip>
            <template #default="{ row }">{{ row.machine_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="套数" width="140" align="center">
            <template #default="{ row }">
              <el-input-number
                v-model="row.editQty"
                :min="1"
                :step="1"
                :precision="0"
                size="small"
                controls-position="right"
                style="width: 110px"
              />
            </template>
          </el-table-column>
          <el-table-column label="录入时间" prop="created_at" width="140" align="center" />
          <el-table-column label="操作" width="168" align="center">
            <template #default="{ row }">
              <el-button
                type="primary"
                plain
                size="small"
                :loading="row.saving"
                :disabled="!isExtraDirty(row)"
                @click="saveExtraRow(row)"
              >保存</el-button>
              <!-- 2026-10-30：删除已生成记录（二次确认；同样只看 admin，后端 require_admin 兜底） -->
              <el-button
                type="danger"
                plain
                size="small"
                :disabled="row.saving"
                @click="removeExtraRow(row)"
              >删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="!extraEditLoading && !extraEditRows.length" class="extra-edit-empty">
          该负责人本月暂无计划外完成记录
        </div>
      </div>

      <template #footer>
        <el-button @click="extraVisible = false">关闭</el-button>
        <el-button type="primary" :loading="extraSaving" @click="submitExtra">确认录入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import {
  fetchProductionRanking,
  fetchProductionRankingDetail,
  addExtraCompletion,
  fetchExtraCompletions,
  updateExtraCompletion,
  deleteExtraCompletion,
} from '../api/ranking'

const store = useProjectStore()   // 共享调度令月份（三页联动）
const auth = useAuthStore()       // 仅用于「额外」按钮的显隐（后端仍强制 require_admin）
const loading = ref(false)
const rows = ref([])
const extraTotal = ref(0)         // 当月计划外完成合计（KPI 第 5 项，取接口 extra_total）

const stats = computed(() => {
  const totalPlan = rows.value.reduce((s, r) => s + (r.total_plan || 0), 0)
  const totalActual = rows.value.reduce((s, r) => s + (r.total_actual || 0), 0)
  // 完成率 = 累计完成套数 / 累计计划套数 × 100%（整体口径）
  // ⚠️ 不可用「各负责人完成率的算术平均」：那会让小组负责人的权重被放大，
  //    例如 1/1=100% 与 10/100=10% 各占 50%，与真实产出占比严重不符。
  const rate = totalPlan > 0 ? ((totalActual / totalPlan) * 100).toFixed(1) : '—'
  return { persons: rows.value.length, totalPlan, totalActual, avgRate: totalPlan > 0 ? `${rate}%` : rate }
})

const fmtQty = (v) => (v === null || v === undefined ? '0' : Number(v).toLocaleString())
const rateColor = (rate) => (rate >= 100 ? '#38a169' : rate < 60 ? '#e53e3e' : '#ed8936')

// ── 今日新增（v7.8）：后端 /ranking/production 返回 today_increment + today ──
// today_increment = 该负责人名下『附件安装』中「最后一次填报日期 = 业务今日」的实际完成量之和；
// > 0 才在「累计完成套数」旁显示 ↑（无新增保持简洁，不给每条都挂箭头）。
const todayIncrement = (row) => {
  const n = Number(row?.today_increment)
  return Number.isFinite(n) && n > 0 ? n : 0
}
// 2026-10-30：今天录入的「计划外完成」套数（后端 extra_today_qty = DATE(created_at)=今天 的合计）。
// 🔴 次日自动为 0 —— 标识必须按"天"判断，不是当月累计（用户原话：当天展示第二天就不展示了）。
const extraTodayQty = (row) => {
  const n = Number(row?.extra_today_qty)
  return Number.isFinite(n) && n > 0 ? n : 0
}
// 任一来源今日有增长 → 显示绿色 ↑（两者共用同一个箭头，避免并排两个箭头）
const hasTodayFlag = (row) => todayIncrement(row) > 0 || extraTodayQty(row) > 0
const todayTip = (row) => {
  const day = row?.today || '今日'
  const parts = []
  const filled = todayIncrement(row)
  const extra = extraTodayQty(row)
  if (filled > 0) parts.push(`${day} 填报新增 ${fmtQty(filled)} 套`)
  if (extra > 0) parts.push(`${day} 录入计划外完成 ${fmtQty(extra)} 套`)
  return parts.join('；')
}
// ⚠️ 口径如实标注（tooltip 第二行灰字）：库里没有填报流水表，node_actual_progress 是
// 覆盖式保存（report_date = 最后一次填报日期、actual_qty = 该节点累计值），
// 故这里统计的是「最后一次填报发生在今天的节点累计量」，同一节点跨天分批填报时会偏高。

// 详情
const detailVisible = ref(false)
const detailPerson = ref('')
const detailRows = ref([])
// 2026-10-30：详情弹窗内的「计划外完成明细」（与 detailRows 并行拉取，互不阻塞）
const detailExtraRows = ref([])
const extraMonthTotal = computed(() =>
  detailExtraRows.value.reduce((s, r) => s + Number(r.qty || 0), 0))
async function openDetail(row) {
  detailPerson.value = row.manager
  detailRows.value = []
  detailExtraRows.value = []
  detailVisible.value = true
  // 两个请求并行：任何一个失败都不影响另一个的展示
  const [detailRes, extraRes] = await Promise.allSettled([
    fetchProductionRankingDetail(store.filters.month, row.manager),
    fetchExtraCompletions(store.filters.month, row.manager),
  ])
  if (detailRes.status === 'fulfilled') {
    detailRows.value = detailRes.value || []
  } else {
    ElMessage.error('加载明细失败')
    detailRows.value = []
  }
  if (extraRes.status === 'fulfilled') {
    detailExtraRows.value = extraRes.value?.items || []
  } else {
    // 计划外明细为增强展示：失败不弹错，仅留空态（大区账号越权时会 403，属预期）
    detailExtraRows.value = []
  }
}

async function load() {
  store.ensureMonth()   // 月份必填（2026-10）：被清空时自动回补当前自然月，杜绝「全部月份」汇总口径
  loading.value = true
  store.ensureMonth()   // 共享月份非空（默认当前自然月）
  try {
    // v7.9：接口由 list 改为 { rows, extra_total }（extra_total = 当月计划外完成合计）
    const res = await fetchProductionRanking(store.filters.month)
    rows.value = res?.rows || []
    extraTotal.value = Number(res?.extra_total || 0)
  } catch (e) {
    ElMessage.error('加载排名数据失败')
  } finally {
    loading.value = false
  }
}

// ── 计划外完成录入（2026-11，仅管理员）──
// 口径：month 只影响该月；qty 计入该负责人当月累计完成，完成率只加分子不动分母。
const extraVisible = ref(false)
const extraSaving = ref(false)
const extraForm = ref({ manager: '', project_name: '', machine_type: '', qty: 1 })
// 负责人候选 = 当前排名的负责人（自由文本口径下，前端只让选已有负责人，避免录到无人认领的 name）
const managerOptions = computed(() => rows.value.map((r) => r.manager).filter(Boolean))

// ── 已填报记录（2026-10-30 新增）：查看 / 原地改套数 / 保存 ──
// 数据源与「详情弹窗」同一个 GET /ranking/extra/list（month + manager），不新增接口口径。
const extraEditRows = ref([])
const extraEditLoading = ref(false)
const extraEditTotal = computed(() =>
  extraEditRows.value.reduce((s, r) => s + Number(r.editQty || 0), 0))

// 后端 detail 既可能是字符串也可能是 {code, message} 对象，统一取人话文案
const errMsg = (e, fallback) => {
  const d = e?.response?.data?.detail
  if (typeof d === 'string' && d) return d
  if (d && typeof d === 'object' && d.message) return d.message
  return fallback
}

async function loadExtraEdit() {
  const mgr = extraForm.value.manager
  if (!extraVisible.value || !mgr) { extraEditRows.value = []; return }
  extraEditLoading.value = true
  try {
    const res = await fetchExtraCompletions(store.filters.month, mgr)
    // editQty = 编辑中的值（与 qty 原值比对判断是否有改动）；saving = 单行保存态
    extraEditRows.value = (res?.items || []).map((it) => ({
      ...it,
      editQty: Number(it.qty || 0),
      saving: false,
    }))
  } catch (e) {
    extraEditRows.value = []
    ElMessage.error(errMsg(e, '加载已填报记录失败'))
  } finally {
    extraEditLoading.value = false
  }
}

// 值没变就禁用保存，避免无意义的 PUT（也防手抖重复点）
const isExtraDirty = (row) => Number(row.editQty) !== Number(row.qty)

async function saveExtraRow(row) {
  const qty = Number(row.editQty)
  if (!Number.isFinite(qty) || qty <= 0) { ElMessage.warning('额外完成套数必须大于 0'); return }
  if (!isExtraDirty(row)) { ElMessage.info('套数未改动'); return }
  row.saving = true
  try {
    await updateExtraCompletion(row.id, { month: store.filters.month, qty: Math.trunc(qty) })
    ElMessage.success('已更新该条计划外完成')
    // 保存后两件事同时做：刷新列表（回显新值）+ 刷新排名与 KPI（完成率/顺序跟着变）
    await Promise.all([loadExtraEdit(), load()])
  } catch (e) {
    ElMessage.error(errMsg(e, '更新失败'))
  } finally {
    row.saving = false
  }
}

// 删除已生成记录：二次确认 → DELETE → 列表与排名一起回退
async function removeExtraRow(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除「${row.project_name}」的 ${row.qty} 套计划外完成？删除后该负责人的累计完成与完成率会同步回退。`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return   // 取消 / 关闭弹窗 → 什么都不做（ElMessageBox 取消是 reject，必须吞掉）
  }
  row.saving = true
  try {
    await deleteExtraCompletion(row.id, store.filters.month)
    ElMessage.success('已删除该条计划外完成')
    // 与保存同样两路刷新：列表少一行 + 排名/KPI 回退
    await Promise.all([loadExtraEdit(), load()])
  } catch (e) {
    ElMessage.error(errMsg(e, '删除失败'))
  } finally {
    row.saving = false
  }
}

// 切换负责人由 el-select 的 @change 触发 loadExtraEdit（不用 watch：
// 重新打开同一负责人时 watch 不会触发，会导致编辑区停留在上一个人的数据）
function openExtra(row) {
  if (!auth.isAdmin) return
  extraForm.value = {
    manager: row?.manager || '',
    project_name: '',
    machine_type: '',
    qty: 1,
  }
  extraEditRows.value = []
  extraVisible.value = true
  loadExtraEdit()
}

async function submitExtra() {
  const f = extraForm.value
  if (!f.manager) { ElMessage.warning('请选择负责人'); return }
  if (!String(f.project_name || '').trim()) { ElMessage.warning('请填写项目名称'); return }
  const qty = Number(f.qty)
  if (!Number.isFinite(qty) || qty <= 0) { ElMessage.warning('额外完成套数必须大于 0'); return }
  extraSaving.value = true
  try {
    await addExtraCompletion({
      month: store.filters.month,
      manager: f.manager,
      project_name: String(f.project_name).trim(),
      machine_type: String(f.machine_type || '').trim() || null,
      qty: Math.trunc(qty),
    })
    // ⚠️ ElMessage 只传一个参数（本项目踩过坑）
    ElMessage.success(`已录入额外完成 ${Math.trunc(qty)} 套`)
    // 2026-10-30：录入后不再关闭弹窗 —— 下方「已填报记录」就地刷新，可立刻核对/修正；
    // 表单只清空本次输入（负责人保留，方便同一个人连续补录）。
    f.project_name = ''
    f.machine_type = ''
    f.qty = 1
    await Promise.all([loadExtraEdit(), load()])
  } catch (e) {
    ElMessage.error(errMsg(e, '录入失败'))
  } finally {
    extraSaving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ranking-wrap { }
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hint { color: #718096; font-size: 13px; }
.kpi-row { display: flex; gap: 16px; margin: 16px 0; }
.kpi-card {
  flex: 1; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px;
}
.kpi-value { font-size: 28px; font-weight: 700; color: #1a365d; }
.kpi-label { font-size: 13px; color: #718096; margin-top: 4px; }
/* 2026-11：计划外完成 KPI 的副标题（说明这是人工录入、非本月调度令） */
/* 2026-10-30：按用户要求删除副标题 —— KPI 只保留「数值 + 标签」，与其它 4 项一致。
   样式一并移除（无其它引用）。 */
/* 2026-10-30：`.extra-tag`（+N 内联标签）已删除 —— 内联元素会把数字挤偏，改为当天 ↑ 标识。 */
.extra-hint { margin-left: 10px; font-size: 11px; color: #a0aec0; }
/* 2026-10-30：计划外完成弹窗内的「新增录入 / 已填报记录」两段分区
   风格与详情弹窗一致：左竖条标题 + #f7fafc 表头，禁用花哨描边。 */
.extra-section-title {
  font-size: 13px; font-weight: 600; color: #1a365d;
  margin-bottom: 12px; padding-left: 8px; border-left: 3px solid #3182ce;
}
.extra-edit-block { margin-top: 4px; }
.extra-edit-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 8px;
}
/* 数字用等宽数字，条数/合计变化时行宽不跳 */
.extra-edit-summary { font-size: 12px; color: #718096; font-variant-numeric: tabular-nums; }
.extra-edit-summary b { color: #1a365d; font-weight: 600; }
.extra-edit-empty {
  margin-top: 8px; font-size: 12px; color: #a0aec0; text-align: center; padding: 10px 0;
}
/* 2026-10-30：详情弹窗内的「计划外完成明细」区块 */
.extra-detail-block { margin-top: 16px; }
.extra-detail-title {
  font-size: 13px; font-weight: 600; color: #1a365d;
  margin-bottom: 8px; padding-left: 8px; border-left: 3px solid #805ad5;
}
.extra-detail-empty {
  margin-top: 8px; font-size: 12px; color: #a0aec0; text-align: center; padding: 10px 0;
}
.block-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; }
.block-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.block-title { font-size: 15px; font-weight: 600; color: #1a365d; }
/* 「累计完成套数」单元：数字 + 今日新增 ↑
   箭头刻意做小（12px / #38a169），不抢数字视觉；仅在今日有新增时渲染。
   箭头用绝对定位悬浮在数字右侧 → 有无箭头都不影响数字的居中位置（列内数字始终对齐）。 */
.actual-cell {
  position: relative;
  display: inline-block;
  font-variant-numeric: tabular-nums;
}
.actual-cell.is-today { cursor: help; }
.today-up {
  position: absolute;
  /* 与数字拉开一点（4px → 8px），避免挤在一起 */
  left: calc(100% + 8px);
  top: 50%;
  transform: translateY(-58%);
  font-size: 14px;
  line-height: 1;
  /* 加深一档（#38a169 → #2f855a），在浅底表头下更实 */
  color: #2f855a;
  font-weight: 800;
  opacity: .9;
}
/* 详情弹窗表格：表头与单元格强制单行，避免短文本被竖排 */
.detail-dialog-table th.el-table__cell,
.detail-dialog-table td.el-table__cell {
  white-space: nowrap;
}
</style>

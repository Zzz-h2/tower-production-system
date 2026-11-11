<template>
  <div class="issue-wrap">
    <!-- ① 筛选条（sticky 吸顶：滚动时始终可操作） -->
    <div class="block-card filter-bar">
      <div class="toolbar">
        <el-date-picker
          v-model="store.filters.month"
          type="month"
          :clearable="false"
          value-format="YYYY-MM"
          placeholder="选择调度令月份"
          style="width: 150px"
          @change="load"
        />
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 120px" @change="load">
          <el-option label="计划中" value="pending" />
          <el-option label="执行中" value="processing" />
          <el-option label="已完成" value="closed" />
        </el-select>
        <el-select v-model="filters.severity" placeholder="全部等级" clearable style="width: 120px" @change="load">
          <el-option label="高" value="high" />
          <el-option label="中" value="medium" />
          <el-option label="低" value="low" />
        </el-select>
        <el-select
          v-model="filters.project_id"
          placeholder="全部项目"
          clearable
          filterable
          style="width: 220px"
          @change="load"
        >
          <el-option v-for="p in projectOptions" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-input
          v-model="filters.keyword"
          placeholder="搜索项目 / 问题 / 工序 / 责任人"
          clearable
          style="width: 220px"
          @keyup.enter="load"
          @clear="load"
        />
        <el-checkbox v-model="filters.overdue_only" @change="load">只看逾期未关闭</el-checkbox>
        <div class="toolbar-right">
          <el-button :icon="RefreshLeft" @click="resetFilters">重置</el-button>
          <el-button type="primary" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        </div>
      </div>
    </div>

    <!-- ② 指标行：5 张等宽卡（flex 均分，一行放完） -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-value">{{ kpis.total }}</div>
        <div class="kpi-label">事项总数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:#38a169;">{{ kpis.closed }}</div>
        <div class="kpi-label">已关闭事项数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:#dd6b20;">{{ kpis.open }}</div>
        <div class="kpi-label">未关闭事项数</div>
      </div>
      <div class="kpi-card kpi-rate">
        <el-progress
          type="circle"
          :width="58"
          :percentage="Math.min(100, kpis.close_rate || 0)"
          :color="rateColor(kpis.close_rate)"
          :format="() => `${kpis.close_rate || 0}%`"
        />
        <div class="kpi-rate-text">
          <div class="kpi-label">事项关闭率</div>
          <div class="kpi-sub">当前 {{ kpis.close_rate || 0 }}% / 目标 {{ kpis.target_rate }}%</div>
        </div>
      </div>
      <!-- 第 5 张：逾期未关闭（红卡 + 可点击联动筛选） -->
      <div
        class="kpi-card kpi-danger"
        :class="{ 'is-active': filters.overdue_only }"
        title="判据：未关闭 且 解决时间早于今天（点击可只看逾期未关闭）"
        @click="toggleOverdue"
      >
        <div class="kpi-value" style="color:#e53e3e;">
          {{ kpis.overdue }}<span v-if="kpis.overdue > 0" class="pulse-dot"></span>
        </div>
        <div class="kpi-label">逾期未关闭事项数</div>
        <div class="kpi-sub">判据：未关闭且解决时间早于今天</div>
      </div>
    </div>

    <!-- ③ 主区：左右两列**等高对齐**（align="stretch" + 卡片 flex 撑满） -->
    <el-row :gutter="12" align="stretch" class="main-row">
      <!-- 左：主问题列表。≥1400px 时占 2/3；更窄时整宽（图表随后落到下方） -->
      <el-col :span="24" class="col-main">
        <div class="block-card">
          <div class="block-header">
            <span class="block-title">问题明细</span>
            <el-tag type="info" size="small">{{ items.length }}</el-tag>
          </div>
          <!-- 表格容器 flex:1 → el-table height=100% 撑满卡片，多余空白落在表格内而不是卡片底部 -->
          <div class="table-wrap">
            <el-table
              :data="sortedItems"
              border
              stripe
              size="small"
              height="100%"
              style="width: 100%"
              :row-style="rowStyle"
              :header-cell-style="{ background: '#f7fafc', color: '#1a365d', whiteSpace: 'nowrap', textAlign: 'center' }"
              @sort-change="onSortChange"
            >
              <el-table-column label="项目名称" prop="project_name" min-width="162" show-overflow-tooltip />
              <el-table-column label="问题描述" prop="reason_detail" min-width="160" show-overflow-tooltip />
              <el-table-column label="等级" width="72" align="center" sortable="custom" prop="severity">
                <template #default="{ row }">
                  <el-tag :type="severityTagType(row.severity)" size="small">{{ row.severity_label }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="责任人" width="76" align="center">
                <template #default="{ row }">{{ row.handler || '-' }}</template>
              </el-table-column>
              <el-table-column label="解决时间" width="136" align="center" sortable="custom" prop="planned_close_date">
                <template #default="{ row }">
                  <div class="date-cell">
                    <span :class="{ 'is-overdue-text': row.is_overdue }">{{ row.planned_close_date || '-' }}</span>
                    <span v-if="row.is_overdue" class="overdue-days">逾期{{ row.overdue_days }}天</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-tag :type="statusTagType(row.status)" size="small">{{ row.status_label }}</el-tag>
                </template>
              </el-table-column>
              <!-- 操作列：固定两列栅格（56px + 56px，gap 6），单/双按钮行左边缘始终对齐
                   按钮为**浅底胶囊**（浅蓝=编辑 / 浅绿=关闭 / 浅灰=已关闭禁用），不再用纯文字 link -->
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row }">
                  <div v-if="canTouchIssues" class="op-cell">
                    <el-button size="small" class="op-btn is-edit" @click="openEdit(row)">编辑</el-button>
                    <!-- 关闭：**始终渲染**，已关闭行浅灰禁用（不隐藏 → 保证按钮位置一致）
                         点确认 → PATCH status=closed → 整表刷新后本按钮变灰 -->
                    <el-button
                      size="small"
                      class="op-btn is-close"
                      :disabled="row.status === 'closed'"
                      :title="row.status === 'closed' ? '该异常已关闭' : '关闭该异常'"
                      @click="onCloseIssue(row)"
                    >关闭</el-button>
                  </div>
                  <span v-else>-</span>
                </template>
              </el-table-column>
          </el-table>
          </div>
          <el-empty v-if="!items.length && !loading" description="当月暂无问题记录" />
        </div>
      </el-col>

      <!-- 右侧：三图竖排（md 及以下自动落到主表下方） -->
      <!-- 右：三图竖排 -->
      <el-col :span="24" class="col-side">
        <div class="block-card">
          <div class="block-header"><span class="block-title">按流转状态分布</span></div>
          <div ref="statusChartRef" class="chart-box"></div>
          <div class="block-header chart-header"><span class="block-title">按来源部门（大区）分布</span></div>
          <div ref="areaChartRef" class="chart-box"></div>
          <div class="block-header chart-header"><span class="block-title">按优先级分布</span></div>
          <div ref="severityChartRef" class="chart-box"></div>
        </div>
      </el-col>
    </el-row>

    <!-- ④ 编辑弹窗（逻辑不变） -->
    <el-dialog
      v-model="editVisible"
      :title="`编辑问题（#${editForm.id}）`"
      width="520px"
      append-to-body
      :close-on-click-modal="false"
    >
      <el-form label-width="96px" label-position="right">
        <el-form-item label="项目">
          <span class="edit-readonly">{{ editForm.project_name }}</span>
        </el-form-item>
        <el-form-item label="问题描述">
          <el-input v-model="editForm.reason_detail" type="textarea" :rows="3" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="严重等级">
          <el-select v-model="editForm.severity" style="width: 100%">
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>
        </el-form-item>
        <el-form-item label="责任人">
          <el-input v-model="editForm.handler" placeholder="责任人姓名" maxlength="64" />
        </el-form-item>
        <el-form-item label="解决时间">
          <el-date-picker
            v-model="editForm.planned_close_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option label="计划中" value="pending" />
            <el-option label="执行中" value="processing" />
            <el-option label="已完成" value="closed" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 问题管控看板（v7.10 · 2026-11 布局优化）
 *
 * 布局（用户指定，首屏信息密度优先）：
 *   ① 筛选条（sticky 吸顶）
 *   ② 5 张指标卡一行（逾期未关闭并入本行，红卡可点击联动筛选）
 *   ③ 左 16 = 主问题列表；右 8 = 三个图表竖排（md 及以下图表落到主表下方）
 *   ④ 原「逾期未关闭事项明细」整表已删除（与主列表内容 100% 重复）
 *
 * ⚠️ 数据/接口/筛选/排序/编辑逻辑与上一版**逐行一致**，本次只动结构与样式。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, RefreshLeft } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import { fetchIssueBoard, patchIssue } from '../api/issues'
import { fetchProjects } from '../api/node'

const store = useProjectStore()
const auth = useAuthStore()

const loading = ref(false)
const items = ref([])
const kpis = ref({ total: 0, closed: 0, open: 0, overdue: 0, close_rate: 0, target_rate: 100 })
const byStatus = ref([])
const bySeverity = ref([])
const byArea = ref([])
const today = ref('')

const filters = reactive({ status: '', severity: '', project_id: null, keyword: '', overdue_only: false })
const projectOptions = ref([])

// 前端排序（后端已按「超期→等级→解决时间」排好，这里只处理表头点击）
const sortState = reactive({ prop: '', order: '' })
const sortedItems = computed(() => {
  const arr = [...items.value]
  if (!sortState.prop || !sortState.order) return arr
  const sevWeight = { high: 0, medium: 1, low: 2 }
  const dir = sortState.order === 'ascending' ? 1 : -1
  arr.sort((a, b) => {
    if (sortState.prop === 'severity') {
      return (sevWeight[a.severity] - sevWeight[b.severity]) * dir
    }
    if (sortState.prop === 'planned_close_date') {
      const av = a.planned_close_date || '9999-99-99'
      const bv = b.planned_close_date || '9999-99-99'
      return av < bv ? -1 * dir : av > bv ? 1 * dir : 0
    }
    return 0
  })
  return arr
})

/**
 * 是否可操作问题（2026-11-11 用户口径：**区域负责人也要能编辑/关闭**，但仅限本大区）。
 *
 * - 前端只负责「显示按钮」；真正的越权拦截在后端 PATCH（大区不符 → 403 OUT_OF_SCOPE）。
 * - 大区账号看到的列表本身已由后端 `get_scope_big_area` 隔离，故无需再前端过滤。
 * - 字段名：`store/auth.js` 提供 `isAdmin`（role==='admin'）与 `isBigArea`（role==='big_area'）。
 */
const canTouchIssues = computed(() => auth.isAdmin || auth.isBigArea)

const rateColor = (rate) => (rate >= 100 ? '#38a169' : rate >= 60 ? '#3182ce' : '#e53e3e')
const severityTagType = (sev) => (sev === 'high' ? 'danger' : sev === 'medium' ? 'warning' : 'info')
const statusTagType = (st) => (st === 'closed' ? 'success' : st === 'processing' ? 'primary' : 'info')
// 超期行：左侧 3px 红条（inset box-shadow，不占布局）+ 不再整行浅红底（多行超期时避免一片红）
const rowStyle = ({ row }) => ({ height: '38px', ...(row.is_overdue ? { boxShadow: 'inset 3px 0 0 #e53e3e' } : {}) })

function onSortChange({ prop, order }) {
  sortState.prop = prop || ''
  sortState.order = order || ''
}

/** 重置所有筛选条件（保留共享月份）后重新拉取。 */
function resetFilters() {
  filters.status = ''
  filters.severity = ''
  filters.project_id = null
  filters.keyword = ''
  filters.overdue_only = false
  load()
}

/** 点击「逾期未关闭」卡：切换只看逾期（与复选框状态联动，可见可逆）。 */
function toggleOverdue() {
  filters.overdue_only = !filters.overdue_only
  load()
}

// ---------------- 图表 ----------------
const statusChartRef = ref(null)
const areaChartRef = ref(null)
const severityChartRef = ref(null)
let statusChart = null
let areaChart = null
let severityChart = null

const STATUS_COLORS = { pending: '#3182ce', processing: '#00b5d8', closed: '#38a169' }
const SEVERITY_COLORS = { high: '#e53e3e', medium: '#dd6b20', low: '#718096' }

function renderStatusChart() {
  if (!statusChart) return
  const data = byStatus.value.map((d) => ({
    name: d.label,
    value: d.count,
    itemStyle: { color: STATUS_COLORS[d.key] || '#718096' },
  }))
  statusChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    legend: { bottom: 0, itemWidth: 10, itemHeight: 8, textStyle: { color: '#4a5568', fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],        // 环形更细，给图例留高度
      center: ['50%', '42%'],
      avoidLabelOverlap: true,
      label: { show: false },         // 空间有限：隐藏引导线标签，只留图例
      labelLine: { show: false },
      data,
    }],
  }, true)
}

function renderAreaChart() {
  if (!areaChart) return
  const labels = byArea.value.map((d) => d.label)
  const values = byArea.value.map((d) => d.count)
  areaChart.setOption({
    grid: { left: 6, right: 12, top: 18, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#4a5568', fontSize: 11, interval: 0, rotate: labels.length > 4 ? 25 : 0 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { show: false },     // 只留数值标签
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },     // 隐藏网格线
    },
    series: [{
      type: 'bar',
      barMaxWidth: 26,
      itemStyle: { color: '#3182ce', borderRadius: [4, 4, 0, 0] },
      data: values,
      label: { show: true, position: 'top', color: '#4a5568', fontSize: 11 },
    }],
  }, true)
}

function renderSeverityChart() {
  if (!severityChart) return
  const labels = bySeverity.value.map((d) => d.label)
  const colors = bySeverity.value.map((d) => SEVERITY_COLORS[d.key] || '#718096')
  const values = bySeverity.value.map((d) => d.count)
  severityChart.setOption({
    grid: { left: 6, right: 12, top: 18, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#4a5568', fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 32,
      data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] } })),
      label: { show: true, position: 'top', color: '#4a5568', fontSize: 11 },
    }],
  }, true)
}

function resizeCharts() {
  statusChart?.resize()
  areaChart?.resize()
  severityChart?.resize()
}

// ---------------- 数据加载 ----------------
async function loadProjectOptions() {
  try {
    const res = await fetchProjects({ page: 1, page_size: 1000 })
    projectOptions.value = (res?.items || []).map((p) => ({
      id: p.id,
      name: String(p.project_name || '').replace(/\s+/g, ' ').trim(),
    }))
  } catch (e) {
    projectOptions.value = []
  }
}

async function load() {
  if (typeof store.ensureMonth === 'function') store.ensureMonth()
  loading.value = true
  try {
    const res = await fetchIssueBoard({
      month: store.filters.month || undefined,
      status: filters.status || undefined,
      severity: filters.severity || undefined,
      project_id: filters.project_id || undefined,
      overdue_only: filters.overdue_only || undefined,
      keyword: filters.keyword || undefined,
    })
    items.value = res?.items || []
    kpis.value = res?.kpis || kpis.value
    byStatus.value = res?.by_status || []
    bySeverity.value = res?.by_severity || []
    byArea.value = res?.by_area || []
    today.value = res?.today || ''
    renderStatusChart()
    renderAreaChart()
    renderSeverityChart()
    // 数据刷新后容器尺寸可能变化（等高/滚动条），再对齐一次 canvas
    nextTick(() => resizeCharts())
  } catch (e) {
    ElMessage.error('加载问题看板失败')
  } finally {
    loading.value = false
  }
}

// ---------------- 编辑 ----------------
const editVisible = ref(false)
const saving = ref(false)
const editForm = reactive({
  id: null, project_name: '', reason_detail: '', severity: 'medium',
  handler: '', planned_close_date: null, status: 'pending',
})

/**
 * 关闭一条异常（用户要求：异常情况区域可直接关闭，关闭后恢复默认状态）。
 *
 * 流程：二次确认 → PATCH status=closed（后端自动写 closed_at）→ 成功提示 → load() 刷新。
 * 刷新后自动达成 4 点反馈：①状态标签变「已完成」②该行不再有关闭按钮
 * ③KPI 已关闭 +1 / 未关闭 -1 / 关闭率上升 ④按排序规则重排（已关闭不再超期优先，可能下移）。
 *
 * @param {object} row 当前行（至少含 id / process_name / status）
 */
async function onCloseIssue(row) {
  if (!canTouchIssues.value || !row || row.status === 'closed') return
  try {
    await ElMessageBox.confirm(
      '确认关闭该异常？关闭后将从「未关闭」统计中移除。',
      '关闭异常',
      { type: 'warning', confirmButtonText: '确认关闭', cancelButtonText: '取消' },
    )
  } catch (e) {
    return   // 取消：不做任何改动
  }
  try {
    await patchIssue(row.id, { status: 'closed' })
    // ElMessage 只传一个参数（项目踩过坑）
    ElMessage.success('已关闭')
    await load()
  } catch (e) {
    // 失败不改本地状态：不乐观更新，列表保持原样
    ElMessage.error(e?.response?.data?.detail || '关闭失败')
  }
}

function openEdit(row) {
  if (!canTouchIssues.value) return
  editForm.id = row.id
  editForm.project_name = row.project_name
  editForm.reason_detail = row.reason_detail
  editForm.severity = row.severity
  editForm.handler = row.handler || ''
  editForm.planned_close_date = row.planned_close_date || null
  editForm.status = row.status
  editVisible.value = true
}

async function submitEdit() {
  saving.value = true
  try {
    const payload = {
      severity: editForm.severity,
      status: editForm.status,
      handler: editForm.handler || '',
      reason_detail: editForm.reason_detail || '',
      planned_close_date: editForm.planned_close_date || null,
    }
    await patchIssue(editForm.id, payload)
    // ElMessage 只传一个参数（项目踩过坑）
    ElMessage.success('已保存，看板已刷新')
    editVisible.value = false
    await load()   // 指标 / 图表 / 列表实时刷新
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

watch(() => store.filters.month, load)

onMounted(async () => {
  // ① 先 init 图表（DOM 已挂载，容器有宽高），再拉数据 → 数据回来直接 setOption
  if (statusChartRef.value) statusChart = echarts.init(statusChartRef.value)
  if (areaChartRef.value) areaChart = echarts.init(areaChartRef.value)
  if (severityChartRef.value) severityChart = echarts.init(severityChartRef.value)
  window.addEventListener('resize', resizeCharts)
  // ② 项目下拉与看板数据并行
  await Promise.all([loadProjectOptions(), load()])
  // ③ 布局稳定后再 resize 一次（首屏出现滚动条会改变容器宽度）
  setTimeout(resizeCharts, 300)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  statusChart?.dispose()
  areaChart?.dispose()
  severityChart?.dispose()
  statusChart = areaChart = severityChart = null
})
</script>

<style scoped>
.issue-wrap { display: flex; flex-direction: column; gap: 12px; }

/* ① 筛选条：sticky 吸顶（滚动时始终可操作；白底+阴影压住下方内容） */
.filter-bar {
  position: sticky;
  top: 0;
  z-index: 9;
  padding: 12px 16px;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(26, 54, 93, 0.06);
}
.toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.toolbar-right { margin-left: auto; display: flex; gap: 10px; }

/* ② 指标行：flex 均分 5 卡，一行放完 */
.kpi-row { display: flex; gap: 16px; flex-wrap: wrap; }
.kpi-card {
  flex: 1 1 0;
  min-width: 0;
  min-height: 96px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 18px;
}
.kpi-value {
  font-size: 32px;
  font-weight: 700;
  color: #1a365d;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}
.kpi-label { font-size: 13px; color: #718096; margin-top: 2px; }
.kpi-sub { font-size: 11px; color: #a0aec0; margin-top: 2px; }
.kpi-rate { flex-direction: row; align-items: center; gap: 12px; }
.kpi-rate-text { display: flex; flex-direction: column; }

/* 第 5 卡：逾期未关闭（红卡 + 点击联动筛选） */
.kpi-danger {
  background: #fff5f5;
  border: 1px solid #fed7d7;
  cursor: pointer;
  transition: box-shadow .2s;
}
.kpi-danger:hover { box-shadow: 0 2px 10px rgba(229, 62, 62, 0.15); }
.kpi-danger.is-active { border-color: #e53e3e; box-shadow: 0 0 0 2px rgba(229, 62, 62, 0.12); }
.pulse-dot {
  display: inline-block;
  width: 8px; height: 8px;
  margin-left: 8px;
  border-radius: 50%;
  background: #e53e3e;
  vertical-align: 8px;
  animation: kpiPulse 1.6s ease-out infinite;
}
@keyframes kpiPulse {
  0% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0.45); }
  70% { box-shadow: 0 0 0 8px rgba(229, 62, 62, 0); }
  100% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0); }
}

/* ③ 主区：左右 16/8 只在 ≥1400px 生效
   说明：Element Plus 的 lg 断点是 1200，但 1280 宽度下左栏仅 ~850px，
   主表 8 列（最小宽度合计约 1010px）会只能横向滚动、图表也被压窄 →
   因此把「并排」阈值提到 1400px，1280 及以下自动改为上下堆叠（用户验收项 3）。 */
.main-row { margin-top: 0; }
@media (min-width: 1400px) {
  .col-main { flex: 0 0 66.6667%; max-width: 66.6667%; display: flex; }
  .col-side { flex: 0 0 33.3333%; max-width: 33.3333%; display: flex; }
  /* 🔴 卡片必须显式撑满：el-col 变成 flex 容器后，卡片默认按内容收缩，
     会导致右侧图表容器只有 ~140px 宽（canvas 被压扁、图例被裁）。 */
  .col-main > .block-card,
  .col-side > .block-card { flex: 1 1 auto; min-width: 0; width: 100%; }
}
/* <1400：两列上下堆叠，卡片不再等分高度（否则右侧会被拉出大片空白） */
@media (max-width: 1399px) {
  .block-card { height: auto; }
  .table-wrap :deep(.el-table) { height: auto !important; }
}
.block-card {
  background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 14px 16px;
  /* 等高：卡片自身成为 flex 容器，表格区用 flex:1 撑满（多余空白落在表格内，不在卡片底部） */
  display: flex; flex-direction: column; height: 100%;
}
.block-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex: 0 0 auto; }
.block-title { font-size: 13px; font-weight: 600; color: #1a365d; }
.table-wrap { flex: 1 1 auto; min-height: 0; display: flex; }
.table-wrap :deep(.el-table) { flex: 1 1 auto; }
/* 三块图表之间的间隔收紧到 10px（配合等高） */
.chart-header { margin-top: 10px; }
.chart-box { width: 100%; height: 96px; flex: 0 0 auto; }

.date-cell { display: flex; align-items: center; justify-content: center; gap: 4px; white-space: nowrap; font-size: 12px; }
/* 表头高度收紧（38 行高 + 36 表头，与右侧三图总高更接近） */
.table-wrap :deep(.el-table__header th) { height: 36px; padding: 4px 0; }
.table-wrap :deep(.el-table__body td) { padding: 4px 0; }
.is-overdue-text { color: #e53e3e; font-weight: 600; }
.overdue-days {
  color: #e53e3e;
  font-size: 10px;
  border: 1px solid #fed7d7;
  border-radius: 4px;
  padding: 0 4px;
  white-space: nowrap;
}
.edit-readonly { color: #4a5568; }
/* 操作列：固定两列栅格（56 + 56，gap 6），单/双按钮行左边缘恒等（差值 0px） */
.op-cell {
  display: grid;
  grid-template-columns: 48px 48px;
  gap: 6px;
  align-items: center;
  justify-content: start;   /* 整体左对齐（不居中） */
}
/* 浅底胶囊按钮：24px 高、4px 圆角、12px 字号，三态（normal / hover / disabled） */
.op-cell .op-btn {
  /* 48px 放 2 个 12px 汉字 + 左右 padding 各 4px 足够；操作列 130 内不再被裁切
     （旧值 56×2 + gap6 + 单元格 padding 24 = 142 > 130 → 右侧 12px 被 overflow:hidden 切掉） */
  width: 48px;
  min-width: 48px;
  height: 24px;
  padding: 0 4px;
  border-radius: 4px;
  font-size: 12px;
  text-align: center;
  justify-content: center;
  box-shadow: none;
}
/* 编辑：浅蓝底 */
.op-cell .op-btn.is-edit {
  background: #ebf8ff !important;
  color: #3182ce !important;
  border: 1px solid #bee3f8 !important;
}
.op-cell .op-btn.is-edit:not(.is-disabled):hover {
  background: #d6ecff !important;
  border-color: #90cdf4 !important;
}
/* 关闭：浅绿底 */
.op-cell .op-btn.is-close {
  background: #f0fff4 !important;
  color: #38a169 !important;
  border: 1px solid #c6f6d5 !important;
}
.op-cell .op-btn.is-close:not(.is-disabled):hover {
  background: #dcfce7 !important;
  border-color: #9ae6b4 !important;
}
/* 已关闭：浅灰底 + 灰字 + 不可点（明确"已关闭"而不是隐藏） */
.op-cell .op-btn.is-close.is-disabled,
.op-cell .op-btn.is-close.is-disabled:hover,
.op-cell .op-btn.is-close.is-disabled:focus {
  background: #f7fafc !important;
  color: #c0c4cc !important;
  border-color: #e2e8f0 !important;
  cursor: not-allowed;
}

/* ④ 响应式：lg 以下图表自动落到主表下方（栅格顺序天然如此），图表略增高 */
@media (max-width: 1399px) {
  .chart-box { height: 130px; }
}
@media (max-width: 768px) {
  .toolbar-right { margin-left: 0; }
  .kpi-card { padding: 12px 14px; min-height: 84px; }
  .kpi-value { font-size: 26px; }
}
</style>

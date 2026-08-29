<template>
  <div class="page-wrap">
    <!-- ① 左侧一级视图切换栏 -->
    <div class="page-layout">
      <div class="side-menu">
        <el-menu :default-active="activeView" class="view-switch-menu" @select="handleViewSwitch">
          <el-menu-item index="production">
            <el-icon><TrendCharts /></el-icon>
            <span>生产进度总览</span>
          </el-menu-item>
          <el-menu-item index="schedule">
            <el-icon><DocumentChecked /></el-icon>
            <span>排产计划总览</span>
          </el-menu-item>
          <el-menu-item index="ranking">
            <el-icon><Trophy /></el-icon>
            <span>出品排名总览</span>
          </el-menu-item>
        </el-menu>
      </div>

      <div class="main-content">
        <!-- ========== 生产进度总览（原主页面，逻辑不变） ========== -->
        <template v-if="activeView === 'production'">
          <!-- 标题栏 -->
          <div class="block-header page-title">
            <span class="icon"></span>
            <span class="block-title">塔筒生产进度总览</span>
            <span class="block-subtitle">按月度调度令建项目 · 实时跟踪各风场塔筒生产进度与风险</span>
          </div>

    <!-- ② 概览指标卡区 -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-value">{{ stats.total_projects }}</div>
        <div class="kpi-label">在产项目总数</div>
      </div>
      <div class="kpi-card kpi-warning">
        <div class="kpi-value" style="color:#f6ad55;">{{ stats.warning_projects }}</div>
        <div class="kpi-label">预警项目</div>
      </div>
      <div class="kpi-card kpi-delayed">
        <div class="kpi-value" style="color:#e53e3e;">{{ stats.delayed_projects }}</div>
        <div class="kpi-label">延期项目</div>
      </div>
      <div class="kpi-card kpi-blue">
        <div class="kpi-value">{{ stats.monthly_plan_total }}</div>
        <div class="kpi-label">本月计划出品总量</div>
      </div>
    </div>

    <!-- ③ 导入月度调度令卡片 -->
    <div class="block-card">
      <div class="block-header">
        <span class="icon"></span>
        <span class="block-title">导入月度调度令</span>
        <span class="block-subtitle">通过 Excel 批量创建项目（必填：项目名称/钢塔厂家/本月计划/交付负责人）</span>
      </div>
      <DispatchImport :disabled="!auth.canEdit" @imported="onDispatchImported" />
    </div>

    <!-- ④ 搜索/筛选栏卡片 -->
    <div class="block-card">
      <div class="search-bar">
        <el-input
          v-model="filterForm.keyword"
          placeholder="搜索项目名称 / 机型"
          clearable
          style="width: 240px"
          @input="onFilterChange"
          @clear="onFilterClear('keyword')"
        />
        <el-select
          v-model="filterForm.person"
          placeholder="交付负责人"
          clearable
          filterable
          style="width: 180px"
          @change="onFilterChange"
          @clear="onFilterClear('person')"
        >
          <el-option v-for="p in store.allPersons" :key="p" :label="p" :value="p" />
        </el-select>
        <!-- 大区负责人筛选：仅管理员可见（大区账号区域已锁定，隐藏下拉避免歧义；后端亦强制隔离） -->
        <el-select
          v-if="auth.isAdmin"
          v-model="filterForm.bigAreaPerson"
          placeholder="大区负责人"
          clearable
          filterable
          style="width: 180px"
          @change="onFilterChange"
          @clear="onFilterClear('bigAreaPerson')"
        >
          <el-option v-for="p in store.allBigAreaPersons" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select
          v-model="filterForm.status"
          placeholder="项目状态"
          clearable
          style="width: 160px"
          @change="onFilterChange"
          @clear="onFilterClear('status')"
        >
          <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-date-picker
          v-model="store.filters.month"
          type="month"
          value-format="YYYY-MM"
          placeholder="选择调度令月份"
          style="width: 160px"
          @change="onMonthChange"
        />
        <el-button :icon="Download" :loading="exporting" @click="onExport">导出</el-button>
        <el-button type="primary" :icon="Refresh" @click="onRefresh">刷新</el-button>
      </div>
    </div>

    <!-- ⑤ 项目表格卡片 -->
    <div class="block-card">
      <div class="block-header">
        <span class="icon"></span>
        <span class="block-title">项目列表</span>
        <span class="block-subtitle">共 {{ store.pagination.total }} 个项目</span>
        <el-button
          class="add-btn"
          type="primary"
          :icon="Plus"
          :disabled="!auth.canEdit"
          @click="addVisible = true"
        >手动添加项目</el-button>
      </div>
      <el-table v-if="store.projects.length || store.loading" :data="store.projects" v-loading="store.loading" stripe>
        <el-table-column prop="project_name" label="项目名称" min-width="180" />
        <el-table-column prop="machine_type" label="机型" min-width="120" />
        <el-table-column prop="factory_name" label="钢塔厂家" min-width="140" />
        <el-table-column prop="contract_count" label="合同总数" width="100" align="right">
          <template #default="{ row }">
            <span>{{ row.contract_count ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_month_output" label="截止上月" width="100" align="right" />
        <el-table-column prop="monthly_plan" label="本月计划" width="100" align="right" />
        <el-table-column label="整体进度" width="180" align="center">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="Number(row.progress_pct || 0)"
                :stroke-width="10"
                :show-text="false"
                :color="progressColor"
                class="list-progress"
              />
              <span class="progress-text">{{ Number(row.progress_pct || 0).toFixed(1) }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="delivery_person" label="交付负责人" width="120" />
        <el-table-column prop="big_area_person" label="大区负责人" width="120">
          <template #default="{ row }">
            <span class="region-cell">{{ row.big_area_person || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="remarks" label="备注" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="remark-cell">{{ row.remarks || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="风险状态" width="100">
          <template #default="{ row }">
            <span class="status-pill" :style="riskStyle(row.risk_level)">{{ riskLabel(row.risk_level) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <div class="op-btns">
              <el-button size="small" type="primary" @click="goDetail(row)">详细</el-button>
              <el-button size="small" type="warning" plain :disabled="!auth.canEdit" @click="onEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain :disabled="!auth.canEdit" @click="onDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <!-- 空态（非报错）：当前筛选/隔离范围内暂无项目数据 -->
      <el-empty
        v-else
        description="当前大区暂无项目数据（请管理员先导入调度令）"
        style="padding: 32px 0;"
      />
    </div>

    <!-- ⑥ 分页条 -->
    <div class="block-card page-bar">
      <el-select
        v-model="pageSize"
        style="width: 120px"
        @change="onPageSizeChange"
      >
        <el-option v-for="s in pageSizes" :key="s" :label="`${s} 条/页`" :value="s" />
      </el-select>
      <el-button :disabled="store.pagination.page <= 1" @click="onPrev">上一页</el-button>
      <el-button :disabled="store.pagination.page >= totalPages" @click="onNext">下一页</el-button>
      <span class="page-info">
        共 {{ store.pagination.total }} 条 第 {{ store.pagination.page }}/{{ totalPages }} 页
      </span>
    </div>

    <AddProjectDialog v-model="addVisible" @added="onAdded" />
    <EditProjectDialog v-model="editVisible" :project="editTarget" @updated="onUpdated" />
        </template>

        <!-- ========== 排产计划总览（副页面） ========== -->
        <SchedulePlanOverview v-else-if="activeView === 'schedule'" />

        <!-- ========== 出品排名总览（副页面） ========== -->
        <ProductionRankingOverview v-else-if="activeView === 'ranking'" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, TrendCharts, DocumentChecked, Trophy, Download } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as XLSX from 'xlsx'
import { saveAs } from 'file-saver'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import { deleteProject as deleteProjectApi, fetchExportProjects } from '../api/node'
import DispatchImport from '../components/DispatchImport.vue'
import AddProjectDialog from '../components/AddProjectDialog.vue'
import EditProjectDialog from '../components/EditProjectDialog.vue'
import SchedulePlanOverview from '../components/SchedulePlanOverview.vue'
import ProductionRankingOverview from '../components/ProductionRankingOverview.vue'

const store = useProjectStore()
const router = useRouter()
const auth = useAuthStore()   // 按钮级权限：管理员可编辑，普通账号只读
const exporting = ref(false)  // 导出中状态

// 左侧一级视图切换：production 生产进度总览 / schedule 排产计划总览
const activeView = ref('production')
function handleViewSwitch(index) {
  activeView.value = index
}

// 首页总览 KPI（字段与 /api/dashboard/stats 一致）
const stats = computed(() => store.dashboard)

const addVisible = ref(false)
const editVisible = ref(false)
const editTarget = ref(null)

// 本地筛选表单（双向绑定，变化时回写 store 并重置页码）
const filterForm = reactive({
  keyword: store.filters.keyword,
  person: store.filters.person,
  bigAreaPerson: store.filters.bigAreaPerson,
  status: store.filters.status,
})

const statusOptions = [
  { label: '全部', value: 'all' },
  { label: '正常', value: 'normal' },
  { label: '预警', value: 'warning' },
  { label: '延期', value: 'delayed' },
]

const pageSizes = [10, 20, 50, 100]
const pageSize = ref(store.pagination.page_size)

const totalPages = computed(() =>
  Math.max(1, Math.ceil((store.pagination.total || 0) / (store.pagination.page_size || 10)))
)

// 交付负责人下拉项：使用全量列表（store.allPersons），与当前筛选结果隔离
// （旧实现基于当前表格行推导，会被筛选结果污染，已移除）

// 风险状态四色（normal 绿 / warning 黄 / delayed 红 / 未开始灰）
const riskColors = {
  normal: ['#f0fff4', '#38a169', '正常'],
  warning: ['#fffff0', '#d69e2e', '预警'],
  delayed: ['#fff5f5', '#e53e3e', '延期'],
}
const riskStyle = (level) => {
  const item = riskColors[level] || riskColors.normal
  return { background: item[0], color: item[1] }
}
const riskLabel = (level) => (riskColors[level] || riskColors.normal)[2]

// 进度条分段颜色（按百分比：>=50 绿 / >=20 蓝 / >0 橙 / 0 红）
const progressColor = [
  { color: '#38a169', percentage: 100 },
  { color: '#3182ce', percentage: 50 },
  { color: '#f6ad55', percentage: 20 },
  { color: '#e53e3e', percentage: 0 },
]

// 筛选变化 → 重置页码为 1 并加载
function onFilterChange() {
  store.pagination.page = 1
  store.loadProjects({
    keyword: filterForm.keyword,
    person: filterForm.person,
    bigAreaPerson: filterForm.bigAreaPerson,
    status: filterForm.status,
    page: 1,
  })
}

// 单个筛选字段清空（×）→ 同步表单并重新加载
function onFilterClear(field) {
  filterForm[field] = ''
  onFilterChange()
}

// 刷新 = 重置全部筛选条件 + 回到第 1 页 + 加载全量（保留共享月份）
function onRefresh() {
  filterForm.keyword = ''
  filterForm.person = ''
  // 大区账号区域锁定：刷新时保持锁定值（后端同样强制隔离，此处保持前端一致）
  filterForm.bigAreaPerson = auth.isAdmin ? '' : auth.lockedBigAreaName
  filterForm.status = 'all'
  store.pagination.page = 1
  store.loadProjects({ keyword: '', person: '', bigAreaPerson: filterForm.bigAreaPerson, status: 'all', page: 1 })
  store.loadDashboard()
}

// 月份切换：三页联动（共享 store.filters.month）→ 列表 + KPI 同步刷新
function onMonthChange() {
  store.pagination.page = 1
  store.loadProjects({ page: 1 })
  store.loadDashboard()
}

// 导出当前共享月份的计划完成情况（前端本地生成 xlsx）
async function onExport() {
  exporting.value = true
  try {
    const res = await fetchExportProjects(store.filters.month)
    const rows = (res.items || res.data?.items || [])
    const header = [['项目名称', '机型', '钢塔厂家', '合同总数', '截至上月进度', '本月计划', '整体进度(%)', '交付负责人', '大区负责人']]
    const body = rows.map(r => [
      r.project_name, r.machine_type, r.factory_name, r.contract_count ?? '',
      r.last_month_output, r.monthly_plan,
      (Number(r.progress_pct) || 0).toFixed(1), r.delivery_person, r.big_area_person,
    ])
    const ws = XLSX.utils.aoa_to_sheet([...header, ...body])
    ws['!cols'] = [
      { wch: 26 }, { wch: 14 }, { wch: 18 }, { wch: 12 },
      { wch: 14 }, { wch: 12 }, { wch: 14 }, { wch: 14 }, { wch: 12 },
    ]
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, '生产进度总览')
    const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
    saveAs(new Blob([buf], { type: 'application/octet-stream' }), `生产进度总览_${store.filters.month}.xlsx`)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败，请重试')
  } finally {
    exporting.value = false
  }
}

function onPrev() {
  if (store.pagination.page > 1) {
    store.pagination.page -= 1
    store.loadProjects({ page: store.pagination.page })
  }
}
function onNext() {
  if (store.pagination.page < totalPages.value) {
    store.pagination.page += 1
    store.loadProjects({ page: store.pagination.page })
  }
}
function onPageSizeChange(size) {
  store.pagination.page_size = size
  store.pagination.page = 1
  store.loadProjects({ page_size: size, page: 1 })
}

function goDetail(row) {
  router.push(`/projects/${row.id}`)
}

function onEdit(row) {
  editTarget.value = row
  editVisible.value = true
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除项目「${row.project_name}」吗？此操作不可撤销（含工序/异常/节点等关联数据）！`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch (e) {
    return   // 用户取消
  }
  try {
    await deleteProjectApi(row.id)
    ElMessage.success(`项目「${row.project_name}」已删除`)
    // 删除后回到第 1 页并刷新（避免当前页数据不足）
    store.loadProjects({ page: 1 })
    store.loadDashboard()
  } catch (e) {
    // 404/500 已由 axios 拦截器统一提示
  }
}

function onUpdated() {
  store.loadProjects({ page: store.pagination.page })
  store.loadDashboard()
}

function onDispatchImported(res) {
  store.loadProjects({ page: 1 })
  store.loadDashboard()
  // 调度令导入后：若后端已自动开通大区账号则提示数量，否则提示联系管理员发放密码
  const accountsReady = Number(res?.accounts_ready || 0)
  if (accountsReady > 0) {
    ElMessage.success(`已自动开通 ${accountsReady} 个大区账号`)
  } else {
    ElMessage.info('导入成功，可联系管理员为相应大区账号发放密码')
  }
}
function onAdded() {
  store.loadProjects({ page: 1 })
}

onMounted(() => {
  store.ensureMonth()            // 默认共享月份 = 当前自然月
  store.loadAllPersons()         // 加载全量交付负责人（下拉框数据源）
  store.loadAllBigAreaPersons()  // 加载全量大区负责人（下拉框数据源）
  // 大区账号：区域锁定，前端筛选同步锁定（隐藏下拉框；后端同样强制隔离，此处仅保持 UX 一致）
  filterForm.bigAreaPerson = auth.isAdmin ? '' : auth.lockedBigAreaName
  store.loadDashboard()
  store.loadProjects({ page: 1, bigAreaPerson: filterForm.bigAreaPerson })
})
</script>

<style scoped>
.page-wrap { padding: 24px; }
.page-layout { display: flex; gap: 20px; align-items: flex-start; }
.side-menu {
  width: 200px; flex-shrink: 0; background: #fff;
  border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px;
}
.side-menu :deep(.el-menu) { border-right: none; }
.side-menu :deep(.el-menu-item) { border-radius: 8px; margin-bottom: 4px; }
.side-menu :deep(.el-menu-item.is-active) {
  background: #1a365d; color: #fff; font-weight: 500;
}
.side-menu :deep(.el-menu-item:not(.is-active):hover) { background: #f4f6f9; }
.side-menu :deep(.el-menu-item .el-icon) { margin-right: 8px; }
.main-content { flex: 1; min-width: 0; }
.page-title { margin-bottom: 16px; }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.kpi-warning { border-top: 3px solid var(--color-warning); }
.kpi-delayed { border-top: 3px solid var(--color-red); }
.kpi-blue { border-top: 3px solid var(--color-blue); }
.add-btn { margin-left: auto; }
.page-bar { display: flex; align-items: center; gap: 12px; }
.page-info { margin-left: auto; color: var(--color-sub); font-size: 13px; }
.progress-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: center;
}
.list-progress {
  width: 120px;          /* 加宽，保证填充比例视觉可见 */
  display: inline-block;
}
.progress-text {
  font-size: 13px;
  color: #1a365d;
  font-weight: 500;
  min-width: 44px;
  text-align: right;
}

/* 操作列：三个按钮强制同一行 */
.op-btns {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;      /* 强制三个按钮同一行 */
  white-space: nowrap;
}
.op-btns .el-button {
  margin-left: 0;          /* 去掉 el-button 默认左边距，防止换行 */
}
/* 备注列：次要文字色弱化显示 */
.remark-cell {
  color: var(--color-sub);
  font-size: 13px;
}
/* 大区负责人列：次要文字色弱化显示（与备注同色系） */
.region-cell {
  color: var(--color-sub);
  font-size: 13px;
}
</style>

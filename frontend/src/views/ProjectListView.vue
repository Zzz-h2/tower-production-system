<template>
  <div class="page-wrap">
    <!-- ① 左侧一级视图切换栏（可收起/展开：收起后数据区获得更大可视宽度） -->
    <div class="page-layout">
      <div class="side-menu" :class="{ 'is-collapsed': sidebarCollapsed }">
        <el-menu
          :default-active="activeView"
          class="view-switch-menu"
          @select="handleViewSwitch"
        >
          <el-menu-item index="production" :title="sidebarCollapsed ? '生产进度总览' : ''">
            <el-icon><TrendCharts /></el-icon>
            <template #title><span class="menu-label">生产进度总览</span></template>
          </el-menu-item>
          <el-menu-item index="schedule" :title="sidebarCollapsed ? '排产计划总览' : ''">
            <el-icon><DocumentChecked /></el-icon>
            <template #title><span class="menu-label">排产计划总览</span></template>
          </el-menu-item>
          <el-menu-item index="ranking" :title="sidebarCollapsed ? '出品排名总览' : ''">
            <el-icon><Trophy /></el-icon>
            <template #title><span class="menu-label">出品排名总览</span></template>
          </el-menu-item>
          <el-menu-item index="submission" :title="sidebarCollapsed ? '提报情况总览' : ''">
            <el-icon><Calendar /></el-icon>
            <template #title><span class="menu-label">提报情况总览</span></template>
          </el-menu-item>
        </el-menu>
        <!-- 收起/展开按钮：始终可见（移动端也保留），点击切换并记忆到 localStorage -->
        <button
          class="collapse-toggle"
          type="button"
          :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
          :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
          @click="toggleSidebar"
        >
          <el-icon><component :is="sidebarCollapsed ? Expand : Fold" /></el-icon>
        </button>
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

    <!-- ② 概览指标卡区（2026-11：4 → 5 卡，在「预警」与「延期」之间插入第 4 态「异常」） -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-value">{{ stats.total_projects }}</div>
        <div class="kpi-label">在产项目总数</div>
      </div>
      <div class="kpi-card kpi-exception">
        <div class="kpi-value" style="color:#dd6b20;">{{ stats.exception_projects }}</div>
        <div class="kpi-label">异常项目</div>
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

    <!-- ③ 导入月度调度令（可折叠行：默认收起，整行点击展开/收起，交互语言同「填报进度」行） -->
    <div class="block-card import-card">
      <div
        class="block-header import-header"
        :class="{ 'is-open': importOpen, 'is-drag-over': importDragging }"
        @click="importOpen = !importOpen"
        @dragover="onImportDragOver"
        @dragleave="onImportDragLeave"
        @drop="onImportDrop"
      >
        <span class="icon"></span>
        <span class="block-title">📥 导入月度调度令</span>
        <span class="import-hint">{{ importHint }}</span>
        <span class="import-caret" :class="{ 'is-open': importOpen }"></span>
      </div>
      <!-- 展开区：@click.stop 隔离，区内控件操作不触发行折叠 -->
      <div v-show="importOpen" class="import-body" @click.stop>
        <div class="import-desc">通过 Excel 批量创建项目（必填：项目名称/钢塔厂家/本月计划/交付负责人）</div>
        <DispatchImport
          ref="dispatchImportRef"
          :disabled="!auth.canEdit"
          @imported="onDispatchImported"
        />
      </div>
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
          <el-option v-for="p in sortedPersons" :key="p" :label="p" :value="p" />
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
          <el-option v-for="p in sortedBigAreaPersons" :key="p" :label="p" :value="p" />
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
          :clearable="false"
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
        <!-- 列对齐规范（2026-10）：除「项目名称」左对齐外，其余列统一居中——
             表头与内容同列居中，视觉上文字正对列名下方。 -->
        <el-table-column prop="project_name" label="项目名称" min-width="220" align="left" />
        <el-table-column prop="machine_type" label="机型" min-width="120" align="center" />
        <el-table-column prop="factory_name" label="钢塔厂家" min-width="140" align="center" />
        <el-table-column prop="contract_count" label="合同总数" width="100" align="center">
          <template #default="{ row }">
            <span>{{ row.contract_count ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_month_output" label="截止上月" width="100" align="center" />
        <el-table-column prop="monthly_plan" label="本月计划" width="100" align="center" />
        <!-- 整体进度：宽度 180 → 210（原宽度下「进度条 + 百分比」溢出使 100.0% 换行）
             2026-11：加 el-tooltip —— 悬停显示「已完成 X 套 / 计划 Y 套」。
             X = completed_sets（已完成套数）；Y = monthly_plan（列表「本月计划」列同源，用户指定口径）。
             注意 Y 是调度令口径、与进度百分比分母（att_plan_qty 附件安装工序口径）不同源，
             X/Y 可能 ≠ 进度百分比 —— 用户知情选择，详见 progressTip() 注释，勿当 bug 改回。 -->
        <el-table-column label="整体进度" width="210" align="center">
          <template #default="{ row }">
            <el-tooltip
              :content="progressTip(row)"
              placement="top"
              effect="dark"
              :show-after="150"
            >
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
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="delivery_person" label="交付负责人" width="120" align="center" />
        <el-table-column prop="big_area_person" label="大区负责人" width="120" align="center">
          <template #default="{ row }">
            <span class="region-cell">{{ row.big_area_person || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="风险状态" width="100" align="center">
          <template #default="{ row }">
            <span class="status-pill" :style="riskStyle(row.risk_level)">{{ riskLabel(row.risk_level) }}</span>
          </template>
        </el-table-column>
        <!-- 2026-11 需求：去掉「备注」列表格列（原列内容全是「—」）。
             仅删展示列：row.remarks 数据仍在（列表接口照常返回），
             导出 Excel 的报表口径不含备注列，无需同步调整。 -->
        <!-- 操作列（2026-11 交互调整）：与排产总览「未上传排产计划」表同款 ——
             ① 表头「操作」居中于按钮组正上方（列宽收敛到按钮组实际宽度 + align="center"）；
             ② 按钮组贴住右边框（td.op-col .cell 改 flex + flex-end，**只作用于 td**，
                class-name 会同时落在 th 上，写成 .op-col .cell 会把表头也推到右边）；
             ③ 浅色小框包住按钮组（.op-group，边 #e2e8f0 / 底 #f8fafc，与页面色板一致）。 -->
        <el-table-column label="操作" width="190" align="center" fixed="right" class-name="op-col">
          <template #default="{ row }">
            <div class="op-group">
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

        <!-- ========== 提报情况总览（副页面） ========== -->
        <SubmissionOverview v-else-if="activeView === 'submission'" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, TrendCharts, DocumentChecked, Trophy, Calendar, Download, Fold, Expand } from '@element-plus/icons-vue'
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
import SubmissionOverview from '../components/SubmissionOverview.vue'

const store = useProjectStore()
const router = useRouter()
const auth = useAuthStore()   // 按钮级权限：管理员可编辑，普通账号只读
const exporting = ref(false)  // 导出中状态

// 左侧一级视图切换：production 生产进度总览 / schedule 排产计划总览
const activeView = ref('production')
function handleViewSwitch(index) {
  activeView.value = index   // 收起/展开只改宽度，不影响当前选中视图
  // 窄屏下展开态是浮层：选完视图自动收起，避免挡住内容
  if (typeof window !== 'undefined' && window.innerWidth < 768 && !sidebarCollapsed.value) {
    applyCollapse(true)
  }
}

// ============================================================
// 侧边栏收起 / 展开（2026-10）
// ------------------------------------------------------------
// · 收起后侧栏 200px → 64px，主内容区（flex:1）自动吃掉多出来的宽度
// · 状态持久化到 localStorage —— 刷新 / 切换视图后保持一致
// · **默认收起**（用户 2026-10 要求）：首次进入 / 清缓存后侧栏为收起态，把宽度让给数据区；
//   用户手动展开过则以 localStorage 记录为准，不会被强制改回收起
// ============================================================
const SIDEBAR_KEY = 'tower_sidebar_collapsed'
function readSidebarCollapsed() {
  try {
    const saved = localStorage.getItem(SIDEBAR_KEY)
    if (saved === '1') return true
    if (saved === '0') return false
  } catch { /* 隐私模式禁用 localStorage 时忽略 */ }
  return true   // 默认收起（首次访问 / 无记录时）；有记录则以用户上次选择为准
}
const sidebarCollapsed = ref(readSidebarCollapsed())
// 🔴 收起/展开**只切换一个布尔值**，由 CSS 同步驱动三层过渡（宽度 / 文字宽度 / 文字透明度）。
//    不再走「延迟切换 el-menu 的 collapse」—— 实测 el-menu 收起时文字 DOM 并不卸载，
//    延迟切换只会让文字先闪一下再淡入（比原来更糟）。
//    现在的时序：容器宽度与文字 max-width 用同一条 .2s 曲线同步推进，
//    文字 opacity 在展开时同步淡入、收起时提前 20ms 淡出 —— 三者同源，不会脱节。
function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  try { localStorage.setItem(SIDEBAR_KEY, sidebarCollapsed.value ? '1' : '0') } catch { /* 忽略 */ }
}
function applyCollapse(next) {
  if (sidebarCollapsed.value === next) return
  sidebarCollapsed.value = next
  try { localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0') } catch { /* 忽略 */ }
}

// ============================================================
// ③ 导入月度调度令：折叠行（默认收起，节省首屏空间）
// ------------------------------------------------------------
// 交互语言与项目详情页「填报进度」行完全一致：
//   整行可点 → 展开/收起；hover 背景微变 + cursor:pointer；折叠三角旋转 180°；
//   展开区内的控件用 @click.stop 隔离，操作控件不会误触行折叠。
// 顺带支持「收起态直接拖入 Excel」：自动展开 → 立刻解析（省去先展开再点选的两步）。
// ============================================================
const importOpen = ref(false)        // 默认收起（不持久化：每次进首页保持简洁）
const importDragging = ref(false)    // 拖拽悬停高亮（仅在拖着文件经过该行时）
const dispatchImportRef = ref(null)  // DispatchImport 组件实例（收起态拖入时直接触发解析）

const importHint = computed(() => {
  if (importDragging.value) return '松开即导入该 Excel 文件'
  if (importOpen.value) return '点击收起导入区'
  return '点击展开 / 拖拽 Excel 到此处导入'
})

/** 从 DataTransfer 中取第一个 Excel 文件（.xlsx/.xls）；没有则返回 null。 */
function pickExcelFile(event) {
  const files = event?.dataTransfer?.files
  if (!files || !files.length) return null
  for (const file of files) {
    if (/\.(xlsx|xls)$/i.test(file.name || '')) return file
  }
  return null
}

/** 拖拽内容是否含文件（用于判断要不要接管 dragover/drop）。 */
function isFileDrag(event) {
  const types = event?.dataTransfer?.types
  return !!types && Array.from(types).includes('Files')
}

// dragover 必须 preventDefault 才允许 drop（收起态也能直接拖入）
function onImportDragOver(event) {
  if (!isFileDrag(event)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
  importDragging.value = true
}

function onImportDragLeave(event) {
  // 只有真正离开整行才取消高亮（子元素之间移动会反复触发 leave）
  if (event?.currentTarget?.contains?.(event.relatedTarget)) return
  importDragging.value = false
}

async function onImportDrop(event) {
  if (!isFileDrag(event)) return
  event.preventDefault()
  importDragging.value = false
  const file = pickExcelFile(event)
  if (!file) {
    ElMessage.warning('请拖入 .xlsx / .xls 格式的调度令文件')
    return
  }
  if (!auth.canEdit) {
    ElMessage.warning('当前账号无导入权限，请联系管理员')
    return
  }
  // 收起态拖入 → 先展开，等 DOM 渲染完再把文件交给 DispatchImport 解析
  importOpen.value = true
  await nextTick()
  dispatchImportRef.value?.previewFile?.(file)
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
  { label: '异常', value: 'exception' },
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
//
// 2026-10：下拉选项按**姓名拼音首字母 A→Z** 排序。
// 后端返回的是插入/字典序（按 UTF-16 码点，中文实际等同于无意义顺序），
// 故在前端用 Intl.Collator('zh-CN') 做拼音比较——浏览器原生支持，无需引入拼音库。
// 用 Intl.Collator 而非每次调用 localeCompare：Collator 实例会缓存排序规则，列表较长时更快。
const zhNameCollator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

// 多音姓氏修正：ICU 拼音库对多音字只取**常用读音**，与姓氏读音不一致（会排错位置）。
// 做法是把首字换成**同音常用字**再交给 collator 比较——只影响排序 key，绝不改变显示文本。
// 典型：曾(céng→zēng，否则排到 C)、乐(lè→yuè，姓氏读岳)、单(shàn)、解(xiè)、查(zhā)…
// 未列出的姓氏走 collator 默认读音，通常正确。
const SURNAME_HOMOPHONE = {
  曾: '增', 乐: '岳', 单: '山', 解: '谢', 查: '扎', 仇: '求', 区: '欧',
  朴: '瓢', 翟: '宅', 覃: '秦', 缪: '妙', 盖: '葛', 员: '云', 种: '崇',
  折: '舌', 召: '邵', 秘: '必', 尉: '玉', 祭: '债', 阚: '看',
}
function nameSortKey(name) {
  const s = String(name ?? '')
  if (!s) return s
  const mapped = SURNAME_HOMOPHONE[s.charAt(0)]
  return mapped ? mapped + s.slice(1) : s
}
const sortByNamePinyin = (arr) =>
  [...(arr || [])].sort((a, b) => zhNameCollator.compare(nameSortKey(a), nameSortKey(b)))
const sortedPersons = computed(() => sortByNamePinyin(store.allPersons))
const sortedBigAreaPersons = computed(() => sortByNamePinyin(store.allBigAreaPersons))

// 风险状态四色（normal 绿 / exception 实心橙 / warning 黄 / delayed 红）
// exception 用**实心橙底白字**：与预警（淡黄底深黄字）区分层级——异常是第 4 态、优先级最高。
const riskColors = {
  normal: ['#f0fff4', '#38a169', '正常'],
  exception: ['#dd6b20', '#ffffff', '异常'],
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

/**
 * 「整体进度」单元格 hover 文案：`已完成 X 套 / 计划 Y 套`。
 *
 * ⚠️ 口径说明（用户 2026-11 指定，勿"修正"回去）：
 *   - X = row.completed_sets —— 已完成套数（后端列表聚合 att_actual_qty 原值）；
 *   - Y = row.monthly_plan —— **列表「本月计划」列的值**（调度令口径）。
 *     用户明确要求 Y 必须与「本月计划」列一致，因此 X/Y 与进度百分比的分母
 *     （att_plan_qty，附件安装工序口径）**不同源**，可能出现 X/Y ≠ 进度百分比
 *     （如 id=170：已完成 1 / 计划 4 = 25%，但进度条按 1/6 附件安装口径显示 16.7%）。
 *     这是用户知情选择的口径，不是 bug。
 *   - 后端 att_plan_qty 字段仍照常返回（db.py 聚合处未删），只是本 tooltip 不再使用。
 *
 * ⚠️ 禁止用 `progress_pct × 任意总量` 反算 X/Y：progress_pct 已四舍五入到 0.1，反算必失真。
 *
 * @param {object} row 项目列表行
 * @returns {string} tooltip 文案；本月计划为 0/NULL（调度令未填）时降级为只显示已完成套数
 */
function progressTip(row) {
  const done = Number(row?.completed_sets ?? 0) || 0
  // 计划套数 = 「本月计划」列（monthly_plan）。0 / null / 缺失 → 降级只报已完成套数，
  // 避免「/ 计划 0 套」让用户误以为数据异常。
  const planQty = Number(row?.monthly_plan ?? 0) || 0
  return planQty > 0 ? `已完成 ${done} 套 / 计划 ${planQty} 套` : `已完成 ${done} 套`
}

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

/**
 * 重新拉取筛选下拉选项，并校验当前选中值是否仍然有效。
 *
 * 用于「项目删除 / 编辑 / 新增 / 导入」之后：这些操作会改变交付负责人、大区负责人集合。
 * 若不刷新，已失效的选中值会被 el-select（单值 + filterable）原样渲染成标签，
 * 表现为「项目已删除，筛选栏仍残留旧记录，列表恒 0 条」。
 *
 * @param {object} [opts]
 * @param {boolean} [opts.reload=true] 清除了失效值时是否立即重跑列表查询
 * @returns {Promise<boolean>} 是否清除了失效的筛选值
 */
async function refreshFilterOptions({ reload = true } = {}) {
  await Promise.all([store.loadAllPersons(), store.loadAllBigAreaPersons()])
  const cleared = store.reconcilePersonFilter({
    // 大区账号的区域锁定值受后端强制隔离，不参与「失效清理」
    lockedBigArea: auth.isAdmin ? '' : auth.lockedBigAreaName,
  })
  // store.filters 是筛选值的唯一来源，清空后同步回本地表单
  filterForm.person = store.filters.person
  filterForm.bigAreaPerson = store.filters.bigAreaPerson
  if (!cleared.length) return false

  ElMessage.warning(
    `「${cleared.map((c) => c.value).join('、')}」已不存在，已自动清除对应筛选条件`
  )
  if (reload) {
    store.pagination.page = 1
    store.loadProjects({
      keyword: filterForm.keyword,
      person: filterForm.person,
      bigAreaPerson: filterForm.bigAreaPerson,
      status: filterForm.status,
      page: 1,
    })
    store.loadDashboard()
  }
  return true
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
  // 手动刷新时一并重取下拉选项，保证选项与被删改的项目同步
  refreshFilterOptions({ reload: false })
}

// 月份切换：三页联动（共享 store.filters.month）→ 列表 + KPI 同步刷新
function onMonthChange() {
  // 月份必填（2026-10）：清空后立刻回补当前月，避免退化成「全部月份」汇总
  store.ensureMonth()
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
    const header = [['项目名称', '机型', '钢塔厂家', '合同总数', '截至上月进度', '本月计划', '整体进度(%)', '交付负责人', '大区负责人', '风险状态']]
    const body = rows.map(r => [
      r.project_name, r.machine_type, r.factory_name, r.contract_count ?? '',
      r.last_month_output, r.monthly_plan,
      (Number(r.progress_pct) || 0).toFixed(1), r.delivery_person, r.big_area_person,
      // 风险状态：与列表 pill 同一套文案（后端 risk_level 单源，四态互斥）
      (riskColors[r.risk_level] || riskColors.normal)[2],
    ])
    const ws = XLSX.utils.aoa_to_sheet([...header, ...body])
    ws['!cols'] = [
      { wch: 26 }, { wch: 14 }, { wch: 18 }, { wch: 12 },
      { wch: 14 }, { wch: 12 }, { wch: 14 }, { wch: 14 }, { wch: 12 }, { wch: 10 },
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
    store.pagination.page = 1
    // 被删项目可能带走最后一位交付负责人 → 先重取选项并清理失效选中值，再刷列表
    await refreshFilterOptions({ reload: false })
    store.loadProjects({
      page: 1,
      person: filterForm.person,
      bigAreaPerson: filterForm.bigAreaPerson,
    })
    store.loadDashboard()
  } catch (e) {
    // 404/500 已由 axios 拦截器统一提示
  }
}

async function onUpdated() {
  // 编辑可能改动交付负责人/大区负责人 → 同步刷新下拉选项并清理失效值
  await refreshFilterOptions({ reload: false })
  store.loadProjects({
    page: store.pagination.page,
    person: filterForm.person,
    bigAreaPerson: filterForm.bigAreaPerson,
  })
  store.loadDashboard()
}

async function onDispatchImported(res) {
  // 导入会批量新增项目/负责人 → 同步刷新下拉选项并清理失效值
  await refreshFilterOptions({ reload: false })
  store.loadProjects({
    page: 1,
    person: filterForm.person,
    bigAreaPerson: filterForm.bigAreaPerson,
  })
  store.loadDashboard()
  // 调度令导入后：若后端已自动开通大区账号则提示数量，否则提示联系管理员发放密码
  const accountsReady = Number(res?.accounts_ready || 0)
  if (accountsReady > 0) {
    ElMessage.success(`已自动开通 ${accountsReady} 个大区账号`)
  } else {
    ElMessage.info('导入成功，可联系管理员为相应大区账号发放密码')
  }
}
async function onAdded() {
  await refreshFilterOptions({ reload: false })
  store.loadProjects({ page: 1 })
}

onMounted(async () => {
  store.ensureMonth()            // 默认共享月份 = 当前自然月
  // 大区账号：区域锁定，前端筛选同步锁定（隐藏下拉框；后端同样强制隔离，此处仅保持 UX 一致）
  filterForm.bigAreaPerson = auth.isAdmin ? '' : auth.lockedBigAreaName
  // 先重取下拉选项并清理失效选中值，再加载列表：
  // Pinia 未启用持久化，但筛选值在本次会话内跨路由留存，可能指向已被删除项目的负责人。
  await refreshFilterOptions({ reload: false })
  store.loadDashboard()
  store.loadProjects({
    page: 1,
    person: filterForm.person,
    bigAreaPerson: filterForm.bigAreaPerson,
  })
})
</script>

<style scoped>
.page-wrap { padding: 24px; }
.page-layout { display: flex; gap: 20px; align-items: flex-start; }
.side-menu {
  width: 200px; flex-shrink: 0; background: #fff;
  border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px;
  display: flex; flex-direction: column;
  /* 收起/展开：宽度与内边距一起过渡，避免图标在动画中途跳动 */
  transition: width .2s cubic-bezier(.4, 0, .2, 1), padding .2s cubic-bezier(.4, 0, .2, 1);
}
/* 收起态：把 Element Plus 的 collapse 宽度改小一点，保证 72px 侧栏内不溢出 */
.side-menu.is-collapsed { width: 72px; padding: 8px 4px; --el-menu-collapse-width: 60px; }
.side-menu :deep(.el-menu) { border-right: none; width: 100%; }
.side-menu :deep(.el-menu--collapse) { width: 100%; }
.side-menu :deep(.el-menu-item) { border-radius: 8px; margin-bottom: 4px; }
.side-menu.is-collapsed :deep(.el-menu-item) {
  padding-left: 0 !important; padding-right: 0 !important; justify-content: center;
}
.side-menu.is-collapsed :deep(.el-menu-item .el-icon) { margin-right: 0; }
.side-menu :deep(.el-menu-item.is-active) {
  background: #1a365d; color: #fff; font-weight: 500;
}
.side-menu :deep(.el-menu-item:not(.is-active):hover) { background: #f4f6f9; }
.side-menu :deep(.el-menu-item .el-icon) { margin-right: 8px; }

/* 文字显隐：与容器宽度同源过渡（不再依赖 el-menu 的 collapse / DOM 重建）。
   展开：max-width 与容器同步变宽，文字随之淡入 —— 视觉上"文字被容器推出来"，不会先于背景出现。
   收起：文字先淡出（.1s），随后宽度收缩，避免文字被硬裁。 */
.side-menu :deep(.menu-label) {
  display: inline-block; overflow: hidden; white-space: nowrap;
  max-width: 160px; opacity: 1;
  transition: max-width .2s cubic-bezier(.4, 0, .2, 1), opacity .14s ease;
}
.side-menu.is-collapsed :deep(.menu-label) {
  max-width: 0; opacity: 0;
  transition: max-width .2s cubic-bezier(.4, 0, .2, 1), opacity .1s ease;
}

/* 收起/展开按钮：贴侧栏底部，视觉语言与菜单项一致 */
.collapse-toggle {
  margin-top: 8px; width: 100%; height: 34px;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; border-radius: 8px;
  color: #718096; cursor: pointer; font-size: 16px;
  transition: background .18s ease, color .18s ease;
}
.collapse-toggle:hover { background: #f4f6f9; color: #1a365d; }
.collapse-toggle:focus-visible { outline: 2px solid #3182ce; outline-offset: -2px; }

/* 窄屏：压缩间距（初始收起状态由 JS 按 window.innerWidth 决定） */
@media (max-width: 768px) {
  .page-layout { gap: 10px; }
  .side-menu { padding: 6px; border-radius: 10px; }
  .side-menu.is-collapsed { width: 60px; padding: 6px 2px; --el-menu-collapse-width: 56px; }
  /* 展开态：改为浮层覆盖 —— 390px 屏宽下若仍走 flex 占位，内容区只剩 130px 无法使用 */
  .side-menu:not(.is-collapsed) {
    position: fixed; top: 8px; left: 8px; bottom: 8px; z-index: 2100;
    width: 200px; padding: 8px; border-radius: 12px;
    box-shadow: 0 10px 28px rgba(26, 54, 93, .18);
  }
}
.main-content { flex: 1; min-width: 0; }
.page-title { margin-bottom: 16px; }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);   /* 2026-11：4 → 5 卡（新增「异常项目」） */
  gap: 16px;
  margin-bottom: 16px;
}
.kpi-exception { border-top: 3px solid #dd6b20; }
.kpi-warning { border-top: 3px solid var(--color-warning); }
.kpi-delayed { border-top: 3px solid var(--color-red); }
.kpi-blue { border-top: 3px solid var(--color-blue); }
.add-btn { margin-left: auto; }
/* === ③ 导入月度调度令：折叠行（2026-10 界面优化） ===
   收起态 = 卡片内只有一行标题；展开态 = 标题 + 原有导入控件。
   hover 背景 / cursor / 三角旋转与项目详情页「填报进度」行同一套语言。 */
.import-card { padding: 0; }          /* 内边距交给行与展开区各自持有，hover 底色才能铺满整张卡 */
.import-header {
  padding: 16px 24px;
  margin-bottom: 0;
  cursor: pointer;
  border-radius: 12px;
  transition: background-color .12s, box-shadow .12s;
  user-select: none;
}
.import-header:hover { background: #f9fbfd; }
.import-header.is-open { background: #fbfdff; }
.import-header.is-open:hover { background: #f4f9fd; }
/* 拖拽悬停：整行高亮 + 内描边，提示「可以松手导入」 */
.import-header.is-drag-over,
.import-header.is-drag-over:hover {
  background: #ebf8ff;
  box-shadow: inset 0 0 0 2px #3182ce;
}
.import-hint {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-sub);
  white-space: nowrap;
}
.import-header.is-drag-over .import-hint { color: #2b6cb0; font-weight: 600; }
/* 折叠三角：CSS 边框画（与 ProcessDetailDialog 的 .fill-row-caret 同一手法），展开时旋转 180° */
.import-caret {
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid #a0aec0;
  transition: transform .15s, border-top-color .15s;
  flex-shrink: 0;
}
.import-header:hover .import-caret { border-top-color: #4a5568; }
.import-caret.is-open { transform: rotate(180deg); border-top-color: #2b6cb0; }
.import-body { padding: 2px 24px 20px; }
.import-desc { font-size: 13px; color: var(--color-sub); margin-bottom: 12px; }

.page-bar { display: flex; align-items: center; gap: 12px; }
.page-info { margin-left: auto; color: var(--color-sub); font-size: 13px; }
.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;              /* 12→8：与百分比拉开但不浪费横向空间 */
  justify-content: center;
  white-space: nowrap;   /* 整块不换行（关键：原 100.0% 被挤成两行） */
  cursor: help;          /* 提示「悬停可看已完成套数」（el-tooltip 触发区 = 整个单元格内容） */
}
.list-progress {
  width: 108px;          /* 120→108：给百分比留出安全宽度 */
  flex: 0 0 auto;
  display: inline-block;
}
.progress-text {
  font-size: 13px;
  color: #1a365d;
  font-weight: 500;
  min-width: 52px;       /* 44→52：容纳 "100.0%" 完整宽度 */
  text-align: right;
  white-space: nowrap;
  flex: 0 0 auto;
}

/* 操作列（2026-11）：与 SchedulePlanOverview「未上传排产计划」表同款按钮组样式。
   两组件 scoped 样式各自持有一份（10 行小段），不提全局 theme.css —— 避免污染项目里
   其它所有 el-table；后续若第三处也要用，再抽公共样式不迟。 */
.page-wrap :deep(td.op-col .cell) {
  display: flex;
  justify-content: flex-end;   /* 按钮组贴住单元格右缘（靠近表格右边框） */
  padding-right: 4px;          /* 右内边距收窄，小框贴近边框又不顶死 */
}
.op-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;                    /* 间距交给 gap，覆盖 el-button 相邻默认 12px 左边距 */
  padding: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.op-group .el-button + .el-button { margin-left: 0; }
/* 备注列已移除（2026-11）→ 原 .remark-cell 样式一并清理，避免死代码 */
/* 大区负责人列：次要文字色弱化显示 */
.region-cell {
  color: var(--color-sub);
  font-size: 13px;
}
</style>

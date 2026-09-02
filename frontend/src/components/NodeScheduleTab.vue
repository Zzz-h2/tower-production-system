<template>
  <div>
    <!-- 多负责人（v6.0）：负责人视图筛选器。默认「全部（汇总）」展示所有负责人工序总和 -->
    <div class="block-card mm-filter" v-if="managerOptions.length">
      <span class="mm-label">负责人视图：</span>
      <el-select
        v-model="selectedManager"
        placeholder="全部（汇总）"
        clearable
        style="width: 200px;"
        @change="reload"
      >
        <el-option label="全部（汇总）" value="" />
        <el-option v-for="m in managerOptions" :key="m.manager" :label="m.manager" :value="m.manager" />
      </el-select>
      <span class="mm-hint" v-if="selectedManager">
        当前仅查看「<b>{{ selectedManager }}</b>」名下节点（计划数按其申报值 {{ currentManagerPlan }}）
      </span>
      <span class="mm-hint" v-else>展示所有负责人导入工序的总和</span>
    </div>

    <!-- 导入排产计划入口（对齐原版：节点计划 Tab 最上方）。
         多负责人 v6.0：把「负责人视图」当前选中的负责人透传给导入，使其归属到该负责人名下；
         未选（汇总视图）且项目为多负责人时，后端会返回 400 提示先选负责人。 -->
    <ScheduleImport :pid="pid" :manager="selectedManager" :disabled="!auth.canEdit" @imported="onImported" />
    <el-alert
      v-if="selectedManager && managerOptions.length > 1"
      type="info"
      :closable="false"
      show-icon
      style="margin-top:10px;"
      :title="`当前导入将归属到负责人「${selectedManager}」名下（仅覆盖该负责人排产工序）`"
    />

    <!-- 顶部指标 KPI 卡 -->
    <div class="block-card" v-if="overview">
      <div class="block-header"><span class="icon"></span><span class="block-title">📌 项目节点概览</span></div>
      <el-row :gutter="16">
        <el-col :span="4" v-for="kpi in kpis" :key="kpi.key">
          <div class="kpi-card" :style="{ borderTopColor: kpi.color }">
            <div class="kpi-value">{{ overview.kpis[kpi.key] }}</div>
            <div class="kpi-label">{{ kpi.label }}</div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 有节点数据时才显示时间轴和工序明细 -->
    <template v-if="hasNodes">
      <!-- 时间轴卡（ECharts） -->
      <div class="block-card">
        <div class="block-header">
          <span class="icon"></span><span class="block-title">工序节点计划时间轴</span>
          <span class="block-subtitle">圆点按状态着色，红色竖线为今天</span>
        </div>
        <NodeTimelineChart v-if="overview" :rows="overview.timeline" :processes="overview.visible_processes" :height="timelineHeight" @visible-change="visibleProcessCount = $event" />
      </div>

      <!-- 工序卡片网格 -->
      <div class="block-card">
        <div class="block-header">
          <span class="icon"></span><span class="block-title">🏭 工序节点明细</span>
          <span class="block-subtitle" style="color:#3182ce;">点击卡片查看详情</span>
        </div>
        <ProcessCardGrid :pid="pid" :processes="overview?.processes || []" @open="onOpenProcess" />
      </div>
    </template>

    <!-- 无节点数据时显示空状态 -->
    <template v-else>
      <div class="block-card empty-state-card">
        <div class="empty-icon">📂</div>
        <div class="empty-title">暂无节点计划数据</div>
        <div class="empty-desc">
          请使用上方「导入排产计划」上传 Excel 后，即可查看工序时间轴与节点明细。<br/>
          导入新排产计划会覆盖该项目已有节点计划。
        </div>
      </div>
    </template>

    <!-- 工序详情 / 填报弹窗 -->
    <ProcessDetailDialog
      v-model="dialogVisible"
      :pid="pid"
      :process-name="activeProcess"
      :mode="dialogMode"
      :manager="selectedManager"
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import ScheduleImport from './ScheduleImport.vue'
import NodeTimelineChart from './NodeTimelineChart.vue'
import ProcessCardGrid from './ProcessCardGrid.vue'
import ProcessDetailDialog from './ProcessDetailDialog.vue'

const props = defineProps({ pid: { type: String, required: true } })
const store = useProjectStore()
const auth = useAuthStore()   // 普通账号禁用导入排产（仅管理员可导入）
const route = useRoute()
const overview = computed(() => store.overview)

// 多负责人（v6.0）：负责人视图筛选（'' = 汇总）。可选负责人分别查看 / 提报
const selectedManager = ref('')
const managerOptions = computed(() => overview.value?.managers || [])
const currentManagerPlan = computed(() => {
  const m = managerOptions.value.find((x) => x.manager === selectedManager.value)
  return m ? (m.monthly_plan || 0) : 0
})

// 时间轴当前可见工序数（由子组件图例隐藏时回传），用于实时重算时间轴高度
const visibleProcessCount = ref(0)
watch(
  () => overview.value?.visible_processes,
  (vp) => { visibleProcessCount.value = (vp || []).length },
  { immediate: true },
)

// 是否有节点计划数据
const hasNodes = computed(() => (overview.value?.kpis?.node_count || 0) > 0)

const kpis = [
  { key: 'total_sets', label: '总套数', color: '#1a365d' },
  { key: 'process_count', label: '工序数', color: '#3182ce' },
  { key: 'node_count', label: '节点总数', color: '#64748b' },
  { key: 'done_count', label: '达标节点', color: '#38a169' },
  { key: 'overdue_count', label: '逾期节点', color: '#e53e3e' },
]
const timelineHeight = computed(() => Math.max(480, 85 * Math.max(visibleProcessCount.value, 1)))

// 弹窗状态：mode = detail | input
const dialogVisible = ref(false)
const dialogMode = ref('detail')
const activeProcess = ref('')
const onOpenProcess = ({ process_name, mode }) => {
  activeProcess.value = process_name
  dialogMode.value = mode || 'detail'
  dialogVisible.value = true
}
// 统一刷新：按当前负责人筛选重载总览 + 头部信息卡 + 触发预警刷新
function reload() {
  store.loadOverview(props.pid, selectedManager.value || undefined)
  store.loadDetail(props.pid)
  store.lastNodeSavedAt = Date.now()
}
const onSaved = () => {
  dialogVisible.value = false
  reload()
}
const onImported = () => {
  reload()   // Excel 导入成功后刷新节点计划总览（含负责人筛选）
}

onMounted(() => {
  // 支持从多负责人管理弹窗「查看」携带 ?manager= 直达单人视图
  selectedManager.value = (route.query.manager && String(route.query.manager)) || ''
  reload()
})
watch(() => props.pid, () => {
  selectedManager.value = ''
  reload()
})
</script>

<style scoped>
.kpi-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-top: 4px solid #3182ce;
  border-radius: 10px;
  padding: 14px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.kpi-value { font-size: 26px; font-weight: 700; color: #1a365d; }
.kpi-label { font-size: 13px; color: #64748b; margin-top: 4px; }

/* 无节点计划数据空状态 */
.empty-state-card {
  text-align: center;
  padding: 48px 24px;
  color: #64748b;
}
.empty-icon { font-size: 48px; margin-bottom: 12px; }
.empty-title { font-size: 18px; font-weight: 600; color: #1a365d; margin-bottom: 8px; }
.empty-desc { font-size: 14px; line-height: 1.8; }

/* 多负责人视图筛选器 */
.mm-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.mm-label { font-size: 14px; font-weight: 600; color: #1a365d; white-space: nowrap; }
.mm-hint { font-size: 12px; color: #718096; }
.mm-hint b { color: #3182ce; }
</style>

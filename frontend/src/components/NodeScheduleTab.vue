<template>
  <div>
    <!-- 导入排产计划入口（对齐原版：节点计划 Tab 最上方） -->
    <ScheduleImport :pid="pid" :disabled="!auth.canEdit" @imported="onImported" />

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
        <NodeTimelineChart v-if="overview" :rows="overview.timeline" :processes="overview.visible_processes" :height="timelineHeight" />
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
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import ScheduleImport from './ScheduleImport.vue'
import NodeTimelineChart from './NodeTimelineChart.vue'
import ProcessCardGrid from './ProcessCardGrid.vue'
import ProcessDetailDialog from './ProcessDetailDialog.vue'

const props = defineProps({ pid: { type: String, required: true } })
const store = useProjectStore()
const auth = useAuthStore()   // 普通账号禁用导入排产（仅管理员可导入）
const overview = computed(() => store.overview)

// 是否有节点计划数据
const hasNodes = computed(() => (overview.value?.kpis?.node_count || 0) > 0)

const kpis = [
  { key: 'total_sets', label: '总套数', color: '#1a365d' },
  { key: 'process_count', label: '工序数', color: '#3182ce' },
  { key: 'node_count', label: '节点总数', color: '#64748b' },
  { key: 'done_count', label: '达标节点', color: '#38a169' },
  { key: 'overdue_count', label: '逾期节点', color: '#e53e3e' },
]
const timelineHeight = computed(() => Math.max(480, 85 * Math.max((overview.value?.visible_processes || []).length, 1)))

// 弹窗状态：mode = detail | input
const dialogVisible = ref(false)
const dialogMode = ref('detail')
const activeProcess = ref('')
const onOpenProcess = ({ process_name, mode }) => {
  activeProcess.value = process_name
  dialogMode.value = mode || 'detail'
  dialogVisible.value = true
}
const onSaved = () => {
  dialogVisible.value = false
  // 刷新节点计划总览（工序卡片/时间轴）
  store.loadOverview(props.pid)
  // 刷新顶部项目信息卡：风险等级 + 整体进度（附件安装）
  store.loadDetail(props.pid)
  // 触发节点预警 Tab 实时刷新
  store.lastNodeSavedAt = Date.now()
}
const onImported = () => {
  store.loadOverview(props.pid)   // Excel 导入成功后刷新节点计划总览
  store.lastNodeSavedAt = Date.now()   // 触发节点预警/异常模块自动刷新（排产变化 → 预警重算）
}

onMounted(() => store.loadOverview(props.pid))
watch(() => props.pid, () => store.loadOverview(props.pid))
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
</style>

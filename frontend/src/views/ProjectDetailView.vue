<template>
  <div class="page-wrap">
    <el-page-header @back="$router.push('/projects')" :content="`项目详情：${project?.project_name || ''}`" />
    <!-- 顶部项目信息卡 -->
    <ProjectHeaderCard v-if="project" :project="project" :overview="store.overview" />
    <!-- Tab 页 -->
    <el-tabs v-model="activeTab">
      <el-tab-pane label="📅 节点计划" name="nodes">
        <NodeScheduleTab :pid="id" />
      </el-tab-pane>
      <el-tab-pane label="⚠️ 节点预警" name="alerts">
        <div class="block-card">
          <div class="block-header"><span class="icon"></span><span class="block-title">节点预警</span></div>
          <AlertList :pid="id" />
        </div>
      </el-tab-pane>
      <!-- 异常记录（2026-11）：看**本项目全部异常**（不限工序），
           生效中 / 已超期 / 已关闭三段一目了然，可直接关闭。 -->
      <el-tab-pane label="🟠 异常记录" name="exceptions">
        <div class="block-card">
          <div class="block-header">
            <span class="icon"></span>
            <span class="block-title">异常记录</span>
            <span class="block-subtitle">本项目全部异常（生效中 / 已超期 / 已关闭）· 超期≠关闭</span>
          </div>
          <ExceptionRecordTable :pid="id" :refresh-key="excReloadKey" @changed="onExceptionChanged" />
        </div>
      </el-tab-pane>
      <el-tab-pane label="📅 里程碑倒排" name="milestone">
        <div class="block-card">
          <div class="block-header">
            <span class="icon"></span><span class="block-title">里程碑倒排</span>
            <span class="block-subtitle" style="color:#3182ce;">输入交付截止日自动倒排</span>
          </div>
          <MilestoneBackward :pid="id" />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useProjectStore } from '../store/project'
import ProjectHeaderCard from '../components/ProjectHeaderCard.vue'
import NodeScheduleTab from '../components/NodeScheduleTab.vue'
import AlertList from '../components/AlertList.vue'
import MilestoneBackward from '../components/MilestoneBackward.vue'
import ExceptionRecordTable from '../components/ExceptionRecordTable.vue'

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const activeTab = ref('nodes')
const project = computed(() => store.current)
// 排产按月隔离（v7.4）：详情页跟随全局共享月份（与「排产计划总览」页联动，缺省当前自然月），
// 使「项目基本信息卡的进度/风险」与「节点计划」的月份口径一致，不再把上月排产当作本月数据。
const currentMonth = computed(() => store.ensureMonth())

// 异常记录页签：关闭异常后 KPI / 工序卡片 / 预警列表都要失效缓存重算
const excReloadKey = ref(0)
function onExceptionChanged() {
  store.lastNodeSavedAt = Date.now()          // 预警列表刷新
  store.lastExceptionChangedAt = Date.now()   // 工序卡片「存在异常」标签刷新
  store.loadDetail(props.id, currentMonth.value)   // 头部风险等级（exception 态）立即更新
  store.loadDashboard()                            // KPI 五卡立即更新（后端缓存已失效）
}

onMounted(() => {
  store.loadDetail(props.id, currentMonth.value)
  store.loadOverview(props.id, undefined, currentMonth.value)   // 头部信息卡需要各工序进度
})
watch(currentMonth, () => {
  store.loadDetail(props.id, currentMonth.value)
  store.loadOverview(props.id, undefined, currentMonth.value)
})
</script>

<style scoped>
.page-wrap { padding: 24px; }
</style>

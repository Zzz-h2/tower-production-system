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

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const activeTab = ref('nodes')
const project = computed(() => store.current)
// 排产按月隔离（v7.4）：详情页跟随全局共享月份（与「排产计划总览」页联动，缺省当前自然月），
// 使「项目基本信息卡的进度/风险」与「节点计划」的月份口径一致，不再把上月排产当作本月数据。
const currentMonth = computed(() => store.ensureMonth())

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

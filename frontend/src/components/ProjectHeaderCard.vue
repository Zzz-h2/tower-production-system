<template>
  <div class="project-info-card">
    <div class="info-group">
      <div class="group-label">基本信息</div>
      <div class="group-items">
        <div class="item"><span>钢塔厂家</span><b>{{ project.factory_name || 'N/A' }}</b></div>
        <div class="item"><span>交付负责人</span><b>{{ project.delivery_person || 'N/A' }}</b></div>
        <div class="item"><span>计划开工 → 交付</span><b>{{ project.plan_start_date || '—' }} → {{ project.plan_end_date || '—' }}</b></div>
      </div>
    </div>
    <div class="info-group">
      <div class="group-label">整体进度（附件安装）</div>
      <div class="progress-row">
        <b>{{ overallProgress }}%</b>
        <div class="thin-progress" style="flex:1;">
          <div class="thin-progress-bar" :style="{ width: `${Math.min(overallProgress, 100)}%`, background: '#38a169' }"></div>
        </div>
      </div>
    </div>
    <div class="info-group center">
      <div class="group-label">风险等级</div>
      <span class="status-pill" :style="riskStyle">{{ riskLabel }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  project: { type: Object, required: true },
  overview: { type: Object, default: () => null },
})

// 整体进度 = 「附件安装」工序进度（overview.processes 中查找；兜底 project.progress_pct）
const attachmentProcess = computed(() =>
  props.overview?.processes?.find((p) => p.process_name === '附件安装')
)
const overallProgress = computed(() =>
  attachmentProcess.value?.progress_pct ?? props.project?.progress_pct ?? 0
)

// 风险等级：直接用后端实时计算值（node_plans + actuals 口径，与节点预警一致）
// —— 避免前端用 overview.processes 二次判定造成双口径不一致（如未来提前进行中误判预警）
const riskLevel = computed(() => props.project?.risk_level || 'normal')

const riskMap = {
  normal: ['#f0fff4', '#38a169', '正常'],
  warning: ['#fffff0', '#d69e2e', '预警'],
  delayed: ['#fff5f5', '#e53e3e', '延期'],
}
const riskStyle = computed(() => {
  const [bg, color] = riskMap[riskLevel.value] || riskMap.normal
  return { background: bg, color }
})
const riskLabel = computed(() => (riskMap[riskLevel.value] || riskMap.normal)[2])
</script>

<style scoped>
.project-info-card {
  background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
  border-radius: 16px;
  padding: 32px 36px;          /* 原 24px 28px → 增大 */
  color: #fff;
  margin: 20px 0 24px;
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  box-shadow: 0 4px 24px rgba(26, 54, 93, 0.25);
}
.info-group {
  flex: 1;
  min-width: 280px;           /* 原 240px → 加宽 */
  background: rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 18px 22px;         /* 原 12px 16px → 增大 */
}
/* 基本信息组占更多空间 */
.info-group:first-child { flex: 1.6; }
.info-group.center { text-align: center; }
.group-label { font-size: 13px; opacity: 0.75; font-weight: 600; letter-spacing: 1px; margin-bottom: 10px; }
.group-items { display: flex; flex-wrap: wrap; gap: 16px; }
.item span { display: block; font-size: 12px; opacity: 0.7; margin-bottom: 4px; }
.item b { font-size: 17px; }
.progress-row { display: flex; align-items: center; gap: 10px; }
.progress-row b { font-size: 22px; }
.status-pill { font-size: 15px; padding: 6px 16px; }
</style>

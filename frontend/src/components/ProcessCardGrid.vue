<template>
  <el-row :gutter="16" v-if="processes.length">
    <el-col :span="8" v-for="p in processes" :key="p.process_name" style="margin-bottom: 16px;">
      <div class="process-card-box">
        <div class="pc-header">
          <span class="pc-dot" :style="{ color: colorOf(p.status) }">{{ emojiOf(p.status) }}</span>
          <span class="pc-title">{{ p.process_name }}</span>
          <span class="pc-pill" :style="pillStyle(p.status)">{{ p.label }}</span>
          <span v-for="t in (p.tags || [])" :key="t" class="pc-tag" :style="tagStyle(t)">{{ t }}</span>
        </div>
        <div class="pc-count">{{ p.total_actual }}/{{ p.total_plan }} 套</div>
        <div class="pc-progress">
          <div class="pc-progress-track">
            <div class="pc-progress-bar" :style="{ width: p.progress_pct + '%', background: colorOf(p.status) }"></div>
          </div>
          <span class="pc-percent">{{ p.progress_pct }}%</span>
        </div>
        <div class="pc-footer">
          <el-button size="small" type="primary" plain @click="$emit('open', { process_name: p.process_name, mode: 'detail' })">
            查看详情
          </el-button>
        </div>
      </div>
    </el-col>
  </el-row>
  <div v-else class="pc-empty">暂无工序节点明细数据</div>
</template>

<script setup>
defineProps({
  pid: { type: String, required: true },
  processes: { type: Array, default: () => [] },
})
defineEmits(['open'])

const statusColors = {
  done: '#38a169', pending: '#718096', in_progress: '#3182ce', warning: '#3182ce',
  overdue: '#e53e3e', done_early: '#0ea5e9',
}
const statusBgs = {
  done: '#f0fff4', pending: '#f7fafc', in_progress: '#ebf8ff', warning: '#ebf8ff',
  overdue: '#fff5f5', done_early: '#e0f2fe',
}
const emojis = { done: '🟢', pending: '⚪', in_progress: '🔵', warning: '🟡', overdue: '🔴', done_early: '✨' }
const colorOf = (s) => statusColors[s] || '#718096'
const pillStyle = (s) => ({ background: statusBgs[s] || '#f7fafc', color: statusColors[s] || '#718096' })
const emojiOf = (s) => emojis[s] || '⚪'

// 附加标签（时间维度偏差）浅底小字
const tagStyle = (t) => {
  const m = {
    '已逾期': { c: '#e53e3e', b: '#fff5f5' },
    '已提前': { c: '#0ea5e9', b: '#e0f2fe' },
    '部分完成': { c: '#f6ad55', b: '#fffaf0' },
  }
  const s = m[t] || { c: '#718096', b: '#f7fafc' }
  return { background: s.b, color: s.c }
}
</script>

<style scoped>
/* 附加标签：浅底小字圆角，紧跟主状态胶囊 */
.pc-tag {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  margin-left: 4px;
  line-height: 18px;
  white-space: nowrap;
  flex-shrink: 0;
}
/* 无工序节点明细数据空状态 */
.pc-empty {
  text-align: center;
  padding: 32px;
  color: #718096;
  font-size: 14px;
}
</style>

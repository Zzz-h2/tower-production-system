<template>
  <div>
    <div v-if="items.length === 0" class="empty-hint">暂无预警节点</div>
    <el-table v-else :data="items" style="width: 100%">
      <el-table-column label="操作" width="90" fixed="left">
        <template #default="{ row }">
          <el-button size="small" type="danger" plain @click="openManage(row)">管理</el-button>
        </template>
      </el-table-column>
      <el-table-column label="节点信息" min-width="220">
        <template #default="{ row }">
          <div style="font-weight:600;">{{ row.process_name }} · {{ row.plan_date }}</div>
          <div class="sub">计划 {{ row.plan_qty }} 套 / 实际 {{ row.actual_qty }} 套</div>
          <span v-if="row.has_exception" class="exc-badge">已提报异常</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <span class="status-pill" :style="pillStyle(row.status)">{{ row.label }}</span>
        </template>
      </el-table-column>
      <el-table-column label="逾期天数" width="100">
        <template #default="{ row }">
          {{ row.deviation_days ?? '-' }}
        </template>
      </el-table-column>
    </el-table>

    <!-- 异常管理弹窗 -->
    <el-dialog v-model="manageVisible" title="异常处理" width="600px">
      <div v-if="selectedRow">
        <p><b>节点：</b>{{ selectedRow.process_name }} · {{ selectedRow.plan_date }}</p>
        <p><b>计划/实际：</b>{{ selectedRow.plan_qty }} / {{ selectedRow.actual_qty }} 套</p>

        <div v-if="selectedRow.exceptions?.length" class="exc-list">
          <div v-for="e in selectedRow.exceptions" :key="e.id" class="exc-card">
            <p><b>责任分类：</b>{{ e.responsibility_category }}</p>
            <p><b>异常原因：</b>{{ e.reason_detail }}</p>
            <p><b>处理人：</b>{{ e.handler || '-' }}</p>
            <p><b>计划关闭：</b>{{ e.planned_close_date || '-' }}</p>
            <p><b>处理措施：</b>{{ e.measures || '-' }}</p>
            <p><b>状态：</b><span class="exc-status" :class="e.status">{{ statusText[e.status] }}</span></p>
            <el-button v-if="e.status !== 'closed'" size="small" type="success" @click="closeExc(e.id)">关闭异常</el-button>
          </div>
        </div>
        <div v-else class="no-exc">该节点尚未提报异常，请进入节点详情弹窗的「异常提报」Tab 进行提报。</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchAlerts } from '../api/node'
import { updateException } from '../api/exception'
import { useProjectStore } from '../store/project'

const props = defineProps({ pid: { type: String, required: true } })
const store = useProjectStore()
const items = ref([])

const statusColors = {
  done: '#38a169', pending: '#718096', in_progress: '#3182ce', warning: '#3182ce', overdue: '#e53e3e',
}
const statusBgs = {
  done: '#f0fff4', pending: '#f7fafc', in_progress: '#ebf8ff', warning: '#ebf8ff', overdue: '#fff5f5',
}
const colorOf = (s) => statusColors[s] || '#718096'
const pillStyle = (s) => ({ background: statusBgs[s] || '#f7fafc', color: statusColors[s] || '#718096' })

const statusText = { pending: '待处理', processing: '处理中', closed: '已关闭' }

// 管理弹窗
const manageVisible = ref(false)
const selectedRow = ref(null)
function openManage(row) {
  selectedRow.value = row
  manageVisible.value = true
}
async function closeExc(id) {
  await updateException(id, { status: 'closed' })
  ElMessage.success('异常已关闭')
  manageVisible.value = false
  load()
}

async function load() {
  const res = await fetchAlerts(props.pid)
  items.value = res.items || []
}
onMounted(load)
watch(() => props.pid, load)
// 监听节点填报/异常提报保存事件，实时刷新预警列表
watch(() => store.lastNodeSavedAt, (ts) => {
  if (ts && props.pid) load()
})
</script>

<style scoped>
.empty-hint { color: #64748b; font-size: 13px; padding: 12px 0; }
.sub { font-size: 12px; color: #64748b; }
.exc-badge {
  display: inline-block; margin-top: 4px; padding: 1px 8px; border-radius: 10px;
  font-size: 11px; background: #fffaf0; color: #f6ad55;
}
.exc-list { margin-top: 12px; }
.exc-card {
  border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px;
  font-size: 13px; color: #4a5568;
}
.exc-card p { margin: 4px 0; }
.exc-status { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.exc-status.pending { background: #fffaf0; color: #f6ad55; }
.exc-status.processing { background: #e0f2fe; color: #0ea5e9; }
.exc-status.closed { background: #f0fff4; color: #38a169; }
.no-exc { color: #718096; font-size: 13px; padding: 16px 0; }
</style>

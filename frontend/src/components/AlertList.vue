<template>
  <div class="alert-list-container">
    <!-- 当前预警模块（预警节点：逾期/今日未完成/进行中，与风险等级同源） -->
    <div class="alert-section">
      <div class="section-header">
        <span class="section-icon">⚠️</span>
        <span class="section-title">当前预警</span>
        <el-tag type="warning" size="small">{{ currentItems.length }}</el-tag>
      </div>
      <el-table :data="currentItems" style="width: 100%" v-if="currentItems.length">
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="onManage(row)">管理</el-button>
          </template>
        </el-table-column>
        <el-table-column label="节点信息" min-width="190">
          <template #default="{ row }">
            <div class="node-title">{{ row.process_name }} · {{ row.plan_date }}</div>
            <div class="sub">计划 {{ row.plan_qty }} 套 / 实际 {{ row.actual_qty }} 套</div>
            <span v-if="row.has_exception" class="exc-badge">已提报异常</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <span class="status-pill" :style="pillStyle(row.status)">{{ row.label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="偏差天数" width="100">
          <template #default="{ row }">
            {{ row.deviation_days ?? '-' }}
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无当前预警" />
    </div>

    <!-- 历史异常记录模块（已关闭的异常提报） -->
    <div class="alert-section history-section">
      <div class="section-header">
        <span class="section-icon">📁</span>
        <span class="section-title">历史异常记录</span>
        <el-tag type="success" size="small">{{ historyItems.length }}</el-tag>
      </div>
      <el-table :data="historyItems" style="width: 100%" v-if="historyItems.length">
        <el-table-column label="节点信息" min-width="180">
          <template #default="{ row }">
            <div class="node-title">{{ row.process_name }} · {{ row.plan_date }}</div>
          </template>
        </el-table-column>
        <el-table-column label="异常原因" prop="reason_detail" show-overflow-tooltip min-width="200" />
        <el-table-column label="责任分类" prop="responsibility_category" width="120" />
        <el-table-column label="处理人" prop="handler" width="120" />
        <el-table-column label="处理措施" prop="measures" show-overflow-tooltip min-width="180" />
        <el-table-column label="计划关闭" prop="planned_close_date" width="120" />
        <el-table-column label="实际关闭" width="170">
          <template #default="{ row }">
            {{ formatClosedAt(row.closed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag type="success" size="small">已关闭</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无历史异常记录" />
    </div>

    <!-- 节点异常管理弹窗：查看该节点已提报异常，可编辑/关闭；无异常提示提报 -->
    <el-dialog v-model="manageVisible" :title="`异常管理：${manageNode?.process_name || ''} · ${manageNode?.plan_date || ''}`" width="620px">
      <div v-if="nodeExceptions.length" class="exc-list">
        <div v-for="e in nodeExceptions" :key="e.id" class="exc-card">
          <p><b>责任分类：</b>{{ e.responsibility_category }}</p>
          <p><b>异常原因：</b>{{ e.reason_detail }}</p>
          <p><b>处理人：</b>{{ e.handler || '-' }}　<b>计划关闭：</b>{{ e.planned_close_date || '-' }}</p>
          <p><b>处理措施：</b>{{ e.measures || '-' }}</p>
          <p>
            <b>状态：</b><span class="exc-status" :class="e.status">{{ statusText[e.status] }}</span>
            <el-button v-if="e.status !== 'closed'" size="small" type="primary" plain style="margin-left:10px;" @click="openEdit(e)">编辑</el-button>
            <el-button v-if="e.status !== 'closed'" size="small" type="success" plain @click="onCloseException(e.id)">关闭</el-button>
          </p>
        </div>
      </div>
      <div v-else class="no-exc">
        该节点尚未提报异常。请在节点详情弹窗的「⚠️ 异常提报」Tab 中提报，提报后此处可查看与处理。
      </div>
    </el-dialog>

    <!-- 编辑异常信息弹窗 -->
    <el-dialog v-model="editVisible" title="编辑异常信息" width="600px" destroy-on-close>
      <el-form :model="editForm" label-width="100px" size="default" v-if="editingException">
        <el-form-item label="责任分类">
          <el-select v-model="editForm.responsibility_category" placeholder="请选择" style="width: 100%">
            <el-option label="供应商" value="供应商" />
            <el-option label="内部生产" value="内部生产" />
            <el-option label="物流运输" value="物流运输" />
            <el-option label="天气/不可抗力" value="天气/不可抗力" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="异常原因">
          <el-input v-model="editForm.reason_detail" type="textarea" :rows="3" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="处理人">
          <el-input v-model="editForm.handler" placeholder="请输入处理人" />
        </el-form-item>
        <el-form-item label="计划关闭日期">
          <el-date-picker
            v-model="editForm.planned_close_date"
            type="date"
            placeholder="选择日期"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="处理措施">
          <el-input v-model="editForm.measures" type="textarea" :rows="3" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" placeholder="请选择" style="width: 100%">
            <el-option label="待处理" value="pending" />
            <el-option label="处理中" value="processing" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchAlerts } from '../api/node'
import { listExceptionsByNode, listClosedExceptions, updateException } from '../api/exception'
import { useProjectStore } from '../store/project'

const props = defineProps({ pid: { type: String, required: true } })
const store = useProjectStore()

const currentItems = ref([])      // 当前预警（预警节点：overdue/warning/in_progress）
const historyItems = ref([])      // 历史异常记录（closed）

const statusText = { pending: '待处理', processing: '处理中', closed: '已关闭' }

const statusColors = {
  done: '#38a169', pending: '#718096', in_progress: '#3182ce', warning: '#3182ce', overdue: '#e53e3e',
}
const statusBgs = {
  done: '#f0fff4', pending: '#f7fafc', in_progress: '#ebf8ff', warning: '#ebf8ff', overdue: '#fff5f5',
}
const pillStyle = (s) => ({ background: statusBgs[s] || '#f7fafc', color: statusColors[s] || '#718096' })

// 节点异常管理弹窗
const manageVisible = ref(false)
const manageNode = ref(null)
const nodeExceptions = ref([])
async function onManage(row) {
  manageNode.value = row
  const res = await listExceptionsByNode(row.id)
  nodeExceptions.value = res.items || []
  manageVisible.value = true
}

// 关闭异常（管理弹窗内）
async function onCloseException(id) {
  await ElMessageBox.confirm('确认关闭该异常？', '提示', { type: 'warning' })
  await updateException(id, { status: 'closed' })
  ElMessage.success('异常已关闭')
  manageVisible.value = false
  await loadAll()
}

// 编辑异常信息
const editVisible = ref(false)
const editingException = ref(null)
const editForm = reactive({
  id: null,
  responsibility_category: '',
  reason_detail: '',
  handler: '',
  planned_close_date: '',
  measures: '',
  status: '',
})
function openEdit(e) {
  editingException.value = e
  editForm.id = e.id
  editForm.responsibility_category = e.responsibility_category || ''
  editForm.reason_detail = e.reason_detail || ''
  editForm.handler = e.handler || ''
  editForm.planned_close_date = e.planned_close_date || ''
  editForm.measures = e.measures || ''
  editForm.status = e.status || 'pending'
  editVisible.value = true
}
async function saveEdit() {
  if (!editForm.responsibility_category || !editForm.reason_detail) {
    ElMessage.warning('请填写责任分类和异常原因')
    return
  }
  await updateException(editForm.id, {
    responsibility_category: editForm.responsibility_category,
    reason_detail: editForm.reason_detail,
    handler: editForm.handler,
    planned_close_date: editForm.planned_close_date || null,
    measures: editForm.measures,
    status: editForm.status,
  })
  ElMessage.success('异常信息已更新')
  editVisible.value = false
  manageVisible.value = false
  await loadAll()
}

async function loadCurrent() {
  const res = await fetchAlerts(props.pid)
  currentItems.value = res.items || []
}

async function loadHistory() {
  const res = await listClosedExceptions(props.pid)
  historyItems.value = res.items || []
}

async function loadAll() {
  await Promise.all([loadCurrent(), loadHistory()])
}

function formatClosedAt(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  return isNaN(d) ? ts : d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

onMounted(loadAll)
watch(() => props.pid, loadAll)
// 节点填报/异常提报/排产导入后自动刷新
watch(() => store.lastNodeSavedAt, (ts) => {
  if (ts && props.pid) loadAll()
})
</script>

<style scoped>
.alert-list-container { padding: 16px; }
.alert-section {
  background: #ffffff;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
  border: 1px solid #e2e8f0;
}
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  font-size: 16px;
  font-weight: 600;
  color: #1a365d;
}
.section-icon { font-size: 18px; }
.node-title { font-weight: 500; color: #1a365d; }
.sub { font-size: 12px; color: #64748b; }
.exc-badge {
  display: inline-block; margin-top: 4px; padding: 1px 8px; border-radius: 10px;
  font-size: 11px; background: #fffaf0; color: #f6ad55;
}
.history-section { background: #f8fafc; }
.exc-list { margin-top: 4px; }
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

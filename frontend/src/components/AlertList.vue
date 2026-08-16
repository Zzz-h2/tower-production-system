<template>
  <div class="alert-list-container">
    <!-- 当前预警模块 -->
    <div class="alert-section">
      <div class="section-header">
        <span class="section-icon">⚠️</span>
        <span class="section-title">当前预警</span>
        <el-tag type="warning" size="small">{{ currentItems.length }}</el-tag>
      </div>
      <el-table :data="currentItems" style="width: 100%" v-if="currentItems.length">
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openManage(row)">管理</el-button>
            <el-button size="small" type="success" plain @click="onCloseException(row)">关闭</el-button>
          </template>
        </el-table-column>
        <el-table-column label="节点信息" min-width="180">
          <template #default="{ row }">
            <div class="node-title">{{ row.process_name }} · {{ row.plan_date }}</div>
          </template>
        </el-table-column>
        <el-table-column label="异常原因" prop="reason_detail" show-overflow-tooltip min-width="200" />
        <el-table-column label="责任分类" prop="responsibility_category" width="120" />
        <el-table-column label="处理人" prop="handler" width="120" />
        <el-table-column label="计划关闭日期" prop="planned_close_date" width="140" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'pending' ? 'warning' : 'primary'" size="small">
              {{ row.status === 'pending' ? '待处理' : '处理中' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无当前预警" />
    </div>

    <!-- 历史异常记录模块 -->
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
        <el-table-column label="处理措施" prop="measures" show-overflow-tooltip min-width="200" />
        <el-table-column label="计划关闭日期" prop="planned_close_date" width="140" />
        <el-table-column label="实际关闭日期" width="180">
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

    <!-- 编辑异常信息弹窗 -->
    <el-dialog v-model="manageVisible" title="编辑异常信息" width="600px" destroy-on-close>
      <el-form :model="editForm" label-width="100px" size="default" v-if="editingException">
        <el-form-item label="节点信息">
          <span>{{ editingException.process_name }} · {{ editingException.plan_date }}</span>
        </el-form-item>
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
        <el-button @click="manageVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listExceptionsByProject, listClosedExceptions, updateException } from '../api/exception'
import { useProjectStore } from '../store/project'

const props = defineProps({ pid: { type: String, required: true } })
const store = useProjectStore()

const currentItems = ref([])      // 当前预警（异常记录，非 closed）
const historyItems = ref([])      // 历史异常记录（closed）

const statusText = { pending: '待处理', processing: '处理中', closed: '已关闭' }

// 编辑弹窗：当前预警行本身就是异常记录，直接编辑该行字段
const manageVisible = ref(false)
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

function openManage(row) {
  editingException.value = row
  editForm.id = row.id
  editForm.responsibility_category = row.responsibility_category || ''
  editForm.reason_detail = row.reason_detail || ''
  editForm.handler = row.handler || ''
  editForm.planned_close_date = row.planned_close_date || ''
  editForm.measures = row.measures || ''
  editForm.status = row.status || 'pending'
  manageVisible.value = true
}

// 保存编辑：更新字段/状态后联动刷新当前预警 + 历史异常
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
  manageVisible.value = false
  await loadAll()
}

// 行内关闭异常：确认后置为 closed，联动刷新两模块
async function onCloseException(row) {
  await ElMessageBox.confirm('确认关闭该异常？', '提示', { type: 'warning' })
  const excId = row.id
  await updateException(excId, { status: 'closed' })
  ElMessage.success('异常已关闭')
  await loadAll()
}

async function loadCurrent() {
  const res = await listExceptionsByProject(props.pid)
  currentItems.value = (res.items || []).filter((e) => e.status !== 'closed')
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
// 异常提报后自动刷新（复用节点保存事件总线）
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
.history-section { background: #f8fafc; }
</style>

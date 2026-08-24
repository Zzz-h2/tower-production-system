<template>
  <div class="milestone-wrap">
    <div class="milestone-toolbar">
      <el-date-picker
        v-model="deadline"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="选择交付截止日期"
        style="width: 220px"
      />
      <el-button type="primary" :icon="Refresh" :loading="loading" @click="generate">
        生成倒排计划
      </el-button>
      <el-button :icon="Setting" @click="openMilestoneSetting">设置</el-button>
      <span class="hint">输入交付截止日，系统自动倒排各工序最晚开始/完成时间</span>
    </div>

    <el-empty v-if="!rows.length && !loading" description="请选择交付截止日期后生成倒排计划" />

    <template v-else>
      <el-table :data="rows" border stripe style="width: 100%; margin-top: 16px">
        <el-table-column label="工序" prop="process_name" min-width="120" />
        <el-table-column label="工期(天)" prop="days" width="100" />
        <el-table-column label="最晚开始" min-width="120">
          <template #default="{ row }">{{ fmt(row.backward_start) }}</template>
        </el-table-column>
        <el-table-column label="最晚完成" min-width="120">
          <template #default="{ row }">{{ fmt(row.backward_end) }}</template>
        </el-table-column>
        <el-table-column label="当前状态" min-width="110">
          <template #default="{ row }">
            <span class="status-tag" :style="statusStyle(row.current_status)">
              {{ statusText(row.current_status) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="偏差分析" min-width="220">
          <template #default="{ row }">
            <span :style="{ color: devColor(row.dev_level), fontWeight: 500 }">
              {{ row.deviation }}
            </span>
          </template>
        </el-table-column>
      </el-table>

      <div class="delivery-bar" :class="lagClass">
        <b>预计交付：</b>{{ result.estimated_delivery }}
        <span class="lag-text">
          {{ result.lag_days > 0 ? `⚠️ 较截止日延迟 ${result.lag_days} 天` : '✅ 可在截止日前完成' }}
        </span>
        <span v-if="!result.has_plan" class="no-plan">（暂无实际排产数据，状态按未开始估算）</span>
      </div>
    </template>

    <!-- 工序工期设置抽屉 -->
    <el-drawer
      v-model="settingVisible"
      title="里程碑倒排工序设置"
      direction="rtl"
      size="400px"
      destroy-on-close
    >
      <div class="setting-tip">按项目自定义各工序工期（天），保存后自动重新倒排。仅本项目生效。</div>
      <el-table :data="settingRows" style="width: 100%" :row-style="{ height: '48px' }">
        <el-table-column label="工序" min-width="120">
          <template #default="{ row }">
            <span class="proc-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="工期(天)" width="150">
          <template #default="{ row }">
            <el-input-number
              v-model="settingForm[row.name]"
              :min="1"
              :max="365"
              :step="1"
              step-strictly
              controls-position="right"
              style="width: 120px"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="settingForm[row.name] !== DEFAULT_DURATIONS[row.name]"
              type="primary"
              link
              size="small"
              @click="resetOne(row.name)"
            >
              恢复默认
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-divider />
      <div class="setting-footer">
        <el-button @click="resetAll">恢复全部默认</el-button>
        <span style="flex:1"></span>
        <el-button @click="settingVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSetting">保存</el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Refresh, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { fetchMilestoneBackward } from '../api/milestone'

const props = defineProps({ pid: { type: String, required: true } })
const deadline = ref('')
const loading = ref(false)
const rows = ref([])
const result = ref({ estimated_delivery: '', lag_days: 0, has_plan: true })

// 默认工序工期（顺序与后端 MILESTONE_PROCESSES 一致；"黑塔"为后端标准名）
const DEFAULT_DURATIONS = {
  '钢板到货': 1, '法兰到货': 1, '下料': 2, '卷制': 3, '组对': 2,
  '环缝': 2, '门框焊接': 1,
  '黑塔': 2, '防腐': 2, '附件安装': 3, '具备验收': 1,
}
const PROCESS_ORDER = [
  '钢板到货', '法兰到货', '下料', '卷制', '组对',
  '环缝', '门框焊接', '黑塔', '防腐', '附件安装', '具备验收',
]

// localStorage 按项目隔离
const getStorageKey = (projectId) => `milestone-durations-${projectId}`
const loadDurations = () => {
  try {
    const saved = localStorage.getItem(getStorageKey(props.pid))
    return saved ? { ...DEFAULT_DURATIONS, ...JSON.parse(saved) } : { ...DEFAULT_DURATIONS }
  } catch (e) {
    return { ...DEFAULT_DURATIONS }
  }
}

// 设置抽屉
const settingVisible = ref(false)
const settingForm = ref({})
const settingRows = computed(() => PROCESS_ORDER.map((name) => ({ name })))

function openMilestoneSetting() {
  settingForm.value = loadDurations()
  settingVisible.value = true
}
function resetOne(processName) {
  settingForm.value[processName] = DEFAULT_DURATIONS[processName]
}
function resetAll() {
  settingForm.value = { ...DEFAULT_DURATIONS }
}
function saveSetting() {
  for (const name of PROCESS_ORDER) {
    const v = settingForm.value[name]
    if (!Number.isInteger(v) || v < 1 || v > 365) {
      ElMessage.warning(`${name} 工期必须是 1~365 的整数`)
      return
    }
  }
  localStorage.setItem(getStorageKey(props.pid), JSON.stringify(settingForm.value))
  settingVisible.value = false
  ElMessage.success('设置已保存')
  // 若已选交付截止日，自动重新生成倒排计划
  if (deadline.value) generate()
}

const STATUS_TEXT = {
  done: '已完成', done_early: '提前完成', overdue: '已逾期',
  in_progress: '进行中', pending: '未开始',
}
const statusText = (s) => STATUS_TEXT[s] || '未开始'
const statusStyle = (s) => {
  const m = {
    done: { c: '#38a169', b: '#f0fff4' }, done_early: { c: '#0ea5e9', b: '#e0f2fe' },
    overdue: { c: '#e53e3e', b: '#fff5f5' }, in_progress: { c: '#3182ce', b: '#ebf4ff' },
    pending: { c: '#718096', b: '#f7fafc' },
  }
  const x = m[s] || m.pending
  return { color: x.c, background: x.b, padding: '2px 10px', borderRadius: '10px', fontSize: '12px' }
}
const devColor = (lv) => ({ normal: '#38a169', warning: '#f6ad55', danger: '#e53e3e' }[lv] || '#38a169')
const fmt = (d) => (d ? String(d).slice(0, 10) : '-')
const lagClass = computed(() => (result.value.lag_days > 0 ? 'late' : 'ok'))

async function generate() {
  if (!deadline.value) { ElMessage.warning('请先选择交付截止日期'); return }
  loading.value = true
  try {
    const res = await fetchMilestoneBackward(props.pid, deadline.value, loadDurations())
    rows.value = res.rows || []
    result.value = {
      estimated_delivery: res.estimated_delivery,
      lag_days: res.lag_days,
      has_plan: res.has_plan,
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.milestone-wrap { padding: 8px 4px; }
.milestone-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hint { color: #718096; font-size: 13px; }
.delivery-bar {
  margin-top: 16px; padding: 14px 18px; border-radius: 12px; font-size: 14px;
  border: 1px solid #e2e8f0; background: #f8fafc;
}
.delivery-bar.late { background: #fff5f5; border-color: #feb2b2; }
.delivery-bar.ok { background: #f0fff4; border-color: #9ae6b4; }
.lag-text { margin-left: 12px; font-weight: 600; }
.no-plan { margin-left: 10px; color: #a0aec0; font-size: 12px; }
.status-tag { display: inline-block; }
.setting-tip { color: #718096; font-size: 13px; margin-bottom: 12px; }
.proc-name { font-weight: 500; color: #1a365d; }
.setting-footer { display: flex; align-items: center; gap: 10px; }
</style>

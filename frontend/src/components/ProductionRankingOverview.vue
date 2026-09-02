<template>
  <div class="ranking-wrap">
    <!-- ① 工具条 -->
    <div class="block-card">
      <div class="toolbar">
        <el-date-picker
          v-model="store.filters.month"
          type="month"
          value-format="YYYY-MM"
          placeholder="选择调度令月份"
          style="width: 160px"
          @change="load"
        />
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <span class="hint">统计口径：多负责人按单人分别排名；累计计划套数=各负责人申报的本月计划数之和；累计完成套数=附件安装实际完成；按调度令月份归类</span>
      </div>
    </div>

    <!-- ② 统计卡片 -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-value">{{ stats.persons }}</div>
        <div class="kpi-label">负责人数量</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{{ fmtQty(stats.totalPlan) }}</div>
        <div class="kpi-label">累计计划套数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:#38a169;">{{ fmtQty(stats.totalActual) }}</div>
        <div class="kpi-label">累计完成套数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color:#3182ce;">{{ stats.avgRate }}</div>
        <div class="kpi-label">平均完成率</div>
      </div>
    </div>

    <!-- ③ 排名表格 -->
    <div class="block-card">
      <div class="block-header">
        <span class="icon"></span><span class="block-title">出品排名</span>
        <el-tag type="info" size="small">{{ rows.length }}</el-tag>
      </div>
      <el-table :data="rows" border stripe style="width: 100%" :row-style="{ height: '48px' }">
        <el-table-column label="排名" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.rank === 1" type="warning" size="small">🏆 冠军</el-tag>
            <span v-else>{{ row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column label="负责人" prop="manager" min-width="140">
          <template #default="{ row }">
            <span style="font-weight:600; color:#1a365d;">{{ row.manager }}</span>
          </template>
        </el-table-column>
        <el-table-column label="项目数" prop="project_count" width="90" align="center" />
        <el-table-column label="累计计划套数" min-width="140" align="right">
          <template #default="{ row }">{{ fmtQty(row.total_plan) }}</template>
        </el-table-column>
        <el-table-column label="累计完成套数" min-width="140" align="right">
          <template #default="{ row }">{{ fmtQty(row.total_actual) }}</template>
        </el-table-column>
        <el-table-column label="完成率" min-width="200">
          <template #default="{ row }">
            <template v-if="row.completion_rate === null || row.completion_rate === undefined">
              <span style="color:#a0aec0;">—</span>
            </template>
            <el-progress
              v-else
              :percentage="Math.min(100, row.completion_rate)"
              :color="rateColor(row.completion_rate)"
              :format="() => row.completion_rate.toFixed(1) + '%'"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!rows.length && !loading" description="当月暂无出品数据" />
    </div>

    <!-- ④ 详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      :title="`${detailPerson} · 逾期/提前项目清单（${store.filters.month}）`"
      width="88vw"
      :style="{ maxWidth: '1280px' }"
    >
      <el-table
        :data="detailRows"
        border
        stripe
        style="width: 100%"
        :row-style="{ height: '52px' }"
        :max-height="'60vh'"
        :header-cell-style="{ whiteSpace: 'nowrap', background: '#f7fafc', color: '#1a365d' }"
        :cell-style="{ whiteSpace: 'nowrap' }"
      >
        <el-table-column label="项目名称" prop="project_name" min-width="260" show-overflow-tooltip />
        <el-table-column label="机号" prop="machine_no" width="110">
          <template #default="{ row }">{{ row.machine_no || '-' }}</template>
        </el-table-column>
        <el-table-column label="异常类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.exception_type === '逾期' ? 'danger' : 'primary'" size="small">
              {{ row.exception_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工序" prop="process_name" min-width="120" />
        <el-table-column label="计划日期" prop="plan_date" width="130" />
        <el-table-column label="计划/实际" min-width="150">
          <template #default="{ row }">
            <span style="white-space: nowrap; font-variant-numeric: tabular-nums;">
              {{ row.plan_qty }} / {{ row.actual_qty }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="偏差天数" prop="deviation_days" width="100" align="center" />
      </el-table>
      <el-empty v-if="!detailRows.length" description="该负责人当月无逾期或提前项目" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useProjectStore } from '../store/project'
import { fetchProductionRanking, fetchProductionRankingDetail } from '../api/ranking'

const store = useProjectStore()   // 共享调度令月份（三页联动）
const loading = ref(false)
const rows = ref([])

const stats = computed(() => {
  const totalPlan = rows.value.reduce((s, r) => s + (r.total_plan || 0), 0)
  const totalActual = rows.value.reduce((s, r) => s + (r.total_actual || 0), 0)
  const valid = rows.value.filter((r) => r.completion_rate !== null && r.completion_rate !== undefined)
  const avg = valid.length
    ? (valid.reduce((s, r) => s + r.completion_rate, 0) / valid.length).toFixed(1)
    : '—'
  return { persons: rows.value.length, totalPlan, totalActual, avgRate: `${avg}%` }
})

const fmtQty = (v) => (v === null || v === undefined ? '0' : Number(v).toLocaleString())
const rateColor = (rate) => (rate >= 100 ? '#38a169' : rate < 60 ? '#e53e3e' : '#ed8936')

// 详情
const detailVisible = ref(false)
const detailPerson = ref('')
const detailRows = ref([])
async function openDetail(row) {
  detailPerson.value = row.manager
  try {
    const res = await fetchProductionRankingDetail(store.filters.month, row.manager)
    detailRows.value = res || []
  } catch (e) {
    ElMessage.error('加载明细失败')
    detailRows.value = []
  }
  detailVisible.value = true
}

async function load() {
  loading.value = true
  store.ensureMonth()   // 共享月份非空（默认当前自然月）
  try {
    const res = await fetchProductionRanking(store.filters.month)
    rows.value = res || []
  } catch (e) {
    ElMessage.error('加载排名数据失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ranking-wrap { }
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hint { color: #718096; font-size: 13px; }
.kpi-row { display: flex; gap: 16px; margin: 16px 0; }
.kpi-card {
  flex: 1; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px;
}
.kpi-value { font-size: 28px; font-weight: 700; color: #1a365d; }
.kpi-label { font-size: 13px; color: #718096; margin-top: 4px; }
.block-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; }
.block-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.block-title { font-size: 15px; font-weight: 600; color: #1a365d; }
/* 详情弹窗表格：表头与单元格强制单行，避免短文本被竖排 */
.detail-dialog-table th.el-table__cell,
.detail-dialog-table td.el-table__cell {
  white-space: nowrap;
}
</style>

<template>
  <div class="schedule-overview">
    <!-- ① 统计卡片区 -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-value">{{ totalCount }}</div>
        <div class="kpi-label">项目总数</div>
      </div>
      <div class="kpi-card kpi-blue">
        <div class="kpi-value" style="color:#38a169;">{{ uploadedCount }}</div>
        <div class="kpi-label">已上传排产</div>
      </div>
      <div class="kpi-card kpi-warning">
        <div class="kpi-value" style="color:#ed8936;">{{ notUploadedCount }}</div>
        <div class="kpi-label">未上传排产</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{{ monthDueCount }}</div>
        <div class="kpi-label">本月应交项目</div>
      </div>
    </div>

    <!-- ② 筛选/搜索栏 -->
    <div class="block-card">
      <div class="search-bar">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索项目名称 / 机号"
          clearable
          style="width: 240px"
          @input="applyFilter"
          @clear="applyFilter"
        />
        <el-select
          v-model="filters.person"
          placeholder="交付负责人"
          clearable
          filterable
          style="width: 180px"
          @change="applyFilter"
          @clear="applyFilter"
        >
          <el-option v-for="p in store.allPersons" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select
          v-model="filters.uploadStatus"
          placeholder="上传状态"
          clearable
          style="width: 140px"
          @change="applyFilter"
          @clear="applyFilter"
        >
          <el-option label="全部" value="all" />
          <el-option label="已上传" value="uploaded" />
          <el-option label="未上传" value="not_uploaded" />
        </el-select>
        <el-date-picker
          v-model="store.filters.month"
          type="month"
          value-format="YYYY-MM"
          placeholder="选择调度令月份"
          style="width: 160px"
          @change="load"
        />
        <el-button type="primary" :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- ③ 未上传排产计划 -->
    <div class="block-card">
      <div class="block-header">
        <span class="section-dot" style="background:#ed8936;"></span>
        <span class="block-title" style="color:#ed8936;">未上传排产计划</span>
        <el-tag type="warning" size="small">{{ notUploadedList.length }}</el-tag>
      </div>
      <el-table :data="notUploadedList" style="width: 100%" :row-style="{ height: '48px' }">
        <el-table-column label="项目名称" min-width="240">
          <template #default="{ row }">
            <a class="proj-link" @click="goDetail(row)">{{ row.project_name }}</a>
          </template>
        </el-table-column>
        <el-table-column label="机号" prop="machine_type" width="100">
          <template #default="{ row }">{{ row.machine_type || '-' }}</template>
        </el-table-column>
        <el-table-column label="塔筒厂家" prop="factory_name" min-width="140" />
        <el-table-column label="交付负责人" prop="delivery_person" width="110" />
        <el-table-column label="计划开工 → 交付" min-width="200">
          <template #default="{ row }">
            {{ row.plan_start_date || '-' }} → {{ row.plan_end_date || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span class="st-pill" style="background:#fffaf0; color:#ed8936;">未上传</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :disabled="!auth.canEdit" @click="openImport(row)">导入</el-button>
            <el-button size="small" @click="goDetail(row)">查看</el-button>
            <el-button size="small" type="warning" plain disabled title="预警功能即将上线">预警</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!notUploadedList.length" description="暂无未上传排产计划的项目" :image-size="80" />
    </div>

    <!-- ④ 已上传排产计划 -->
    <div class="block-card" style="margin-top: 20px;">
      <div class="block-header">
        <span class="section-dot" style="background:#38a169;"></span>
        <span class="block-title" style="color:#38a169;">已上传排产计划</span>
        <el-tag type="success" size="small">{{ uploadedList.length }}</el-tag>
      </div>
      <el-table :data="uploadedList" style="width: 100%" :row-style="{ height: '48px' }">
        <el-table-column label="项目名称" min-width="240">
          <template #default="{ row }">
            <a class="proj-link" @click="goDetail(row)">{{ row.project_name }}</a>
          </template>
        </el-table-column>
        <el-table-column label="机号" prop="machine_type" width="100">
          <template #default="{ row }">{{ row.machine_type || '-' }}</template>
        </el-table-column>
        <el-table-column label="塔筒厂家" prop="factory_name" min-width="140" />
        <el-table-column label="交付负责人" prop="delivery_person" width="110" />
        <el-table-column label="计划开工 → 交付" min-width="200">
          <template #default="{ row }">
            {{ row.plan_start_date || '-' }} → {{ row.plan_end_date || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span class="st-pill" style="background:#f0fff4; color:#38a169;">已上传</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :disabled="!auth.canEdit" @click="openImport(row)">重新导入</el-button>
            <el-button size="small" @click="goDetail(row)">查看</el-button>
            <el-button size="small" type="warning" plain disabled title="预警功能即将上线">预警</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!uploadedList.length" description="暂无已上传排产计划的项目" :image-size="80" />
    </div>

    <!-- 导入弹窗（复用 ScheduleImport） -->
    <el-dialog v-model="importVisible" :title="`导入排产计划：${importTarget?.project_name || ''}`" width="560px" destroy-on-close>
      <ScheduleImport v-if="importTarget" :pid="String(importTarget.id)" :disabled="!auth.canEdit" @imported="onImported" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { fetchProjects } from '../api/node'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import ScheduleImport from './ScheduleImport.vue'

const router = useRouter()
const store = useProjectStore()
const auth = useAuthStore()   // 普通账号仅可查看排产总览，导入/重新导入禁用

const allItems = ref([])
const filters = ref({ keyword: '', person: '', uploadStatus: 'all' })

// 统计
const totalCount = computed(() => allItems.value.length)
const uploadedCount = computed(() => allItems.value.filter((p) => p.has_schedule_plan).length)
const notUploadedCount = computed(() => totalCount.value - uploadedCount.value)
const monthDueCount = computed(
  () => allItems.value.filter((p) => Number(p.monthly_plan || 0) > 0).length,
)

// 分组 + 筛选
const filtered = computed(() => {
  let list = allItems.value
  const kw = filters.value.keyword.trim().toLowerCase()
  if (kw) {
    list = list.filter(
      (p) =>
        String(p.project_name || '').toLowerCase().includes(kw) ||
        String(p.machine_type || '').toLowerCase().includes(kw),
    )
  }
  if (filters.value.person) {
    list = list.filter((p) => String(p.delivery_person || '') === filters.value.person)
  }
  const st = filters.value.uploadStatus
  if (st === 'uploaded') list = list.filter((p) => p.has_schedule_plan)
  if (st === 'not_uploaded') list = list.filter((p) => !p.has_schedule_plan)
  return list
})
const notUploadedList = computed(() => filtered.value.filter((p) => !p.has_schedule_plan))
const uploadedList = computed(() => filtered.value.filter((p) => p.has_schedule_plan))

function applyFilter() { /* computed 自动响应 */ }

// 导入弹窗
const importVisible = ref(false)
const importTarget = ref(null)
function openImport(row) {
  importTarget.value = row
  importVisible.value = true
}
async function onImported() {
  importVisible.value = false
  ElMessage.success('排产计划导入成功')
  await load()
}

// 跳详情（节点计划 Tab）
function goDetail(row) {
  router.push(`/projects/${row.id}`)
}

async function load() {
  store.ensureMonth()   // 共享月份非空（默认当前自然月）
  const res = await fetchProjects({
    page: 1,
    page_size: 1000,
    month: store.filters.month || undefined,
  })
  allItems.value = res.items || []
}

onMounted(() => {
  if (!store.allPersons.length) store.loadAllPersons()
  load()
})
</script>

<style scoped>
.schedule-overview { }
.kpi-row { display: flex; gap: 16px; margin-bottom: 16px; }
.kpi-card {
  flex: 1; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 18px 20px;
}
.kpi-value { font-size: 28px; font-weight: 700; color: #1a365d; }
.kpi-label { font-size: 13px; color: #718096; margin-top: 4px; }
.block-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; }
.block-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.section-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.block-title { font-size: 15px; font-weight: 600; }
.search-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.st-pill { display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 12px; }
.proj-link { color: #3182ce; cursor: pointer; font-weight: 500; }
.proj-link:hover { text-decoration: underline; }
</style>

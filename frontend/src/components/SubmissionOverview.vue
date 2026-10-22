<template>
  <div class="submission-wrap">
    <!-- ① 工具条：月份与共享 store.filters.month 联动（切换自动重取） -->
    <div class="block-card">
      <div class="toolbar">
        <el-date-picker
          v-model="store.filters.month"
          type="month"
          value-format="YYYY-MM"
          placeholder="选择月份"
          style="width: 160px"
          :disabled="editing"
          @change="onMonthChange"
        />
        <el-button type="primary" :icon="Refresh" :loading="loading" :disabled="editing" @click="load">刷新</el-button>
        <span class="hint">× = 当天有计划但当日完全未提报（仅判定至昨天 {{ board.cutoff || '—' }}）</span>
        <span v-if="editing" class="hint-edit">
          编辑中：点一下格子即「取消 / 加上 ×」，再点一下恢复自动判定；改完点「保存」生效
        </span>
      </div>
    </div>

    <!-- ② 统计卡片（与其它页 KPI 结构一致） -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-value">{{ summary.manager_count }}</div>
        <div class="kpi-label">负责人数量</div>
      </div>
      <div class="kpi-card kpi-missed">
        <div class="kpi-value" style="color:#e53e3e;">{{ missedTotal }}</div>
        <div class="kpi-label">未按时提报（人·天）</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{{ summary.day_count }}</div>
        <div class="kpi-label">当月天数</div>
      </div>
      <div class="kpi-card kpi-blue">
        <div class="kpi-value" style="font-size: 22px;">{{ board.cutoff || '—' }}</div>
        <div class="kpi-label">判定截止日（今天 {{ board.today || '—' }} 不计）</div>
      </div>
    </div>

    <!-- ③ 矩阵表格：负责人（左固定）× 当月日期 -->
    <div class="block-card">
      <div class="block-header">
        <span class="icon"></span>
        <span class="block-title">提报情况总览</span>
        <el-tag type="info" size="small">{{ viewRows.length }}</el-tag>
        <span class="block-subtitle">{{ board.month || '—' }} · 当月日期 × 负责人</span>

        <!-- 管理员「编辑」入口（大区账号不渲染） -->
        <div v-if="isAdmin" class="edit-actions">
          <template v-if="!editing">
            <el-button size="small" type="primary" plain :icon="Edit" :disabled="!viewRows.length" @click="startEdit">
              编辑
            </el-button>
          </template>
          <template v-else>
            <span v-if="changedCount" class="edit-dirty-hint">待保存 {{ changedCount }} 处</span>
            <el-button size="small" type="primary" :icon="Check" :loading="saving" @click="save">保存</el-button>
            <el-button size="small" :icon="Close" :disabled="saving" @click="cancel">取消</el-button>
          </template>
        </div>
      </div>

      <div v-loading="loading" element-loading-text="加载中...">
        <el-table
          v-if="viewRows.length"
          :data="viewRows"
          border
          size="small"
          style="width: 100%"
        >
          <!-- 负责人列：左固定；2026-11 需求 —— 表头与数据**居中**（仅本列，其它列不动） -->
          <el-table-column prop="manager" label="负责人" width="110" fixed="left" align="center">
            <template #default="{ row }">
              <span class="manager-cell">{{ row.manager }}</span>
            </template>
          </el-table-column>

          <!-- 当月每日一列（纵表头显示日号 1…31） -->
          <el-table-column
            v-for="d in dateColumns"
            :key="d.date"
            :prop="d.date"
            :label="String(d.day)"
            width="36"
            align="center"
          >
            <template #default="{ row }">
              <!--
                🔴 tooltip 绝不允许吃掉点击：编辑态下鼠标在相邻格之间快速移动时，
                tooltip 弹层（体量可达 480×180）会盖住上一行的格子，导致该次 click 落在
                tooltip 上而"点了没反应"。两道防线：
                  ① :enterable="false"（本版 Element Plus 用 enterable；2.9+ 的 interactive 别名同理）
                     —— 鼠标移入弹层不再被视为"仍悬停中"；
                  ② popper-class ⇒ 全局样式 `.subm-tip-popper{pointer-events:none!important}`
                     —— 从命中测试层面彻底移出鼠标事件，任何版本/任何内容都不会拦截点击。
                另有 ③ 编辑态提高 show-after（800ms）并去掉超长 caveat 段落，缩小遮挡面积。
              -->
              <el-tooltip
                placement="top"
                :show-after="editing ? 800 : 80"
                :enterable="false"
                popper-class="subm-tip-popper"
                :disabled="!row.byDate[d.date]"
              >
                <template #content>
                  <div class="subm-tip-line subm-tip-title">{{ row.manager }} · {{ d.date }}</div>
                  <template v-if="row.byDate[d.date]">
                    <div v-if="row.byDate[d.date].has_plan" class="subm-tip-line">
                      该日计划 {{ row.byDate[d.date].plan_count }} 个节点
                    </div>
                    <div v-if="!editing && row.byDate[d.date].processes.length" class="subm-tip-line">
                      涉及工序：{{ procText(row.byDate[d.date]) }}
                    </div>
                    <!-- 2026-11 覆盖口径：说明「为什么有×/为什么留空」背后的已覆盖节点数。
                         全部覆盖 → 不留×；部分覆盖 → 仍判未按时，但这里标注已覆盖 N/M。 -->
                    <div v-if="row.byDate[d.date].covered_count > 0" class="subm-tip-line">
                      已视为已提报 {{ row.byDate[d.date].covered_count }}/{{ row.byDate[d.date].plan_count }} 个节点
                      <span class="subm-tip-meta">
                        （提前完成 {{ row.byDate[d.date].covered_early }}<template v-if="row.byDate[d.date].covered_paused">、前置异常暂停 {{ row.byDate[d.date].covered_paused }}</template>）
                      </span>
                    </div>
                    <!-- 非编辑态：已被人工覆盖的格子明确说明「改成了什么、谁改的、何时改的」 -->
                    <div v-if="!editing && row.byDate[d.date].override" class="subm-tip-line subm-tip-ovr">
                      人工调整为「{{ row.byDate[d.date].override === 'missed' ? '未按时提报（×）' : '已按时提报（留空）' }}」
                      <span v-if="overrideMeta(row.byDate[d.date])" class="subm-tip-meta">（{{ overrideMeta(row.byDate[d.date]) }}）</span>
                    </div>
                    <div v-if="!editing && row.byDate[d.date].missed" class="subm-tip-line">
                      自动判定为未按时：{{ row.byDate[d.date].covered_count > 0
                        ? `剩余 ${row.byDate[d.date].plan_count - row.byDate[d.date].covered_count} 个节点当天无填报、无异常提报`
                        : '当天未填报、未提报异常' }}
                    </div>
                    <div v-if="!editing && !row.byDate[d.date].missed && row.byDate[d.date].auto_missed" class="subm-tip-line">
                      自动判定为未按时，已人工调整为已按时
                    </div>
                    <div v-if="!editing && row.byDate[d.date].missed && !row.byDate[d.date].auto_missed" class="subm-tip-line">
                      自动判定为已提报，已人工标记为未按时
                    </div>
                    <!-- 编辑态：只用两行说明（自动判定 + 点击结果），避免大面积遮挡 -->
                    <div v-if="editing" class="subm-tip-line">
                      自动判定：{{ row.byDate[d.date].auto_missed ? '未按时（×）' : '按时（留空）' }}
                      <span v-if="row.byDate[d.date].original" class="subm-tip-meta">
                        · 原有覆盖：{{ row.byDate[d.date].original === 'missed' ? '未按时' : '按时' }}
                      </span>
                    </div>
                    <div v-if="editing && row.byDate[d.date].editable" class="subm-tip-line subm-tip-act">
                      点击{{ row.byDate[d.date].missed ? '取消 ×' : '标记为未按时（×）' }}（再点一次恢复自动判定）
                    </div>
                    <div v-if="editing && !row.byDate[d.date].editable" class="subm-tip-line subm-tip-act">
                      不可编辑：{{ row.byDate[d.date].has_plan ? '今天/未来日期尚未判定' : '当天无计划' }}
                    </div>
                    <!-- 长文案（数据模型限制）只在非编辑态展示：编辑态下它会撑大弹层、遮挡相邻格 -->
                    <div v-if="!editing" class="subm-tip-note">{{ cellCaveat }}</div>
                  </template>
                </template>

                <div class="cell-box" :class="cellClass(row, d.date)" @click="onCellClick(row, d.date)">
                  <span v-if="row.byDate[d.date] && row.byDate[d.date].missed" class="miss-mark">×</span>
                  <span v-else class="blank-cell"></span>
                  <!-- 人工调整不显示任何视觉标识：按用户要求「手动改完留白即可，与其他未填项一样」。
                       需要确认某格是否人工调整过时，悬停 tooltip 仍会显示「人工调整为…（操作人 时间）」。 -->
                  <!-- 未保存改动标识：右上角橙色角标 -->
                  <i v-if="row.byDate[d.date] && row.byDate[d.date].dirty" class="dirty-dot"></i>
                </div>
              </el-tooltip>
            </template>
          </el-table-column>

          <!-- 每行小计：右固定 -->
          <el-table-column label="合计" width="76" align="center" fixed="right">
            <template #default="{ row }">
              <span :class="row.missedTotalView > 0 ? 'miss-total' : 'miss-total-zero'">
                {{ row.missedTotalView > 0 ? row.missedTotalView : '—' }}
              </span>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-else-if="!loading" description="当月暂无排产计划" />
      </div>
    </div>

    <!-- ④ 口径说明：按用户要求从前端隐藏（原文见 git 历史）。
         口径信息仍保留在：单元格 tooltip（计划数/工序/自动判定/人工调整记录）+ 接口 caveat 字段。 -->
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Edit, Check, Close } from '@element-plus/icons-vue'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import { fetchSubmissionBoard, saveSubmissionOverrides } from '../api/ranking'

const store = useProjectStore()   // 共享筛选月份（与其它页联动）
const auth = useAuthStore()       // 角色判定：仅管理员可进入编辑态

const loading = ref(false)
const saving = ref(false)
const editing = ref(false)        // 是否处于编辑态（批量保存模式）
/**
 * 未保存改动草稿：key = `${manager}\u0001${date}`，value = 'missed' | 'on_time' | null
 * null 表示「恢复自动判定」（提交时 action='auto'）。
 * 与后端 cell.override 相同的三态，便于「无改动」判定（与原始值相同即从草稿中删除）。
 */
const draft = ref({})
const DRAFT_SEP = '\u0001'

const rows = ref([])
const board = ref({
  month: '',
  today: '',
  cutoff: '',
  dates: [],
  rows: [],
  summary: { manager_count: 0, missed_total: 0, day_count: 0 },
  caveat: '',
})

const isAdmin = computed(() => auth.isAdmin === true)

/**
 * 表格列定义：由后端返回的 dates（'YYYY-MM-DD'）派生日号。
 * 2026-10 清理：原先还算了一个 `weekend` 标记，但它只服务于已被删除的
 * :cell-style 钩子（该钩子及其函数从未定义过，永远传 undefined），全文件无其它消费方。
 */
const dateColumns = computed(() =>
  (board.value.dates || []).map((ds) => ({ date: ds, day: Number(ds.slice(8, 10)) }))
)

const summary = computed(() => board.value.summary || { manager_count: 0, missed_total: 0, day_count: 0 })
const caveat = computed(() => board.value.caveat || '填报记录按节点覆盖式保存，历史个别已提报日期可能被反标为 ×。')

/** 草稿中尚未保存的改动数量 */
const changedCount = computed(() => Object.keys(draft.value).length)

/**
 * 展示用行数据：把「服务端 cell + 本地草稿」合并成最终展示值。
 *
 * 合并规则（与后端完全一致，保证「保存前预览 == 保存后结果」）：
 *   override === 'missed'  → missed = true
 *   override === 'on_time' → missed = false
 *   override === null      → missed = auto_missed（自动判定）
 * 同时算出 dirty（与原始 override 不同）与 editable（has_plan 且 judged）。
 */
const viewRows = computed(() =>
  rows.value.map((r) => {
    const byDate = {}
    let total = 0
    for (const c of r.cells || []) {
      const key = draftKey(r.manager, c.date)
      const has = Object.prototype.hasOwnProperty.call(draft.value, key)
      const original = c.override || null
      const override = has ? draft.value[key] : original
      const missed = override === 'missed' ? true : override === 'on_time' ? false : !!c.auto_missed
      if (missed) total += 1
      byDate[c.date] = {
        ...c,
        original,
        override,
        missed,
        dirty: has && override !== original,
        editable: !!(c.has_plan && c.judged),
      }
    }
    return { manager: r.manager, byDate, missedTotalView: total }
  })
)

/** KPI「未按时提报（人·天）」：按最终值汇总（编辑态下随点击实时变化，保存后与后端一致） */
const missedTotal = computed(() => viewRows.value.reduce((sum, r) => sum + r.missedTotalView, 0))

/**
 * 单元格 tooltip 用的精简说明：只保留「填报覆盖式保存」这一段。
 * 后端 caveat 由两段组成——①填报覆盖（与 × 判定直接相关，逐格提示需要）
 * ②排产整体覆盖导入（历史月可能空白，属整页层面的说明，已在页面底部口径说明呈现）。
 * 用「另：」切分；若后端文案结构调整导致切不开，则回退整段（宁可啰嗦，不可漏说明）。
 */
const cellCaveat = computed(() => {
  const full = caveat.value
  const idx = full.indexOf('另：')
  return idx > 0 ? full.slice(0, idx).trim() : full
})

/** 草稿 key：负责人可能含任意字符，用 \u0001 分隔避免歧义 */
function draftKey(manager, date) {
  return `${manager}${DRAFT_SEP}${date}`
}

/** 覆盖记录的操作人 / 时间文案（tooltip 用） */
function overrideMeta(cell) {
  if (!cell || !cell.override) return ''
  const by = String(cell.override_by || '').trim()
  const at = String(cell.override_at || '').trim()
  if (by && at) return `${by} ${at}`
  return by || at || ''
}

/** 工序名最多展示 3 个，超出补「等」 */
function procText(cell) {
  const names = (cell && cell.processes) || []
  if (!names.length) return '—'
  const head = names.slice(0, 3).join('、')
  return names.length > 3 ? `${head} 等 ${names.length} 个` : head
}

/** 单元格样式类：编辑态可点/置灰、改动标识、人工覆盖底纹 */
function cellClass(row, date) {
  const c = row.byDate[date]
  if (!c) return []
  const cls = []
  if (editing.value) {
    cls.push(c.editable ? 'cell-editable' : 'cell-locked')
  }
  if (c.dirty) {
    cls.push('cell-dirty')
  }
  // 非编辑态不为「已保存的人工调整」加底纹/角标：按用户要求保持留白，与普通空格一致
  return cls
}

/**
 * 编辑态点击格子：**以「当前显示值」为准的翻转**（用户口径「点一下将 × 取消或者增加」）。
 *
 * 核心不变式（P3-2 修复）：**每一次点击都必然翻转可见标记（× ↔ 留空）**，不存在
 * 「点了没反应」的格子——包括「已有覆盖记录」的格子作为起点。
 *
 * 规则（一句）：把显示翻到另一侧；若另一侧的显示值恰好等于**自动判定值**，
 * 就直接删掉覆盖记录（= 回到自动判定），否则写入对应的强制态。
 *   target = !当前显示
 *   target === auto_missed ? 无记录(delete) : (target ? 'missed' : 'on_time')
 *
 * 于是每个格子实际是「自动判定 ⇄ 强制另一侧」的双向切换，两步之内必回自动：
 *   ① auto_missed = true（自动显示 ×）
 *      自动(×) ──点──▶ on_time(留空,待保存) ──点──▶ 自动(×,回到自动判定)
 *      若起点是历史/接口写入的 missed(×)：missed(×) ──点──▶ on_time(留空) ──点──▶ 自动(×)
 *   ② auto_missed = false（自动显示留空）
 *      自动(留空) ──点──▶ missed(×,待保存) ──点──▶ 自动(留空,回到自动判定)
 *      若起点是历史/接口写入的 on_time(留空)：on_time ──点──▶ missed(×) ──点──▶ 自动(留空)
 *
 * 关于「三种覆盖记录状态」：'missed' / 'on_time' / 无记录 依然全部由 UI 可写入——
 * 'missed' 在所有「自动判定为按时」的格子上点一下即得，'on_time' 在所有「自动判定为未按时」
 * 的格子上点一下即得，无记录由任意格子再点一下即得。唯一**有意**不再作为点击目标的是
 * 「强制值与自动判定同向」的组合（如自动已是 × 还要强制 ×）：它与自动判定显示完全相同，
 * 正是「点了没反应」的根因；该组合记录仍被后端与矩阵完整支持（历史数据/接口写入照旧生效，
 * 存在时第一下点击会把它翻到可见的另一侧）。
 *
 * - 今日/未来、无计划的格子不可点（与后端校验一致）
 * - 非编辑态点击无任何副作用（只读）
 */
function onCellClick(row, date) {
  if (!editing.value) return
  const c = row.byDate[date]
  if (!c || !c.editable) return
  const key = draftKey(row.manager, date)
  const targetMissed = !c.missed          // 翻转当前**显示**值（c.missed 已是「草稿合并后」的显示值）
  // 目标显示值与自动判定一致 → 无需覆盖记录，直接删除（回到自动判定）
  const next = targetMissed === c.auto_missed ? null : (targetMissed ? 'missed' : 'on_time')
  const nextDraft = { ...draft.value }
  if (next === c.original) {
    delete nextDraft[key]        // 回到原值 → 不算改动
  } else {
    nextDraft[key] = next
  }
  draft.value = nextDraft
}

/** 进入编辑态 */
function startEdit() {
  draft.value = {}
  editing.value = true
}

/** 取消：有改动时二次确认后丢弃全部本地改动（不触碰后端） */
async function cancel() {
  const pending = changedCount.value
  if (pending > 0) {
    try {
      await ElMessageBox.confirm(
        `确认放弃本次 ${pending} 处未保存的调整？`,
        '取消编辑',
        { type: 'warning', confirmButtonText: '放弃改动', cancelButtonText: '继续编辑' },
      )
    } catch (e) {
      return   // 用户选择「继续编辑」
    }
  }
  draft.value = {}
  editing.value = false
  ElMessage(pending > 0 ? `已放弃 ${pending} 处未保存的调整` : '已退出编辑')
}

/**
 * 保存：把草稿一次性批量提交（每格一条 {manager, date, action}）。
 * action 语义：'missed' 强制未按时 / 'on_time' 强制已按时 / 'auto' 恢复自动判定。
 * 成功后用响应里的最新矩阵刷新（省一次 GET）并退出编辑态。
 */
async function save() {
  if (!changedCount.value) {
    ElMessage('没有需要保存的修改')
    return
  }
  const items = Object.entries(draft.value).map(([key, action]) => {
    const idx = key.indexOf(DRAFT_SEP)
    return {
      manager: key.slice(0, idx),
      date: key.slice(idx + DRAFT_SEP.length),
      action: action || 'auto',
    }
  })
  saving.value = true
  try {
    const res = await saveSubmissionOverrides(store.filters.month, items)
    applyBoard(res?.board)
    draft.value = {}
    editing.value = false
    ElMessage(`已保存 ${res?.saved ?? items.length} 处调整`)
  } catch (e) {
    // 具体原因（403/400/503）由 axios 拦截器统一提示，此处仅保证不退出编辑态、不丢草稿
    ElMessage('保存失败，改动仍保留在页面，可修正后重试')
  } finally {
    saving.value = false
  }
}

/** 把后端矩阵写入本地状态（GET 与 POST 响应共用） */
function applyBoard(data) {
  board.value = data || {}
  const list = (data?.rows || []).map((r) => {
    const byDate = {}
    for (const c of r.cells || []) byDate[c.date] = c
    return { ...r, byDate }
  })
  // 拼音首字母升序（后端已按 gbk 排序，此处以浏览器 ICU 的 zh-CN 排序为最终口径）
  list.sort((a, b) => String(a.manager).localeCompare(String(b.manager), 'zh-CN'))
  rows.value = list
}

/** 加载矩阵数据；月份切换（store.filters.month 变化）时自动重取 */
async function load() {
  loading.value = true
  store.ensureMonth()   // 共享月份非空（默认当前自然月）
  try {
    const res = await fetchSubmissionBoard(store.filters.month)
    applyBoard(res)
  } catch (e) {
    // 错误已由 axios 拦截器统一提示
    rows.value = []
    board.value = {
      month: store.filters.month,
      today: '',
      cutoff: '',
      dates: [],
      rows: [],
      summary: { manager_count: 0, missed_total: 0, day_count: 0 },
      caveat: '',
    }
  } finally {
    loading.value = false
  }
}

/** 月份切换：编辑态下先丢弃草稿（避免把 A 月的改动存到 B 月） */
function onMonthChange() {
  if (editing.value) {
    const pending = changedCount.value
    draft.value = {}
    editing.value = false
    ElMessage(pending > 0
      ? `月份已切换，${pending} 处未保存的调整已放弃`
      : '已退出编辑（月份已切换）')
  }
  load()
}

// 其它页面同改 store.filters.month 时也要清理草稿（月份选择器本身在编辑态已禁用）
watch(() => store.filters.month, (val, old) => {
  if (val === old) return
  if (editing.value) {
    draft.value = {}
    editing.value = false
    ElMessage('月份已切换，未保存的调整已放弃')
  }
})

onMounted(load)
</script>

<style scoped>
.submission-wrap { }
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hint { color: #718096; font-size: 13px; }
.hint-edit { color: #b7791f; font-size: 13px; }
.kpi-row { display: flex; gap: 16px; margin: 16px 0; }
.kpi-card {
  flex: 1; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px;
}
.kpi-value { font-size: 28px; font-weight: 700; color: #1a365d; line-height: 1.2; }
.kpi-label { font-size: 13px; color: #718096; margin-top: 6px; }
.kpi-missed { border-top: 3px solid #e53e3e; }
.kpi-blue { border-top: 3px solid #3182ce; }
.block-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }
.block-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.block-title { font-size: 15px; font-weight: 600; color: #1a365d; }
.block-subtitle { font-size: 13px; color: #718096; margin-left: auto; }

/* 编辑入口（标题区右侧） */
.edit-actions { display: flex; align-items: center; gap: 8px; margin-left: 12px; }
.edit-dirty-hint { font-size: 12px; color: #b7791f; font-weight: 600; }

/* 负责人列 */
.manager-cell { font-weight: 600; color: #1a365d; font-size: 13px; }
/* 未按时提报标记：语义红 */
.miss-mark {
  display: inline-block;
  color: #e53e3e;
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
  cursor: default;
}
.blank-cell { display: inline-block; }
.miss-total { color: #e53e3e; font-weight: 700; font-size: 13px; }
.miss-total-zero { color: #cbd5e0; font-size: 13px; }

/* 单元格容器：撑满 36×38 的日格，承载点击区与角标 */
.cell-box {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 36px;
  border-radius: 6px;
  transition: background-color 0.12s ease;
}
/* 编辑态：可编辑格 —— 可点 + hover 高亮 */
.cell-box.cell-editable { cursor: pointer; }
.cell-box.cell-editable:hover { background: #ebf8ff; outline: 1px solid #90cdf4; outline-offset: -1px; }
/* 编辑态：不可编辑格 —— 置灰 + not-allowed（今天/未来、无计划） */
.cell-box.cell-locked { cursor: not-allowed; background: #f7fafc; }
/* 未保存改动：虚线边框 + 暖色底纹，与「已保存的人工覆盖」明显区分 */
.cell-box.cell-dirty {
  background: #fffaf0;
  outline: 1px dashed #dd6b20;
  outline-offset: -1px;
}
/* 人工调整标识已整体移除（用户要求「手动改完留白即可，与其他未填项一样」）：
   原 .cell-override / .cell-ontime 底纹与 .ovr-dot 右上角圆点一并删除。
   需要确认某格是否人工调整过时，悬停 tooltip 仍会显示「人工调整为…（操作人 时间）」。 */
/* 右上角橙色角标：未保存改动 */
.dirty-dot {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #dd6b20;
}

/* 偶数行极淡底色 */
:deep(.el-table .even-row td.el-table__cell) { background: #f7fafc; }

/* 紧凑表头：日号居中 */
:deep(.el-table th.el-table__cell > .cell) { padding: 0; text-align: center; }
:deep(.el-table td.el-table__cell > .cell) { padding: 0; }

/* tooltip 内部排版
   ⚠️ el-tooltip 的内容被 teleport 到 body，scoped 样式不生效，故见下方非 scoped 样式块 */

/* 口径说明 */
.note-card { background: #fff; }
.note-title { font-size: 14px; font-weight: 700; color: #1a365d; margin-bottom: 8px; }
.note-list { margin: 0; padding-left: 18px; }
.note-list li { font-size: 13px; color: #4a5568; line-height: 1.9; }
.note-list code {
  background: #f4f6f9;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 0 4px;
  font-size: 12px;
  color: #2b6cb0;
}
.note-warn { color: #975a16; }
.note-dim { color: #718096; }
</style>

<!-- tooltip 内容被 teleport 到 body，scoped 样式不生效 → 用唯一前缀的全局样式 -->
<style>
/* 🔴 P3-1：tooltip 弹层必须「不参与命中测试」。
   编辑态下鼠标从下一行移到上一行时，弹层会盖住上一行的格子；若弹层可接收指针事件，
   这一次 click 就落在 .subm-tip-* 上被吞掉（现象：点了没反应，需先移开 500ms 再点）。
   根节点 + 全部子节点都设为 pointer-events:none，任何版本/任何内容都不会拦截点击。 */
.subm-tip-popper,
.subm-tip-popper * { pointer-events: none !important; }
.subm-tip-popper { max-width: 300px; }

.subm-tip-line {
  line-height: 1.7;
  font-size: 12px;
  white-space: normal;
}
.subm-tip-title { font-weight: 700; margin-bottom: 2px; }
.subm-tip-ovr { color: #fefcbf; font-weight: 600; }
.subm-tip-meta { color: rgba(255, 255, 255, 0.85); }
.subm-tip-act { color: #bee3f8; }
.subm-tip-note {
  margin-top: 8px;
  padding-top: 8px;
  max-width: 320px;
  border-top: 1px solid rgba(255, 255, 255, 0.28);
  font-size: 11px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.92);
  white-space: normal;
}
</style>

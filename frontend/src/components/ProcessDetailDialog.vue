<template>
  <el-dialog
    :model-value="modelValue"
    :title="`工序：${processName}`"
    width="88vw"
    :style="{ maxWidth: '1200px' }"
    :close-on-click-modal="false"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template v-if="detail">
      <el-tabs v-model="innerMode">
        <el-tab-pane label="📋 节点详情" name="detail">
          <!-- 独立工序（累计完成总数 / 累计发运总数）：仅渲染一张占位汇总卡
               「完成」= 所有日报行 actual_qty 之和；每次填报产生的日期行
               只在「填报进度 → 已完成」分组中展示，不进节点详情主视图。 -->
          <template v-if="isIndependent">
            <div class="row-card row-grid-detail">
              <div class="row-bar" :style="{ background: colorOf(independentStatus.status) }"></div>
              <div class="row-info">
                <div class="row-qty-line">
                  <span class="qty-text">
                    共计 <span class="qty-num">{{ independentContract }}</span> 套 / 完成 <span class="qty-num">{{ independentFilled }}</span> 套
                  </span>
                  <span v-if="latestIndependentDate" class="latest-date">
                    <span class="ld-key">最新完成日期</span>
                    <span class="ld-val">{{ latestIndependentDate }}</span>
                  </span>
                </div>
              </div>
              <span class="status-pill" :style="pillStyle(independentStatus.status)">{{ independentStatus.label }}</span>
              <div class="deviation-label">-</div>
            </div>
          </template>
          <!-- 11 道排产工序：按节点逐行展示（分页展开，避免 60+ 行一次性渲染卡顿） -->
          <template v-else>
            <!-- 异常汇总条（2026-11 改造）：让用户一眼看出「本工序有哪几套存在**生效中**异常」
                 数据源 = 后端 enrich_rows 的 has_active_exception / active_exception_processes /
                 exception_paused / set_date；第二行单独提示「已超计划关闭日」的条数
                 （expired ≠ closed：暂停已失效，下游已恢复逾期判定）。 -->
            <div v-if="activeExcSets.length || expiredExcCount" class="exc-banner">
              <template v-if="activeExcSets.length">
                <span class="exc-banner-title">⚠️ 本工序有 {{ activeExcSets.length }} 套存在<strong>生效中</strong>异常</span>
                <span class="exc-banner-body">
                  <span v-for="s in activeExcSets" :key="s.key" class="exc-banner-item">
                    {{ s.label }}
                  </span>
                </span>
                <!-- 说明文案已移除（2026-10 用户要求）：暂停/重算口径在异常记录页与状态胶囊已可推断，不再占一行 -->
              </template>
              <span v-if="expiredExcCount" class="exc-banner-expired">
                另有 {{ expiredExcCount }} 条已超计划关闭日，暂停已失效，已恢复逾期判定
              </span>
            </div>
            <template v-for="row in displayedDetailNodes" :key="row.id">
            <div
              class="row-card row-grid-detail"
              :class="{ 'row-has-exception': row.has_open_exception }"
            >
              <div class="row-bar" :style="{ background: colorOf(row.status) }"></div>
              <div class="row-info">
                <div class="row-dates">
                  <div class="date-block">
                    <span class="date-key">计划</span>
                    <span class="date-val">{{ row.plan_date }}</span>
                    <!-- 已关闭异常把锚点后推 → 展示重算后的计划日，并标注原排产日 -->
                    <span
                      v-if="row.plan_date_plan && row.plan_date_plan !== row.plan_date"
                      class="date-orig"
                      :title="`原排产计划日 ${row.plan_date_plan}（已按异常解决时间重算为新计划日）`"
                    >原 {{ row.plan_date_plan }}</span>
                  </div>
                  <div class="date-block">
                    <span class="date-key">实际</span>
                    <span v-if="(row.actual_qty || 0) > 0" class="date-val">{{ row.report_date || '—' }}</span>
                    <span v-else class="date-val date-empty">暂无</span>
                  </div>
                </div>
                <div class="row-qty-line">
                  <span class="qty-text">
                    计划 <span class="qty-num">{{ row.plan_qty }}</span> 套 / 实际 <span class="qty-num">{{ row.actual_qty }}</span> 套
                    <!-- 按段填报（v7.1 行级化）：有段记录的行追加橙色段进度提示
                         🔴 2026-10 用户口径：**整行已按套完成时不再显示段进度** ——
                         按段与按套是两条独立录入路径，按套报完代表该套工序已完成，
                         此时再挂着「已完成 2/5 段」会让用户误以为还有未完成的分段问题。
                         段记录本身保留在库里（不删数据），只是不再作为提示出现在界面。 -->
                    <span
                      v-if="row.segment_total != null && !isRowSetDone(row)"
                      style="color:#b7791f;"
                    >&nbsp;已完成 {{ row.segment_done }}/{{ row.segment_total }} 段</span>
                  </span>
                  <!-- 「第 N 套」明细开关（2026-10）：仅 has_set_detail=true 的行出现；
                       点开后在本行下方折叠出逐套子行，父行本身保持原样 -->
                  <span
                    v-if="row.has_set_detail"
                    class="set-badge"
                    :title="`展开/收起本行 ${row.set_count} 套的逐套计划日与推定完成情况（只读）`"
                    @click="toggleSetRows(row.id)"
                  >共 {{ row.set_count }} 套（第1-{{ row.set_count }}套）{{ expandedSetRows[row.id] ? ' ▴' : ' ▾' }}</span>
                  <!-- 行内异常 chip 已移除（2026-10 用户要求）：异常具体原因统一在「⚠️ 异常记录」页签查看，
                       行内只保留状态胶囊（异常 / 异常暂停 / 计划关闭日），避免每行重复堆叠 -->
                </div>
              </div>
              <span class="status-pill" :style="pillStyle(row.status)">{{ row.label }}</span>
              <div class="deviation-label">{{ row.deviation_label }}</div>
            </div>
            <!-- 逐套子行（只读，2026-10）：第 N 套 · 计划日 · 推定完成 · 暂停/异常标识。
                 has_set_detail=false 的行不会走这个分支 → 渲染与改造前像素级一致。 -->
            <div
              v-if="row.has_set_detail && expandedSetRows[row.id]"
              class="set-child-list"
            >
              <div
                v-for="s in (row.sets || [])"
                :key="`${row.id}-${s.set_seq}`"
                class="set-child"
                :class="{ 'set-child-paused': s.exception_paused }"
              >
                <span class="set-name">第 {{ s.set_seq }} 套</span>
                <span class="set-date">计划 {{ s.plan_date }}</span>
                <span
                  v-if="s.plan_date_plan && s.plan_date_plan !== s.plan_date"
                  class="date-orig"
                  :title="`该套原排产计划日 ${s.plan_date_plan}（按该套自己的下料锚点重算）`"
                >原 {{ s.plan_date_plan }}</span>
                <span class="set-actual">
                  实际 {{ s.actual_qty_est }} 套<span
                    v-if="s.actual_qty_est && s.derived"
                    class="set-derived"
                    title="合并填报，无逐套实际值：按套号升序推定（前 N 套视为完成）"
                  >（推定）</span>
                </span>
                <span v-if="s.source === 'backfill'" class="set-src" title="该套号来自历史/补录行（无排产归属月），套号属推定">（推定套号）</span>
                <span class="status-pill" :style="pillStyle(s.status_display)">{{ s.label_display }}</span>
                <span
                  v-if="s.has_open_exception"
                  class="exc-chip"
                  :title="s.has_active_exception
                    ? `第 ${s.set_seq} 套存在生效中异常：${(s.exception_processes || []).join('、') || '—'}`
                    : `第 ${s.set_seq} 套的异常已超计划关闭日：暂停已失效，已恢复逾期判定`"
                >{{ s.has_active_exception ? '⚠️ ' + ((s.exception_processes || []).join('、') || '存在') + '异常' : '⚠️ 异常已超期' }}</span>
              </div>
              <div class="set-child-hint">
                逐套明细只读展示：计划日按各套自己的下料锚点重算；实际完成按套号升序推定（填报仍为合并填写）。
                整行的逾期/暂停判定仍按行口径，不受逐套明细影响。
              </div>
            </div>
            </template>
            <!-- 展开更多按钮 -->
            <div v-if="detail.nodes.length > PAGE_SIZE && !showAllDetail" class="expand-more">
              <el-button link type="primary" @click="showAllDetail = true">
                ⬇ 展开更多（还有 {{ detail.nodes.length - PAGE_SIZE }} 条）
              </el-button>
            </div>
            <div v-else-if="detail.nodes.length > PAGE_SIZE && showAllDetail" class="expand-more">
              <el-button link type="primary" @click="showAllDetail = false">
                ⬆ 收起（仅显示前 {{ PAGE_SIZE }} 条）
              </el-button>
            </div>
          </template>
        </el-tab-pane>
        <!-- 2026-11 修复：本 pane 此前带 v-if="!isIndependent"，而独立工序（累计完成总数 /
             累计发运总数）的填报 UI（下方 fill-card / record-card 两个独立分支）**全部在这个
             pane 内部** → 独立工序根本没有「填报进度」页签，用户无入口可填（线上反馈）。
             现改为对所有工序渲染；pane 内部的 v-if="isIndependent && ..." 分支自行分流。 -->
        <el-tab-pane label="📝 填报进度" name="input">
          <!-- 填报模式（四分组手风琴）：⚠️ 内容必须留在本 pane 内部（2026-11 修复）。
               历史写法是把它放在 el-tabs 之外、再用第二个 v-if="innerMode === 'input'" 控制显隐，
               于是同一个页签的「激活态」存在两份互相独立的来源：一旦某次 patch 被中断
               （例如子组件 setup 抛错），「异常记录」pane 已经显示、这块填报内容却没被卸载，
               就会看到两个页签的内容叠在一起、整块 UI 也点不动。放进 pane 后显隐只由
               el-tabs 自己的 v-show（作用在 pane 元素上、先于子节点 patch）负责，物理上不可能与
               其他页签同时可见。 -->
          <div style="font-size:12px; color:#718096; margin-bottom:10px;">
            <template v-if="isIndependent">
              累计填报：每次填写「本次新增套数」（不是累计总数），保存后按填报日期生成一条记录并累加计入累计完成数；
              上限 = 合同 {{ independentContract }} 套 − 已填报 {{ independentFilled }} 套。「已完成」分组可按日期修改或订正记录{{ auth.isAdmin ? '（管理员不限日期）' : `（日期仅可回填最近 ${BACKFILL_DAYS} 天）` }}。
            </template>
            <template v-else>
              {{ auth.isAdmin
                ? '管理员可为每行指定历史日期补录（含"已完成"组可编辑）；已保存过的节点，日期会沿用上次保存值，无变更提交不会重置为今天。未开始/未填写的节点日期默认当天（不显示历史值）。'
                : `大区账号仅可填报本大区节点；未填写节点默认当天，填报日期可回填最近 ${BACKFILL_DAYS} 天内的日期（含今天）；已保存过的节点沿用上次保存值（仅限本大区数据）` }}
            </template>
          </div>
          <el-segmented v-model="activeGroup" :options="groupOptions" block style="margin-bottom:14px;" />
          <div v-if="groupNodes.length === 0" class="empty-hint">当前分组「{{ groupLabel }}」没有可保存的节点。</div>
          <template v-else>
            <!-- 独立工序（累计完成/累计发运）· 今日待填报：单卡增量输入（管理员不限日期，大区账号可回填近 7 天） -->
            <div v-if="isIndependent && activeGroup === 'today'" class="fill-card">
              <div class="fill-card-left">
                <span class="fill-card-label">本次填报</span>
                <el-input-number
                  v-model="inputValues[groupNodes[0].id]"
                  :min="0"
                  :max="independentRemaining"
                  size="default"
                  class="fill-card-input"
                />
                <span class="fill-card-unit">套</span>
                <span class="fill-card-pending" :title="`合同 ${independentContract} − 已填报 ${independentFilled} − 本次 ${inputValues[groupNodes[0].id] || 0}`">
                  待完成 <span class="qty-num">{{ independentRemainingAfter }}</span> 套
                </span>
              </div>
              <div class="fill-card-right">
                <!-- 与 11 道排产工序的「更改填报日期」机制一致：修改本次填报的 report_date（管理员不限，大区账号限近 7 天） -->
                <div class="cell-report-date">
                  <span class="rd-tag" :class="{ 'rd-today': (reportDates[groupNodes[0].id] || fmtToday()) === fmtToday() }">
                    📅 {{ reportDates[groupNodes[0].id] || fmtToday() }}
                  </span>
                  <el-popover
                    placement="left-start"
                    :width="260"
                    trigger="click"
                    v-model:visible="datePickerOpen[groupNodes[0].id]"
                  >
                    <template #reference>
                      <el-button
                        size="small"
                        :disabled="!auth.canFill || (activeGroup === 'done' && !auth.isAdmin && !isIndependent)"
                        class="rd-btn"
                      >更改填报日期</el-button>
                    </template>
                    <div class="rd-picker-panel">
                      <div class="rd-picker-hint">
                        上次保存：<b>{{ savedDates[groupNodes[0].id] || '无' }}</b>
                      </div>
                      <el-date-picker
                        v-model="reportDates[groupNodes[0].id]"
                        type="date"
                        value-format="YYYY-MM-DD"
                        format="YYYY-MM-DD"
                        :clearable="false"
                        :teleported="false"
                        :disabled-date="isDateDisabled"
                        style="width: 100%;"
                        @change="onDatePicked(groupNodes[0].id, $event)"
                      />
                    </div>
                  </el-popover>
                </div>
                <span class="status-pill" :style="pillStyle('in_progress')">🔵 进行中</span>
              </div>
            </div>
            <!-- 独立工序· 已完成：每条记录一张卡（按日期降序；管理员可改日期/数量，大区账号置灰） -->
            <div v-else-if="isIndependent && activeGroup === 'done'">
              <div v-for="node in groupNodes" :key="node.id" class="record-card">
                <div class="record-card-left">
                  <span class="record-card-date">📅 {{ reportDates[node.id] || node.plan_date }}</span>
                  <el-input-number
                    v-model="inputValues[node.id]"
                    :min="0"
                    size="small"
                    class="cell-qty-input"
                    :disabled="!auth.isAdmin"
                  />
                  <span class="qty-unit">套</span>
                </div>
                <div class="record-card-right">
                  <!-- 与 11 道排产工序的「更改填报日期」机制一致：移动该条记录到所选日期（管理员可改，大区账号置灰） -->
                  <div class="cell-report-date">
                    <el-popover
                      placement="left-start"
                      :width="260"
                      trigger="click"
                      v-model:visible="datePickerOpen[node.id]"
                    >
                      <template #reference>
                        <el-button
                          size="small"
                          :disabled="!auth.isAdmin"
                          class="rd-btn"
                        >更改填报日期</el-button>
                      </template>
                      <div class="rd-picker-panel">
                        <div class="rd-picker-hint">
                          上次保存：<b>{{ savedDates[node.id] || '无' }}</b>
                        </div>
                        <el-date-picker
                          v-model="reportDates[node.id]"
                          type="date"
                          value-format="YYYY-MM-DD"
                          format="YYYY-MM-DD"
                          :clearable="false"
                          :teleported="false"
                          :disabled-date="isDateDisabled"
                          style="width: 100%;"
                          @change="onDatePicked(node.id, $event)"
                        />
                      </div>
                    </el-popover>
                  </div>
                  <span class="status-pill" :style="pillStyle('done')">🟢 已完成</span>
                </div>
              </div>
            </div>
            <!-- 11 道排产工序：原有 row-grid 行为（分页展开，避免大量 row-card 一次性渲染导致卡顿）
                 互斥兜底（2026-11）：显式加 !isIndependent —— 独立工序只可能落 today / done 两个分组
                 （groupOptions 已裁到这两项、打开弹窗强制 activeGroup='today'），万一分组状态异常，
                 也不会把「排产工序的日期/数量/按段填报/异常提报」混进独立工序。 -->
            <div
              v-else-if="!isIndependent"
              v-for="node in displayedGroupNodes"
              :key="node.id"
              class="row-card row-grid fill-row"
              :class="{ 'row-has-exception': hasOpenExc(node), 'is-expanded': isFillExpanded(node.id) }"
              :title="isFillExpanded(node.id) ? '点击行收起明细' : '点击行展开明细（套信息 / 填报日期 / 按段填报 / 异常提报）'"
              @click="toggleFillRow(node.id)"
            >
              <div class="row-bar" :style="{ background: colorOf(statusOf(node)) }"></div>
              <div class="row-left-section">
                <span v-if="!isIndependent" class="cell-plan-date">
                  {{ node.plan_date }}
                  <!-- 已关闭异常把锚点后推 → 生效计划日已重算，附原排产日对照（与节点详情一致） -->
                  <span
                    v-if="origPlanOf(node) && origPlanOf(node) !== node.plan_date"
                    class="date-orig"
                    :title="`原排产计划日 ${origPlanOf(node)}（已按异常解决时间重算为新计划日）`"
                  >原 {{ origPlanOf(node) }}</span>
                </span>
                <span class="cell-plan-qty">
                  <span class="qty-num">{{ node.plan_qty }}</span><span class="qty-unit">套</span>
                </span>
                <!-- 套明细（共 N 套 / 逐套计划日与完成情况）已移至下方 fill-row-detail 下拉（2026-10 界面优化） -->
                <!-- 收起态极简提示（2026-10 界面优化）：明细（套号/异常原因/填报日期/操作按钮）
                     统一收进下方 fill-row-detail 下拉，此处只留一个 ⚠️ 小标，避免一行塞满导致屏幕放不下 -->
                <span
                  v-if="hasOpenExc(node)"
                  class="exc-mini"
                  :title="excChipText(hasActiveExc(node) ? excOf(node).active_exception_processes : excOf(node).exception_processes, excOf(node).set_date, hasActiveExc(node))"
                >⚠️ 异常</span>
              </div>
              <div class="row-center-section" @click.stop>
                <el-input-number
                  class="cell-qty-input"
                  v-model="inputValues[node.id]"
                  :min="0"
                  :max="maxOf(node)"
                  size="small"
                  :disabled="!auth.canFill || (activeGroup === 'done' && !auth.isAdmin && !isIndependent)"
                />
                <span v-if="isIndependent" class="cell-pending" :title="`总套数 ${node.plan_qty} − 当前填报 ${inputValues[node.id] ?? node.actual_qty ?? 0}`">
                  待完成 <span class="qty-num">{{ pendingOf(node) }}</span> 套
                </span>
              </div>
              <div class="row-status-section">
                <span class="cell-status status-pill" :style="pillStyle(statusOf(node))">{{ labelOf(node) }}</span>
                <!-- 折叠指示（纯视觉，非按钮）：整行点击即可展开/收起 -->
                <span
                  v-if="!isIndependent"
                  class="fill-row-caret"
                  :class="{ 'is-open': isFillExpanded(node.id) }"
                  aria-hidden="true"
                ></span>
              </div>
              <!-- 明细区（跨满整行）：套信息 + 填报日期 + 按段/异常入口。@click.stop 保证区内操作不触发行折叠 -->
              <div v-if="!isIndependent && isFillExpanded(node.id)" class="fill-row-detail" @click.stop>
                <!-- 套明细（只读） -->
                <el-popover v-if="node.has_set_detail" placement="bottom-start" :width="380" trigger="click">
                  <template #reference>
                    <span class="set-badge set-badge-lite" :title="`只读：本行共 ${node.set_count} 套（填报仍按「计划 N 套 / 实际 M 套」合并填写）`">
                      共 {{ node.set_count }} 套（第1-{{ node.set_count }}套）
                    </span>
                  </template>
                  <div class="set-bubble">
                    <div class="set-bubble-title">本行共 {{ node.set_count }} 套 · 逐套明细（只读）</div>
                    <div v-for="s in setsOf(node)" :key="s.set_seq" class="set-bubble-row">
                      <span class="set-name">第 {{ s.set_seq }} 套</span>
                      <span class="set-bubble-date">计划 {{ s.plan_date }}</span>
                      <span v-if="s.actual_qty_est > 0" class="set-bubble-done">
                        已完成<span v-if="s.derived" class="set-derived">（推定）</span>
                      </span>
                      <span v-else class="set-bubble-todo">未完成</span>
                      <span v-if="s.source === 'backfill'" class="set-src">（推定套号）</span>
                      <span
                        v-if="s.has_open_exception"
                        class="exc-chip"
                        :title="`第 ${s.set_seq} 套存在未关闭异常：${(s.exception_processes || []).join('、') || '—'}`"
                      >⚠️ 第{{ s.set_seq }}套</span>
                    </div>
                    <div class="set-bubble-hint">
                      填报仍为「计划 N 套 / 实际 M 套」合并填写；实际完成按套号升序推定（前 M 套视为完成），
                      故标「（推定）」。本气泡仅作明细查看，不参与任何判定。
                    </div>
                  </div>
                </el-popover>
                <!-- 该行异常 chip 组已移除（2026-10 用户要求）：逐套异常原因改在「⚠️ 异常记录」页签查看 -->
                <!-- 填报日期文字已隐藏（2026-10 用户要求）：当前日期在「更改填报日期」气泡内可见，
                     此处不再重复展示；三个操作按钮整体靠右排列 -->
                <div class="fill-detail-actions">
                <el-popover
                  placement="left-start"
                  :width="260"
                  trigger="click"
                  v-model:visible="datePickerOpen[node.id]"
                >
                  <template #reference>
                    <el-button
                      size="small"
                      :disabled="!auth.canFill || (activeGroup === 'done' && !auth.isAdmin && !isIndependent)"
                      class="rd-btn"
                    >更改填报日期</el-button>
                  </template>
                  <div class="rd-picker-panel">
                    <div class="rd-picker-hint">
                      上次保存：<b>{{ savedDates[node.id] || '无' }}</b>
                    </div>
                    <el-date-picker
                      v-model="reportDates[node.id]"
                      type="date"
                      value-format="YYYY-MM-DD"
                      format="YYYY-MM-DD"
                      :clearable="false"
                      :teleported="false"
                      :disabled-date="isDateDisabled"
                      style="width: 100%;"
                      @change="onDatePicked(node.id, $event)"
                    />
                  </div>
                </el-popover>
                <!-- 按段填报（v7.1 行级化）：按套（计划行）生效；状态胶囊保留在行右侧不动 -->
                <el-button
                  size="small"
                  type="primary"
                  plain
                  class="seg-btn"
                  :disabled="!auth.canFill"
                  @click="openSegmentDialog(node)"
                >🧩 按段填报</el-button>
                <!-- 异常提报（v7.8 行级化）：每套（计划行）直达该行的异常表单，
                     复用「⚠️ 异常提报」页签内的同一个 ExceptionReportTab，不重写任何提报逻辑。
                     该按钮位于 v-if="!isIndependent" 的 .cell-report-date 内 → 独立工序天然不渲染。
                     权限口径与既有页签入口一致（页签本身无限制，仅组件内「提交异常」受 auth.canFill 控制），
                     故此处不加 :disabled，避免无填报权限账号连历史异常都看不到。 -->
                <el-button
                  size="small"
                  type="warning"
                  plain
                  class="exc-btn"
                  @click="openExceptionForNode(node)"
                >⚠️ 异常提报</el-button>
                </div>
              </div>
            </div>
            <!-- 展开更多按钮：超过 PAGE_SIZE 时显示，避免一次性渲染大量 row-card -->
            <div v-if="groupNodes.length > PAGE_SIZE && !showAllFill" class="expand-more">
              <el-button link type="primary" @click="showAllFill = true">
                ⬇ 展开更多（还有 {{ groupNodes.length - PAGE_SIZE }} 条）
              </el-button>
            </div>
            <div v-else-if="groupNodes.length > PAGE_SIZE && showAllFill" class="expand-more">
              <el-button link type="primary" @click="showAllFill = false">
                ⬆ 收起（仅显示前 {{ PAGE_SIZE }} 条）
              </el-button>
            </div>
          </template>
          <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:16px;">
            <el-button @click="innerMode = 'detail'">← 返回详情</el-button>
            <!-- 一键提报仅对 11 道排产工序有意义（批量按行提报计划/日期）；独立工序是单卡累计填报，不渲染 -->
            <el-button
              v-if="!isIndependent"
              type="warning"
              plain
              :disabled="!auth.canFill || groupNodes.length === 0"
              @click="openBatchDialog"
            >
              ⚡ 一键提报（{{ groupNodes.length }}）
            </el-button>
            <el-button type="primary" :disabled="!auth.canFill" @click="save" :loading="saving">💾 保存节点进度</el-button>
          </div>
        </el-tab-pane>
        <!-- ⚠️ 异常记录（2026-11 重构）：本工序全部异常（生效中 / 已超期 / 已关闭）
             → 计数条 + 筛选 + 9 列表格（复用项目级 ExceptionRecordTable，锁定到本工序）；
             提报表单折叠在底部，避免长期占屏。 -->
        <el-tab-pane v-if="!isIndependent" label="⚠️ 异常记录" name="exception">
          <ExceptionRecordTable
            :pid="pid"
            :process-name="processName"
            :refresh-key="excTableRefreshKey"
            @changed="onExceptionChanged"
          />
          <el-collapse v-model="excFormOpen" class="exc-form-collapse">
            <el-collapse-item name="report" title="➕ 提报异常（展开：选择节点 / 套 → 填写表单）">
              <div v-if="detail.nodes.length" class="exc-node-select">
                <div class="exc-node-label">选择节点：</div>
                <el-select v-model="selectedNodeId" placeholder="选择要提报异常的节点" style="width: 100%;">
                  <el-option
                    v-for="n in detail.nodes"
                    :key="n.id"
                    :label="`${n.plan_date} · 计划 ${n.plan_qty} 套 / 实际 ${n.actual_qty} 套`"
                    :value="n.id"
                  />
                </el-select>
              </div>
              <!-- 套级二级选择（2026-10）：仅当选中的节点有套明细时出现；
                   首项「整套/不指定」= 老口径（不写 set_seq），其余项精确到某一套 -->
              <div v-if="selectedNode && selectedNode.has_set_detail" class="exc-node-select">
                <div class="exc-node-label">套：</div>
                <el-select v-model="selectedSetSeq" placeholder="整套 / 不指定" style="width: 100%;">
                  <el-option :value="null" label="整套 / 不指定（默认，按行口径）" />
                  <el-option
                    v-for="s in (selectedNode.sets || [])"
                    :key="s.set_seq"
                    :value="s.set_seq"
                    :label="setOptionLabel(s)"
                  />
                </el-select>
              </div>
              <ExceptionReportTab
                v-if="selectedNodeId"
                :pid="pid"
                :node-id="selectedNodeId"
                :set-seq="selectedSetSeq"
                :set-d0="selectedSetD0"
                @changed="onReportChanged"
              />
              <div v-else class="exc-form-hint">请先在上方选择要提报异常的节点。</div>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>
      </el-tabs>

    </template>

    <!-- 一键提报弹窗（嵌套） -->
    <el-dialog
      v-model="batchDialogVisible"
      title="⚡ 一键提报"
      width="560px"
      :close-on-click-modal="false"
      append-to-body
      @closed="batchSubmitting = false"
    >
      <div class="batch-body">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 16px;"
        >
          本次将对分组「<b>{{ groupLabel }}</b>」下的 <b>{{ eligibleBatchCount }}</b> 条节点执行一键填报。
          填报数量将自动填到该节点的计划数（{{ batchMode === 'today' ? `填报日期统一为今天 ${fmtToday()}` : '填报日期 = 节点原计划日期' }}）。
          <span v-if="batchSkippedCount > 0" style="color:#e53e3e;">
            （另有 {{ batchSkippedCount }} 条无计划日期的节点将被跳过）
          </span>
        </el-alert>

        <!-- 选项 A：按今日日期完成（全员可用） -->
        <div
          class="batch-option"
          :class="{ 'opt-active': batchMode === 'today' }"
          @click="batchMode = 'today'"
        >
          <div class="opt-row">
            <el-radio v-model="batchMode" value="today" :disabled="batchSubmitting">
              <span class="opt-title">⚡ 按今日日期完成</span>
            </el-radio>
          </div>
          <div class="opt-desc">
            将所有节点统一按今天的日期（{{ fmtToday() }}）批量填报实际数。<br/>
            <span style="color:#718096;">📌 注：填报日期晚于计划日期的，仍会处于「逾期」状态——适用场景：当日批量补录。</span>
          </div>
        </div>

        <!-- 选项 B：按计划日期完成（仅管理员） -->
        <div
          class="batch-option"
          :class="[
            { 'opt-active': batchMode === 'plan' },
            { 'opt-disabled': !auth.isAdmin },
          ]"
          @click="auth.isAdmin && !batchSubmitting && (batchMode = 'plan')"
        >
          <div class="opt-row">
            <el-radio v-model="batchMode" value="plan" :disabled="!auth.isAdmin || batchSubmitting">
              <span class="opt-title">📅 按计划日期完成</span>
            </el-radio>
            <el-tag v-if="!auth.isAdmin" size="small" type="warning" effect="dark">🔒 仅管理员</el-tag>
          </div>
          <div class="opt-desc">
            将所有节点按各自原计划的日期批量填报实际数。<br/>
            <span style="color:#718096;">📌 填报后不产生逾期（填报日期 = 节点计划日期）。</span>
          </div>
          <div v-if="!auth.isAdmin" class="opt-disabled-hint">
            普通用户不可使用：避免填报日期与计划日期不一致造成数据失真。
          </div>
        </div>

        <div v-if="eligibleBatchCount === 0" class="batch-empty">
          当前分组没有可执行一键提报的节点。
        </div>
      </div>

      <template #footer>
        <el-button @click="batchDialogVisible = false" :disabled="batchSubmitting">取消</el-button>
        <el-button
          type="primary"
          :disabled="batchSubmitting || !batchMode || eligibleBatchCount === 0"
          :loading="batchSubmitting"
          @click="executeBatchReport"
        >
          {{ batchSubmitting ? '提报中...' : `确认提报（${eligibleBatchCount} 条）` }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 按段填报弹窗（嵌套二级，v7.1 行级化：按套/计划行生效） -->
    <el-dialog
      v-model="segmentDialogVisible"
      :title="segNodeTitle"
      width="560px"
      :close-on-click-modal="false"
      append-to-body
      @closed="onSegmentDialogClosed"
    >
      <div class="seg-body">
        <div class="seg-tip">
          仅记录这一套的分段进度，不影响该工序其他套计划；保存后主页面对应工序卡片显示「部分完成」并预警，
          延期 7 天未整套完成自动转「延期」。
        </div>
        <div class="seg-fields">
          <div class="seg-field">
            <span class="seg-field-label">总段数</span>
            <el-input-number
              v-model="segTotal"
              :min="1"
              :max="99"
              :disabled="segmentSubmitting"
            />
          </div>
          <div class="seg-field">
            <span class="seg-field-label">已完成段数</span>
            <div class="seg-done-readonly">
              {{ segDone }}<span class="seg-done-unit">段</span>
            </div>
          </div>
        </div>
        <!-- 分段进度可视化：一排 total 个小块，点击第 i 块即把已完成段数设为 i（再点当前最后一块回退） -->
        <div class="seg-blocks">
          <div
            v-for="i in segTotal"
            :key="i"
            class="seg-block"
            :class="{ 'seg-block-done': i <= segDone, 'seg-block-disabled': segmentSubmitting }"
            :title="`点击设为已完成 ${i} 段`"
            @click="onPickSegments(i)"
          >{{ i }}</div>
        </div>
        <div class="seg-hint">点击方块选择已完成段数；再次点击最后一块可回退</div>
        <div class="seg-progress-line">
          折算进度：<b>{{ segPct }}%</b>（{{ segDone }}/{{ segTotal }} 段）
        </div>
        <!-- 本行已有按段记录（取消按段提报的前提）：提示当前口径与取消后的影响 -->
        <div v-if="segHasRecord" class="seg-record-hint">
          ⚠️ 本行已保存按段记录（<b>{{ segNodeSavedDone }}/{{ segNodeSavedTotal }} 段</b>）。
          取消按段提报只会清除这条按段进度记录，<b>已填写的完成套数（{{ segNodeActualQty }} 套）与填报日期不会被改动</b>，
          该行状态回落到按完成套数的常规判定。
        </div>
      </div>
      <template #footer>
        <el-button @click="segmentDialogVisible = false" :disabled="segmentSubmitting || segmentCancelling">取消</el-button>
        <!-- 取消按段提报（destructive）：仅当该行已有按段记录时出现；二次确认后清除段进度记录 -->
        <el-button
          v-if="segHasRecord"
          type="danger"
          plain
          :loading="segmentCancelling"
          :disabled="segmentSubmitting"
          @click="cancelSegments"
        >🗑 取消按段提报</el-button>
        <el-button
          type="primary"
          :loading="segmentSubmitting"
          :disabled="segmentCancelling"
          @click="saveSegments"
        >
          {{ segmentSubmitting ? '保存中...' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, onErrorCaptured } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchProcessNodes, saveNodeProgress, saveSegmentProgress, cancelSegmentProgress } from '../api/node'
import { useProjectStore } from '../store/project'
import { useAuthStore } from '../store/auth'
import ExceptionReportTab from './ExceptionReportTab.vue'
import ExceptionRecordTable from './ExceptionRecordTable.vue'

const props = defineProps({
  modelValue: Boolean,
  pid: { type: String, required: true },
  processName: { type: String, default: '' },
  mode: { type: String, default: 'detail' },
  manager: { type: String, default: '' },   // 多负责人 v6.0：仅查看/提报该负责人名下节点
  month: { type: String, default: '' },     // v7.4 排产按月隔离：仅查看/提报该月导入的节点
})
// refresh：仅要求父级刷新总览，不关闭本弹窗（一键提报用）；saved：保存后由父级关闭并刷新
const emit = defineEmits(['update:modelValue', 'saved', 'refresh'])
const store = useProjectStore()
const auth = useAuthStore() // canFill 决定填报/日期是否可编辑（admin 或大区账号；后端已按大区隔离）

/**
 * 错误边界（2026-11 修复「页签内容叠加 / 整块点不动」）：
 * 弹窗内任一子组件在 setup / render 阶段抛错时，Vue 默认会让错误沿 patch 调用栈冒泡，
 * 导致本次渲染整棵树被打断 —— 表现为「pane 已切换但旧内容没被卸载」且整块 UI 失去响应。
 * 这里兜住错误并显式打日志（返回 false 会阻止 Vue 的默认向上抛出，故必须自己 console.error，
 * 以免错误被静默吞掉），保证弹窗其余部分仍然可用。
 *
 * 说明：这只是兜底，不掩盖问题 —— 真正的错误依旧完整打印在控制台，且结构上已经
 * 把「填报内容」收进 el-tab-pane（见模板注释），两者叠加时不可能再出现内容串页签。
 */
onErrorCaptured((err, instance, info) => {
  console.error('[ProcessDetailDialog] 子组件异常已被错误边界拦截：', info, err)
  return false
})

// 填报日期：默认今天，格式 YYYY-MM-DD
function fmtToday() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
// popover 内选择日期后：写回 reportDates 并收起 popover（v-model 已同步，此处幂等安全）
function onDatePicked(nodeId, newVal) {
  reportDates.value[nodeId] = newVal
  datePickerOpen.value[nodeId] = false
}
// 大区账号可回填的窗口天数：与后端 backend/app/routers/nodes.py 的 BACKFILL_DAYS 必须同值
// （前后端各写一份常量、无法共享，任何改动必须两侧同步）。可选区间 = [今天 − BACKFILL_DAYS, 今天]（含今天）。
const BACKFILL_DAYS = 7
// el-date-picker 的 disabled-date：管理员不限；非 admin（大区账号）仅允许 [今天 − BACKFILL_DAYS, 今天]，
// 区间外（含未来日期）置灰不可选 —— 与后端 REPORT_DATE_OUT_OF_RANGE 校验口径一致。
function isDateDisabled(d) {
  if (auth.isAdmin) return false
  const day = new Date(d)
  day.setHours(0, 0, 0, 0)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const earliest = new Date(today)
  earliest.setDate(earliest.getDate() - BACKFILL_DAYS)
  return day < earliest || day > today
}
// 每行独立填报日期（按 node.id 存储）；管理员可改任意历史日期，大区账号可回填近 BACKFILL_DAYS 天（仅本大区）
const reportDates = ref({})
// 原始已保存填报日期（供 popover「上次保存」提示）
const savedDates = ref({})
// 每行 popover 可见状态（按 node.id）
const datePickerOpen = ref({})
// 跨组脏值判定基线：load 时记录每个节点原始 qty 与 report_date
const originalValues = ref({})

const detail = ref(null)
/**
 * 节点索引（2026-10 性能修复）：把「按 id 找节点」从 O(n) 线性查找降为 O(1)。
 *
 * 背景：statusOf / labelOf / excOf 原先各写一次 `detail.nodes.find(x => x.id === node.id)`，
 * 而模板里每个 fill-row 会调用它们约 10 次（excOf 3 次 + hasOpenExc/hasActiveExc 各 2 次
 * 内部又各调一次 excOf + statusOf 2 次 + labelOf 1 次）。默认渲染 20 行 = 每次渲染
 * 200 次 × 60 项响应式 Proxy 遍历 —— 切换分组 / 输入数量时的卡顿主因。
 * 改为一次性建 Map 后，每行查找变成 hash 命中；detail 变化时才重建（computed 缓存）。
 */
const nodeById = computed(() => {
  const map = new Map()
  for (const n of detail.value?.nodes || []) map.set(n.id, n)
  return map
})
const innerMode = ref('detail')
const activeGroup = ref('today')
const inputValues = ref({})
const saving = ref(false)
const selectedNodeId = ref(null)

// 异常记录页签：表格刷新令牌 + 提报表单折叠态
const excTableRefreshKey = ref(0)
const excFormOpen = ref([])

// 异常提报/关闭后触发全局刷新（复用节点保存事件总线）
// 🔴 2026-11 修复：**必须同时重拉本弹窗的 detail**。分组/计划日是按异常口径算出来的
//    （生效中暂停、已关闭按关闭时间重算计划日），关闭一条异常后本工序的节点可能整体
//    换到另一个分组（如「逾期未完成」→「未来计划」）。若只刷全局时间戳、不刷弹窗，
//    用户看到的还是旧分组 → 再点保存提交的分组与后端判定不一致 → 报错（线上反馈：
//    "关掉异常后保存失败"）。重拉后行会出现在正确的分组里，用户接着填即可。
async function onExceptionChanged() {
  store.lastNodeSavedAt = Date.now()          // 预警列表（AlertList）刷新
  store.lastExceptionChangedAt = Date.now()   // 工序卡片刷新「存在异常」标签与预警态
  // 保持当前页签不动，仅刷新数据（load 内部会重建 groups / inputValues / reportDates）
  try {
    await load()
  } catch (e) {
    // load 失败已由 axios 拦截器提示；保留旧数据不影响用户继续查看
  }
}

// 提报成功：除上面的全局刷新外，还要让「异常记录」表格重新拉取（令牌 +1）
function onReportChanged() {
  onExceptionChanged()
  excTableRefreshKey.value += 1
}

// === 异常提报（v7.8 行级化：每套直达） ===
// 复用「⚠️ 异常记录」页签里折叠的同一个 <ExceptionReportTab>：本函数只做三件事 ——
//   1) 把 selectedNodeId 指向被点击的这一套（计划行）；与已选不同则直接覆盖（下拉随之更新）
//   2) 展开提报表单并切到异常记录页签，让用户立刻看到该套的表单
//   3) 重置二级「套」选择为整套/不指定（用户可在下拉里再精确到某一套）
// 说明：2026-11 起 ExceptionReportTab 不再承担历史列表（历史改由 ExceptionRecordTable 展示），
// 因此原先依赖其内部 watch(nodeId) 重新拉取节点的写法已不适用；表单本身无需重建。
// 权限口径：与既有入口完全一致 —— 页签本身无限制，写操作由组件内「提交异常」按钮的 auth.canFill 把关，
// 所以行内入口同样不加 :disabled。
function openExceptionForNode(node) {
  if (!node || node.id == null) return
  // 独立工序（累计完成/累计发运）本就没有异常记录页签，行内按钮也不会渲染；此处再兜底一次
  if (isIndependent.value) return
  selectedNodeId.value = node.id
  // 从行内入口进入时一律按「整套/不指定」起步（用户可在二级下拉里再选具体某一套）
  selectedSetSeq.value = null
  innerMode.value = 'exception'
  excFormOpen.value = ['report']       // 行内入口直达表单：自动展开折叠区
}

// ---- 失败信息紧凑渲染工具（纯函数，放最前，不依赖响应式状态） ----
// 每个错误 code 一条带 emoji 的短摘要
const CODE_FRIENDLY = {
  QTY_EXCEED_PLAN: '⚠️ 数量超计划：节点实际数量不能超过计划数',
  DONE_READONLY: '🔒 已完成分组不可编辑（仅管理员可调整）',
  BAD_REPORT_DATE: '📅 填报日期格式错误（应为 YYYY-MM-DD）',
  REPORT_DATE_OUT_OF_RANGE: '📅 填报日期超出允许范围：仅可回填最近 7 天内的日期（含今天）',
  NODE_NOT_IN_GROUP: '⚠️ 节点与所选分组不匹配',
  UNKNOWN_GROUP: '⚠️ 未知分组',
  // 2026-11：分组口径与展示不一致时的明确提示（异常关闭后计划日重算会把节点移组）
  GROUP_EMPTY: '🔄 当前分组已没有可保存的节点（可能因异常关闭/日期重算移入其它分组），请关闭弹窗重开',
  NO_NODES: '🔄 该工序当月没有可填报的节点，请刷新后重试',
}
// HTML 转义，防 XSS
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

/**
 * 从 axios 失败原因里提取「可读的错误信息 + code」。
 *
 * 2026-11：此前只认 `detail.message`，遇到 500（detail 是字符串 "Internal Server Error"）、
 * 422（detail 是数组）或网络层失败（无 response）时，code 一律退化成 UNKNOWN、文案一律
 * 「请求失败」——线上问题因此完全无法定位。现在按响应形态分类兜底：
 *   - detail 为 {code,message}（业务校验）→ 直接用；
 *   - detail 为字符串（多数 500 / 少数手写 4xx）→ 直接显示该字符串；
 *   - detail 为数组（FastAPI 422 参数校验）→ 拼出 `字段: 原因`；
 *   - 无 response（超时/断网/服务未启动）→ 显示网络层原因；
 *   - 其它 → HTTP status + statusText。
 *
 * @param {any} reason Promise.allSettled 的 rejected reason（axios 错误）
 * @returns {{code: string, message: string, status: number|string}}
 */
function parseErrorReason(reason) {
  const resp = reason?.response
  if (!resp) {
    const netMsg = reason?.code === 'ECONNABORTED'
      ? '请求超时，请重试'
      : (reason?.message || '网络异常（请求未到达服务器）')
    return { code: 'NETWORK', message: netMsg, status: '-' }
  }
  const detail = resp.data?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return { code: detail.code || `HTTP_${resp.status}`, message: detail.message || '请求失败', status: resp.status }
  }
  if (typeof detail === 'string' && detail.trim()) {
    // 500 常见 "Internal Server Error"；也兼容手写的字符串 detail
    return { code: `HTTP_${resp.status}`, message: detail.trim(), status: resp.status }
  }
  if (Array.isArray(detail) && detail.length) {
    const msg = detail
      .map((d) => {
        const field = Array.isArray(d?.loc) ? d.loc.filter((x) => x !== 'body').join('.') : ''
        return field ? `${field}：${d?.msg || '参数不合法'}` : (d?.msg || '参数不合法')
      })
      .join('；')
    return { code: 'VALIDATION', message: msg, status: resp.status }
  }
  return {
    code: `HTTP_${resp.status}`,
    message: resp.statusText || `请求失败（HTTP ${resp.status}）`,
    status: resp.status,
  }
}

// 把每组的失败压缩成一行（去掉【】前缀，保留原始 message）
function shortItem(group, parsed) {
  const label = groupLabelMap[group] || group
  const clean = String(parsed?.message || '请求失败').replace(/^【.+?】/, '')
  return `${label}：${clean}`
}

const groupOptions = computed(() => {
  const all = [
    { label: '🔵 今日待填报', value: 'today' },
    { label: '🔴 逾期未完成', value: 'overdue' },
    { label: '⚪ 未来计划', value: 'future' },
    { label: '🟢 已完成', value: 'done' },
  ]
  // 独立工序（累计完成总数 / 累计发运总数）：无日期语义，
  // 后端分组里 overdue/future 恒为空，仅保留 today/done
  if (isIndependent.value) return all.filter(g => g.value === 'today' || g.value === 'done')
  return all
})
const groupLabelMap = { today: '今日待填报', overdue: '逾期未完成', future: '未来计划', done: '已完成' }
const groupLabel = computed(() => groupLabelMap[activeGroup.value] || activeGroup.value)
const groupNodes = computed(() => detail.value?.groups?.[activeGroup.value] || [])

// 填报行折叠（2026-10 界面优化）
// 收起态只保留：计划日(+原计划日) / 计划套数 / 数量输入 / 状态胶囊（+有异常时的 ⚠️ 小标）
// 展开态（fill-row-detail）追加：套明细、异常 chip、填报日期+更改、按段填报、异常提报
// 按 node.id 记忆展开状态；切换分组/刷新数据不丢失。
const fillExpanded = ref({})
function isFillExpanded(id) {
  return !!fillExpanded.value[id]
}
function toggleFillRow(id) {
  fillExpanded.value = { ...fillExpanded.value, [id]: !fillExpanded.value[id] }
}

// 分页展开：节点数超过 PAGE_SIZE 时默认只渲染前 PAGE_SIZE 条，避免大量 row-card 一次性渲染导致卡顿
const PAGE_SIZE = 20
const showAllFill = ref(false)
const showAllDetail = ref(false)
const displayedGroupNodes = computed(() =>
  showAllFill.value || groupNodes.value.length <= PAGE_SIZE
    ? groupNodes.value
    : groupNodes.value.slice(0, PAGE_SIZE)
)
const displayedDetailNodes = computed(() =>
  showAllDetail.value || (detail.value?.nodes?.length || 0) <= PAGE_SIZE
    ? (detail.value?.nodes || [])
    : (detail.value?.nodes || []).slice(0, PAGE_SIZE)
)
// 切换分组时重置展开状态
watch(activeGroup, () => { showAllFill.value = false })

// 独立工序（累计完成总数/累计发运总数）：无日期语义 → 隐藏日期列与异常提报页签
const isIndependent = computed(() => !!detail.value?.is_independent)

const statusColors = {
  done: '#38a169', pending: '#718096', in_progress: '#3182ce', warning: '#3182ce', overdue: '#e53e3e',
  waiting_material: '#a0aec0',
  exception_paused: '#a0aec0',   // ⏸ 异常暂停（灰，与待下料同视觉层级）
  exception: '#dd6b20',          // 🟠 异常（第 4 态：本行自身有生效中异常）
  matches_dispatch: '#38a169',
}
const statusBgs = {
  done: '#f0fff4', pending: '#f7fafc', in_progress: '#ebf8ff', warning: '#ebf8ff', overdue: '#fff5f5',
  waiting_material: '#f7fafc',
  exception_paused: '#f7fafc',
  exception: '#fffaf0',
  matches_dispatch: '#f0fff4',
}
const colorOf = (s) => statusColors[s] || '#718096'
const pillStyle = (s) => ({ background: statusBgs[s] || '#f7fafc', color: statusColors[s] || '#718096' })
/**
 * 该行是否已「按套完成」（2026-10 用户口径）：
 * 实际套数 ≥ 计划套数（且计划数 > 0）。
 * 按段提报与按套提报是两条独立路径 —— 按套报满即代表该套工序完成，
 * 此时界面不再显示「已完成 n/m 段」（数据仍在 node_segment_progress，不删除）。
 */
const isRowSetDone = (row) => {
  const plan = Number(row?.plan_qty || 0)
  const actual = Number(row?.actual_qty || 0)
  return plan > 0 && actual >= plan
}

const statusOf = (node) => nodeById.value.get(node.id)?.status || 'pending'
const labelOf = (node) => nodeById.value.get(node.id)?.label || '—'
// === 异常暂停（2026-10）：所属套标识 ===
// 「同一套」= 后端的 set_date（该行所属套的「下料计划日」，非套号）；
// has_open_exception / exception_processes / exception_paused 均由后端 enrich_rows 给出，
// 前端不做任何推断，仅按字段渲染（保证与总览/排名同一口径）。
const excOf = (node) => nodeById.value.get(node.id) || {}
// 原排产计划日（重算前的值）：后端 groups / nodes 行均带 plan_date_plan；
// 未重算的行它与 plan_date 相等 → 不显示「原 X」删除线（避免误显示）。
const origPlanOf = (node) => node?.plan_date_plan || ''
const hasOpenExc = (node) => !!excOf(node).has_open_exception
const hasActiveExc = (node) => !!excOf(node).has_active_exception
// 「哪一套」标签文案：
//   ① 有生效中异常（has_active_exception）→ 显示异常工序名（+ 该套下料计划日）
//   ② 未关闭但已全部到期失效（has_open_exception=true, has_active_exception=false）
//      → 「⚠️ 异常已超期」：暂停已失效、已恢复逾期判定，不能再显示成"正在暂停"
//   ③ 存量项目无时长数据（无法反推所属套）→ 只显示异常工序名，不显示误导性的「下料 —」
function excChipText(procs, setDate, active = true) {
  if (!active) return '⚠️ 异常已超期'
  const name = (procs || []).join('、') || '存在'
  return setDate ? `⚠️ ${name}异常 · 下料 ${setDate}` : `⚠️ ${name}异常`
}
// 本工序「有**生效中**异常」的套汇总（节点详情页顶部提示条用）：按 set_date 去重
// ⚠️ 与「未关闭」区分：已过计划关闭日的异常暂停已失效，不计入本提示条。
const activeExcSets = computed(() => {
  const map = new Map()
  for (const r of detail.value?.nodes || []) {
    if (!r.has_active_exception) continue
    const key = r.set_date || `#${r.id}`
    if (!map.has(key)) map.set(key, { key, set_date: r.set_date, processes: new Set() })
    const item = map.get(key)
    ;(r.active_exception_processes || []).forEach((p) => p && item.processes.add(p))
  }
  return [...map.values()].map((x) => ({
    key: x.key,
    label: x.set_date
      ? `下料 ${x.set_date} 套${x.processes.size ? `（${[...x.processes].join('、')}）` : ''}`
      : `该套（${[...x.processes].join('、') || '—'}）`,
  }))
})
// 本工序「已超计划关闭日」的异常条数（同一套的多行只计一次：按 set_date 取该套的计数）
const expiredExcCount = computed(() => {
  const perSet = new Map()
  for (const r of detail.value?.nodes || []) {
    const key = r.set_date || `#${r.id}`
    const n = Number(r.exception_expired_count || 0)
    if (!perSet.has(key) || n > perSet.get(key)) perSet.set(key, n)
  }
  let total = 0
  perSet.forEach((v) => { total += v })
  return total
})

// === 「第 N 套」展示（2026-10，只读） ===
// 后端在 nodes 行上挂 sets[]/has_set_detail/set_count/set_detail_state；groups 行只带
// 轻量标记（不带 sets）→ 填报表单按 id 回查 nodes 取明细，避免表单体积翻倍。
// 判定相关字段（status/label/逾期/KPI）完全不受本层影响，前端也不做任何推断。
const expandedSetRows = ref({})          // { [nodeId]: true } 节点详情里的逐套子行展开态
function toggleSetRows(nodeId) {
  if (nodeId == null) return
  expandedSetRows.value = {
    ...expandedSetRows.value,
    [nodeId]: !expandedSetRows.value[nodeId],
  }
}
// 按 id 回查 nodes 行（groups 行与 nodes 行同一节点）
function nodeRowOf(node) {
  if (!node) return null
  return (detail.value?.nodes || []).find((x) => x.id === node.id) || null
}
// 该行的逐套明细（无套明细 → 空数组，模板里的 v-for 自然不渲染任何东西）
function setsOf(node) {
  return nodeRowOf(node)?.sets || []
}
// 该行「有异常」的套（填报 tab 的 ⚠️ 第N套 chip 数据源；含已超期，文案由模板区分）
function excSetsOf(node) {
  return setsOf(node).filter((s) => s.has_open_exception)
}
// 异常提报 tab 的「套」选项文案：套号 + 该套生效计划日 + 暂停态提示
function setOptionLabel(s) {
  const base = `第 ${s.set_seq} 套 · 计划 ${s.plan_date}`
  if (s.exception_paused) return `${base} · ⏸ 异常暂停`
  if (s.actual_qty_est > 0) return `${base} · 已完成${s.derived ? '（推定）' : ''}`
  return base
}
// 异常提报 tab：当前选中的节点行（含 sets[]，用于二级「套」下拉）
const selectedNode = computed(() => {
  if (selectedNodeId.value == null) return null
  return (detail.value?.nodes || []).find((x) => x.id === selectedNodeId.value) || null
})
// 选中套的套号（null = 整套/不指定 → 老口径，后端写 NULL）
const selectedSetSeq = ref(null)
// 选中套的下料计划日快照（提交时随 set_seq 一起写入，供判定层/展示层反推）
const selectedSetD0 = computed(() => {
  if (selectedSetSeq.value == null) return null
  const hit = (selectedNode.value?.sets || []).find((s) => s.set_seq === selectedSetSeq.value)
  return hit?.d0 || null
})
// 切换节点后重置「套」选择（避免把上一节点的套号带过去）
watch(selectedNodeId, () => { selectedSetSeq.value = null })
// 分组差异化上限：done=当前值只能减；today/overdue/future=计划数；
// 独立工序不限上限（累计指标可自由填报，后端同样不设上限）
const maxOf = (node) => {
  if (isIndependent.value) return undefined
  if (activeGroup.value === 'done') return node.actual_qty
  if (activeGroup.value === 'overdue' || activeGroup.value === 'future') return node.plan_qty
  return node.plan_qty   // today：上限计划数（后端仅做数量超计划校验，不再做前序联动）
}
// 独立工序：本次输入后剩余套数（实时反映用户输入）—— 仅用于非独立（11 道排产）
const pendingOf = (node) => {
  if (!isIndependent.value) return null
  const total = Number(node.plan_qty) || 0
  const cur = Number(inputValues.value[node.id] ?? node.actual_qty ?? 0)
  return Math.max(0, total - cur)
}

// 独立工序：合同总数（单一数据源 = 项目主表 contract_count；为空时回退合同占位行 plan_qty）
const independentContract = computed(() => {
  if (!isIndependent.value || !detail.value) return 0
  const cc = detail.value.contract_count
  if (cc !== null && cc !== undefined && cc !== '') return Number(cc) || 0
  const placeholder = detail.value.nodes.find((n) => !n.plan_date)
  return Number(placeholder?.plan_qty) || 0
})
// 独立工序：累计已填报（所有行 actual_qty 之和）
const independentFilled = computed(() => {
  if (!detail.value) return 0
  return detail.value.nodes.reduce((s, n) => s + (Number(n.actual_qty) || 0), 0)
})
// 独立工序：剩余可填报
const independentRemaining = computed(() => {
  return Math.max(0, independentContract.value - independentFilled.value)
})
// 独立工序：本次输入后剩余（取 today tab 占位行的 inputValue，未填视为 0）
const independentRemainingAfter = computed(() => {
  const delta = Number(
    groupNodes.value[0] ? (inputValues.value[groupNodes.value[0].id] ?? 0) : 0
  ) || 0
  return Math.max(0, independentRemaining.value - delta)
})
// 独立工序：所有日报行（plan_date 非空）最新填报日期 —— 节点详情「最新完成日期」用
const latestIndependentDate = computed(() => {
  if (!isIndependent.value || !detail.value) return null
  const dates = detail.value.nodes
    .filter((n) => n.plan_date && n.report_date)
    .map((n) => n.report_date)
    .sort()
  return dates.length ? dates[dates.length - 1] : null
})
// 独立工序：节点详情汇总卡状态（合同已完成 → done；否则 in_progress；无日期偏差）
const independentStatus = computed(() => {
  const done = independentContract.value > 0 && independentFilled.value >= independentContract.value
  return {
    status: done ? 'done' : 'in_progress',
    label: done ? '🟢 已完成' : '🔵 进行中',
  }
})

// 模块级 detail 缓存（2026-10 性能优化）
// 背景：生产实测 detail 接口 260~350ms（CloudRun 缩容偶发冷启动可达 500ms+），
// 而用户真实使用是「来回切换工序/反复打开同一弹窗」——每次都重新请求，0.3~0.5s 等待
// 就是反馈里的"切换卡顿"。缓存 30s 内的同一 (项目/工序/负责人/月份) 结果，
// 让「切走再切回」瞬开；保存 / 异常变更 / 手动强制刷新一律走 force 绕过缓存。
const DETAIL_CACHE = new Map()          // key -> { data, ts }
const DETAIL_CACHE_TTL = 30_000

function detailCacheKey() {
  return [props.pid, props.processName, props.manager || '', props.month || ''].join('|')
}

/**
 * 让当前弹窗的 detail 缓存失效。
 * 🔴 必须在实际**改变数据**之后调用（保存进度 / 按段 / 异常变更 / 手动完成…），
 * 否则用户「改完关掉、30 秒内再打开」会命中旧缓存，看到改动前的数据
 * （2026-10 线上反馈：已完成分组里减套数后重开，行还挂在「已完成」）。
 */
function invalidateDetailCache() {
  DETAIL_CACHE.delete(detailCacheKey())
}

async function load({ force = false } = {}) {
  if (!props.processName) return
  const cacheKey = detailCacheKey()
  const hit = DETAIL_CACHE.get(cacheKey)
  if (!force && hit && Date.now() - hit.ts < DETAIL_CACHE_TTL) {
    detail.value = hit.data
  } else {
    // v7.4：带 month 时只取「该月导入的行 ∪ 未标注月行」，与详情页总览同一月份口径
    const params = {}
    if (props.manager) params.manager = props.manager
    if (props.month) params.month = props.month
    detail.value = await fetchProcessNodes(props.pid, props.processName, params)
    DETAIL_CACHE.set(cacheKey, { data: detail.value, ts: Date.now() })
  }
  inputValues.value = {}
  reportDates.value = {}
  Object.keys(detail.value.groups).forEach((g) => {
    detail.value.groups[g].forEach((n) => {
      inputValues.value[n.id] = n.actual_qty
      // 2026-10 性能：原为 groups 内每行 find 一次 nodes（O(n²)，60 套 ≈ 3600 次比较），
      // 改为 nodeById 索引 O(1)；nodeById 依赖 detail，赋值后首次访问自动重建。
      const nd = nodeById.value.get(n.id)
      const saved = nd?.report_date || ''
      reportDates.value[n.id] = (n.actual_qty || 0) > 0
        ? (saved || fmtToday())   // 已填写：保留上次保存的实际填报日期
        : fmtToday()              // 未填写（含未开始）：强制当天
      savedDates.value[n.id] = saved || ''   // 记录原始已保存日期，供 popover 提示
    })
  })
  // 加载时记下每个节点的原始 qty 与 report_date，作为脏值判定基线
  originalValues.value = {}
  Object.keys(detail.value.groups).forEach((g) => {
    detail.value.groups[g].forEach((n) => {
      originalValues.value[n.id] = {
        qty: n.actual_qty,
        report_date: reportDates.value[n.id],
      }
    })
  })
}

async function save() {
  saving.value = true
  try {
    const dirtyByGroup = { today: [], overdue: [], future: [], done: [] }
    Object.keys(detail.value.groups).forEach((g) => {
      detail.value.groups[g].forEach((n) => {
        const o = originalValues.value[n.id] || { qty: 0, report_date: fmtToday() }
        const curQty = inputValues.value[n.id] ?? 0
        const curRd = reportDates.value[n.id] || fmtToday()
        if (curQty !== o.qty || curRd !== o.report_date) {
          dirtyByGroup[g].push({ node_id: n.id, qty: curQty, report_date: curRd })
        }
      })
    })
    const groupsToSave = Object.entries(dirtyByGroup).filter(([, arr]) => arr.length)
    if (!groupsToSave.length) {
      ElMessage.info('当前没有可保存的修改')
      return
    }
    // 并发提交；任一组失败也汇总已成功的部分，避免无提示
    const settled = await Promise.allSettled(
      groupsToSave.map(([g, values]) =>
        saveNodeProgress(props.pid, props.processName, {
          group: g,
          values,
          manager: props.manager || undefined,
          month: props.month || undefined,   // v7.4：后端按同一月份口径校验
        }),
      ),
    )
    const ok = settled.filter((r) => r.status === 'fulfilled')
    const bad = settled.filter((r) => r.status === 'rejected')
    const totalSaved = ok.reduce((s, r) => s + ((r.value?.saved) ?? 0), 0)
    if (bad.length) {
      // 仅取失败（rejected）分组，按 code 聚合压缩展示。
      // parseErrorReason 负责把 500 字符串 detail / 422 数组 / 网络失败 都翻译成可读文案，
      // 不再统一退化成「UNKNOWN / 请求失败」（那样线上问题无从定位）。
      const items = groupsToSave
        .map(([g], i) => ({ g, result: settled[i] }))
        .filter(({ result }) => result?.status === 'rejected')
        .map(({ g, result }) => {
          const parsed = parseErrorReason(result.reason)
          return { group: g, code: parsed.code, short: shortItem(g, parsed) }
        })
      const buckets = {}
      items.forEach(({ code, short }) => {
        const key = code || 'UNKNOWN'
        ;(buckets[key] = buckets[key] || []).push(short)
      })
      const body = Object.entries(buckets)
        .map(([code, lines]) => {
          const headline = CODE_FRIENDLY[code] || `⚠️ ${esc(code)}`
          const detailLines = lines
            .map((s) => `<div style="margin-left:14px; color:#4a5568; font-size:13px; line-height:1.7;">• ${esc(s)}</div>`)
            .join('')
          return `<div style="margin-top:6px;"><b>${esc(headline)}</b>${detailLines}</div>`
        })
        .join('')
      ElMessage.error({
        dangerouslyUseHTMLString: true,
        message: `<div style="line-height:1.6; max-width:540px;"><b>保存失败（${bad.length} / ${groupsToSave.length} 个分组）</b>${body}</div>`,
        duration: 6000,
        showClose: true,
      })
      // 分组口径不一致类失败（节点已被异常/日期重算移出当前分组）：立刻重拉明细，
      // 让行出现在它现在的分组里，用户不用关弹窗就能接着填，也避免重复踩同一个错。
      if (items.some((it) => it.code === 'NODE_NOT_IN_GROUP' || it.code === 'GROUP_EMPTY')) {
        try { await load({ force: true }) } catch (e) { /* 已由拦截器提示 */ }
      }
    }
    if (totalSaved > 0) {
      ElMessage.success(`已保存 ${totalSaved} 条节点进度`)
    }
    // 独立工序（累计完成 / 累计发运）：保存后**不关闭弹窗** —— 重新拉取明细，让用户在
    // 「今日待填报」看到待完成数下降，并能切到「已完成」核对刚生成的日期记录（累计填报天然需要「填→看」闭环）；
    // 父级工序卡片通过 refresh 事件同步刷新。
    // 11 道排产工序保持既有行为：saved → 父组件关闭弹窗 + 刷新。
    if (ok.length) {
      // ⚠️ 排产工序保存后父组件会关掉弹窗；这里必须让缓存失效，
      //    否则 30 秒内重开同一工序会命中旧缓存（改动前的分组/数量）。
      invalidateDetailCache()
      if (isIndependent.value) {
        await load({ force: true })
        emit('refresh')
      } else {
        emit('saved')        // 父组件关闭弹窗 + 刷新
      }
    }
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.modelValue, props.processName, props.mode],
  ([open]) => {
    if (open) {
      innerMode.value = props.mode || 'detail'
      activeGroup.value = 'today'
      selectedNodeId.value = null
      selectedSetSeq.value = null      // 「套」二级选择随节点一起重置
      expandedSetRows.value = {}       // 逐套子行默认折叠
      excFormOpen.value = []           // 提报表单默认折叠（行内入口会再展开）
      excTableRefreshKey.value += 1    // 重新打开时强制刷新「异常记录」表格
      // 不在此重置 reportDates：load() 内部已有 重置+按节点回填 逻辑，避免双重处理
      originalValues.value = {} // 脏值基线同样由 load() 重新初始化
      load()
    }
  },
)

// === 一键提报（弹窗态 + 执行） ===
const batchDialogVisible = ref(false)
// 'today' = 统一填报今天；'plan' = 填报日期 = 节点原计划日期（仅管理员可用）
const batchMode = ref('today')
const batchSubmitting = ref(false)
// 一键提报只对「有计划日期」的节点生效；独立工序占位行无 plan_date，会被跳过
const eligibleBatchNodes = computed(() => groupNodes.value.filter((n) => !!n.plan_date))
const eligibleBatchCount = computed(() => eligibleBatchNodes.value.length)
const batchSkippedCount = computed(
  () => Math.max(0, groupNodes.value.length - eligibleBatchCount.value),
)

// ⚠️ Element Plus 的 ElMessage.xxx(options) 只接受「单个 options 对象」：
// 第二参数会被当成 Vue 的 appContext，导致 createComponentInstance 内
// Object.create(appContext.provides) 收到 undefined → 抛
// "Object prototype may only be an Object or null: undefined"。
// 这里统一走单参对象写法，并对提示层做兜底，避免它打断后续 UI / 数据更新。
function safeToast(type, options) {
  try {
    ;(ElMessage[type] || ElMessage)(options)
  } catch (err) {
    console.warn('[ProcessDetailDialog] 消息提示渲染失败：', err)
  }
}

function openBatchDialog() {
  if (groupNodes.value.length === 0) return
  // 默认选中「按今日日期」（全员可用）；若分组全无 plan_date 则禁用确认按钮（eligibleCount=0）
  batchMode.value = 'today'
  batchSubmitting.value = false
  batchDialogVisible.value = true
}

async function executeBatchReport() {
  if (!batchMode.value || eligibleBatchCount.value === 0) return
  batchSubmitting.value = true
  try {
    const today = fmtToday()
    const usePlanDate = batchMode.value === 'plan'
    const values = eligibleBatchNodes.value.map((n) => ({
      node_id: n.id,
      qty: Number(n.plan_qty) || 0,
      report_date: usePlanDate ? n.plan_date : today,
    }))
    // 复用现有批量保存接口：单个分组一次性提交；partial_ok=部分成功模式
    // （后端校验仅剩分组归属 / 数量超计划等；前序联动已于 2026-10-16 停用）
    const res = await saveNodeProgress(props.pid, props.processName, {
      group: activeGroup.value,
      values,
      manager: props.manager || undefined,
      month: props.month || undefined,   // v7.4：后端按同一月份口径校验
      partial_ok: true,
    })
    const saved = res?.saved ?? values.length
    const dateLabel = usePlanDate ? '按各节点原计划日期' : today

    // 先关弹窗 + 刷新数据，最后才弹提示：保证提示层即使出异常也不影响 UI 与数据
    batchDialogVisible.value = false
    await load({ force: true })        // 本弹窗内节点列表局部刷新（弹窗保持打开，便于继续操作）
    emit('refresh')     // 父级总览（工序卡片 / 时间轴 / 排名）同步刷新
    safeToast('success', {
      dangerouslyUseHTMLString: true,
      message: `<div style="line-height:1.6; max-width:540px;"><b>✅ 一键提报完成：成功提交 ${saved} 条（填报日期：${esc(dateLabel)}）</b>${
        batchSkippedCount.value > 0 ? `<div style="margin-top:2px; color:#718096; font-size:13px;">另跳过 ${batchSkippedCount.value} 条无计划日期节点</div>` : ''
      }</div>`,
      duration: 8000,
      showClose: true,
    })
  } catch (e) {
    const detail = e?.response?.data?.detail
    const code = detail && typeof detail === 'object' ? detail.code : null
    const msg = detail?.message || e?.message || '一键提报失败'
    const headline = CODE_FRIENDLY[code] || `⚠️ 一键提报失败${code ? `（${code}）` : ''}`
    safeToast('error', {
      dangerouslyUseHTMLString: true,
      message: `<div style="line-height:1.6; max-width:520px;"><b>${esc(headline)}</b><div style="margin-top:4px; color:#4a5568; font-size:13px;">${esc(msg)}</div></div>`,
      duration: 6000,
      showClose: true,
    })
  } finally {
    batchSubmitting.value = false
  }
}

// === 按段填报（嵌套二级弹窗，v7.1 行级化：按套/计划行生效） ===
const segmentDialogVisible = ref(false)
const segmentSubmitting = ref(false)
const segmentCancelling = ref(false)   // 「取消按段提报」进行中（与保存互斥，防重复提交）
// 当前填报的节点（计划行）id；总段数/已完成段数预填该行已保存值，无记录默认 5/0
const segNodeId = ref(null)
const segTotal = ref(5)
const segDone = ref(0)
// 当前节点行（nodes 行含 segment 字段；回退 groups 行，两处后端均已带段字段）
const segNode = computed(() => {
  if (segNodeId.value == null) return null
  return (detail.value?.nodes || []).find((n) => n.id === segNodeId.value)
    || (detail.value?.groups?.[activeGroup.value] || []).find((n) => n.id === segNodeId.value)
    || null
})
const segNodeTitle = computed(() => {
  const n = segNode.value
  return n
    ? `🧩 按段填报：${props.processName} · ${n.plan_date}（${n.plan_qty} 套）`
    : `🧩 按段填报：${props.processName}`
})
// === 「取消按段提报」相关（2026-11） ===
// 该行是否**已存在**按段记录：segment_total 非 null 即库里已有 node_segment_progress 行
// （后端 enrich_rows 对无记录的函数返回 None → 前端据此决定是否显示取消按钮）
const segHasRecord = computed(() => segNode.value?.segment_total != null)
// 库里已保存的段进度（提示文案用；与弹窗内可编辑的 segTotal/segDone 区分）
const segNodeSavedTotal = computed(() => Number(segNode.value?.segment_total ?? 0))
const segNodeSavedDone = computed(() => Number(segNode.value?.segment_done ?? 0))
// 该行已填写的完成套数（取消按段后**不会**被改动，提示文案里明示）
const segNodeActualQty = computed(() => Number(segNode.value?.actual_qty ?? 0))
// 折算进度（仅弹窗内展示，不参与任何主进度计算）
const segPct = computed(() => {
  const t = Number(segTotal.value) || 0
  const d = Number(segDone.value) || 0
  return t > 0 ? Math.round((d / t) * 100) : 0
})

// 点击第 i 个方块 → 已完成段数 = i；再次点击「当前最后一块已完成」→ 回退 1 段（i=1 时归 0）
function onPickSegments(i) {
  if (segmentSubmitting.value || segmentCancelling.value) return
  const n = Number(i)
  if (!Number.isFinite(n) || n < 1 || n > Number(segTotal.value)) return
  segDone.value = n === Number(segDone.value) ? n - 1 : n
}

// 总段数调小后自动夹取已完成段数（原实现依赖 el-input-number 的 :max，去掉步进器后需显式兜底）
watch(segTotal, (t) => {
  const total = Number(t) || 0
  if (Number(segDone.value) > total) segDone.value = total
})

function openSegmentDialog(node) {
  if (!node || node.id == null) return
  segNodeId.value = node.id
  // 预填该行已保存段进度（无记录默认 总段数=5、已完成=0）
  segTotal.value = node.segment_total ?? 5
  segDone.value = Math.min(node.segment_done ?? 0, segTotal.value)
  segmentSubmitting.value = false
  segmentCancelling.value = false
  segmentDialogVisible.value = true
}

// 弹窗关闭：复位两个提交态（避免上次的 loading 残留到下次打开）
function onSegmentDialogClosed() {
  segmentSubmitting.value = false
  segmentCancelling.value = false
}

/**
 * 取消按段提报（destructive）。
 *
 * 语义：
 *  1) 删除该 node_plan_id 的 node_segment_progress 记录（后端 DELETE）；
 *  2) actual_qty / report_date **不动** —— 已完成的套数是既成事实，
 *     只是该行不再按段展示、状态回落到按 actual_qty 的常规判定；
 *  3) 必须二次确认，文案明确「仅清除按段进度记录，不改动已填写的完成套数」；
 *  4) 该按钮仅在已有按段记录时显示（模板 v-if="segHasRecord"）。
 */
async function cancelSegments() {
  if (segNodeId.value == null || segmentCancelling.value || segmentSubmitting.value) return
  const n = segNode.value
  const dateLabel = n?.plan_date || '该计划行'
  const qtyLabel = segNodeActualQty.value
  try {
    await ElMessageBox.confirm(
      `<div style="line-height:1.7;">
        确认取消 <b>${esc(dateLabel)}</b> 这一行的按段提报吗？
        <div style="margin-top:6px; color:#4a5568; font-size:13px;">
          仅清除<b>按段进度记录</b>（当前 ${segNodeSavedDone.value}/${segNodeSavedTotal.value} 段），
          <b>不改动已填写的完成套数</b>（${esc(String(qtyLabel))} 套）与填报日期。<br/>
          取消后该行回到「整行填报」模式，状态按完成套数常规判定。
        </div>
      </div>`,
      '🗑 取消按段提报',
      {
        dangerouslyUseHTMLString: true,
        type: 'warning',
        confirmButtonText: '确认取消按段提报',
        cancelButtonText: '再想想',
        confirmButtonClass: 'el-button--danger',
        closeOnClickModal: false,
      },
    )
  } catch {
    return   // 用户取消（ElMessageBox 拒绝 = 取消操作）
  }
  segmentCancelling.value = true
  try {
    const res = await cancelSegmentProgress(props.pid, props.processName, segNodeId.value)
    const deleted = Number(res?.deleted ?? 0)
    segmentDialogVisible.value = false
    // ⚠️ ElMessage 只传单个参数（传第二参会崩）
    ElMessage.success(deleted > 0 ? '✅ 已取消按段提报，该行回到整行填报' : '该行没有按段记录，无需取消')
    await load({ force: true })      // 刷新详情（segment 字段消失 → 行不再显示「已完成 k/N 段」）
    emit('refresh')   // 父级总览（工序卡片标签 / 进度）同步刷新
  } catch (e) {
    const errDetail = e?.response?.data?.detail
    const code = errDetail && typeof errDetail === 'object' ? errDetail.code : null
    const msg = errDetail?.message || e?.message || '取消按段提报失败'
    const headline = code === 'NODE_MISMATCH' || code === 'NODE_NOT_FOUND' ? '⚠️ 节点归属校验未通过'
      : '⚠️ 取消按段提报失败'
    safeToast('error', {
      dangerouslyUseHTMLString: true,
      message: `<div style="line-height:1.6; max-width:520px;"><b>${esc(headline)}</b><div style="margin-top:4px; color:#4a5568; font-size:13px;">${esc(msg)}</div></div>`,
      duration: 6000,
      showClose: true,
    })
  } finally {
    segmentCancelling.value = false
  }
}

async function saveSegments() {
  if (segNodeId.value == null) return
  segmentSubmitting.value = true
  try {
    await saveSegmentProgress(props.pid, props.processName, {
      node_id: segNodeId.value,
      segment_total: segTotal.value,
      segment_done: segDone.value,
    })
    // ⚠️ ElMessage 只传单个参数（传第二参会崩）
    segmentDialogVisible.value = false
    ElMessage.success('✅ 按段填报已保存')
    await load({ force: true })      // 刷新详情（各行 segment 回显）
    emit('refresh')   // 父级总览（工序卡片「部分完成/预警/延期」标签）同步刷新
  } catch (e) {
    const errDetail = e?.response?.data?.detail
    const code = errDetail && typeof errDetail === 'object' ? errDetail.code : null
    const msg = errDetail?.message || e?.message || '按段填报保存失败'
    const headline = code === 'SEGMENT_INVALID' ? '⚠️ 段数校验未通过'
      : code === 'NODE_MISMATCH' || code === 'NODE_NOT_FOUND' ? '⚠️ 节点归属校验未通过'
      : '⚠️ 按段填报保存失败'
    safeToast('error', {
      dangerouslyUseHTMLString: true,
      message: `<div style="line-height:1.6; max-width:520px;"><b>${esc(headline)}</b><div style="margin-top:4px; color:#4a5568; font-size:13px;">${esc(msg)}</div></div>`,
      duration: 6000,
      showClose: true,
    })
  } finally {
    segmentSubmitting.value = false
  }
}
</script>

<style scoped>
.empty-hint { color: #64748b; font-size: 13px; padding: 12px 0; }
.exc-node-select { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.exc-node-label { font-size: 13px; color: #1a365d; font-weight: 600; white-space: nowrap; }

/* 独立工序·今日待填报：单卡增量输入布局（充足留白） */
.fill-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: box-shadow .15s;
}
.fill-card:hover { box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08); }
.fill-card-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1;
  min-width: 0;
}
.fill-card-label {
  font-size: 14px;
  font-weight: 600;
  color: #1a365d;
  white-space: nowrap;
}
.fill-card-input { width: 160px; }
.fill-card-input :deep(.el-input-number__decrease),
.fill-card-input :deep(.el-input-number__increase) { width: 32px; }
.fill-card-input :deep(.el-input__inner) { text-align: center; font-variant-numeric: tabular-nums; font-size: 15px; }
.fill-card-unit { color: #718096; font-size: 13px; }
.fill-card-pending {
  font-size: 14px;
  color: #4a5568;
  white-space: nowrap;
  padding-left: 14px;
  border-left: 1px solid #e2e8f0;
  margin-left: 4px;
}
.fill-card-pending .qty-num { color: #e53e3e; font-size: 16px; padding: 0 2px; }
.fill-card-right { display: flex; align-items: center; }

/* 独立工序·已完成：每条记录一张卡（按日期降序） */
.record-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 18px 24px;
  margin-bottom: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: box-shadow .15s;
}
.record-card:hover { box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08); }
.record-card-left {
  display: flex;
  align-items: center;
  gap: 20px;
  flex: 1;
  min-width: 0;
}
.record-card-date {
  font-size: 14px;
  font-weight: 600;
  color: #1a365d;
  font-variant-numeric: tabular-nums;
  padding: 4px 12px;
  background: #ebf8ff;
  border-radius: 6px;
  white-space: nowrap;
}
.record-card-qty {
  font-size: 14px;
  color: #4a5568;
  white-space: nowrap;
}
.record-card-qty .qty-num { color: #38a169; font-size: 16px; padding: 0 2px; }
.record-card-right { display: flex; align-items: center; }

/* 填报进度行：色条 / 左（日期+套数）/ 中（输入+待完成/已填报）/ 报告日期（非独立）/ 1fr 弹性空间 / 状态（最右） */
.row-grid {
  display: grid;
  /* 4 列：色条 / 左信息(日期+套数+异常小标) / 数量输入 / 状态+折叠三角（1fr → 靠最右） */
  grid-template-columns: 6px auto auto 1fr;
  align-items: center;
  gap: 14px;
  padding: 12px 18px;
}
.row-left-section { display: flex; align-items: baseline; gap: 14px; white-space: nowrap; }
.row-center-section { display: flex; align-items: center; gap: 12px; min-width: 0; }
.row-status-section { display: flex; align-items: center; justify-self: end; }

/* === 填报行折叠（2026-10 界面优化） ===
   主行：色条 / 日期+套数(+异常小标) / 数量输入 / 状态+折叠指示
   交互：**整行点击**展开/收起明细（区内控件用 @click.stop 隔离）
   明细区：跨满整行（grid-column 1/-1），默认收起 */
.fill-row {
  cursor: pointer;
  transition: background-color .12s;
}
.fill-row:hover { background: #f9fbfd; }
/* 有异常的行：hover 保持红系底色，不被通用 hover 覆盖 */
.fill-row.row-has-exception:hover { background: #fff5f5; }
.fill-row.is-expanded { background: #fbfdff; }
.fill-row.row-has-exception.is-expanded { background: #fffafa; }
/* 折叠三角：CSS 边框画，展开时旋转 180°（不占位置、不抢视觉） */
.fill-row-caret {
  margin-left: 8px;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid #a0aec0;
  transition: transform .15s, border-top-color .15s;
  flex-shrink: 0;
}
.fill-row:hover .fill-row-caret { border-top-color: #4a5568; }
.fill-row-caret.is-open { transform: rotate(180deg); border-top-color: #2b6cb0; }
.fill-row-detail {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
  min-width: 0;
  cursor: default;
}
/* 明细区操作按钮组：整体靠右（margin-left:auto），内部按逻辑顺序左→右排列
   （更改填报日期 → 按段填报 → 异常提报），视觉上从右边缘往里收 */
.fill-detail-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
/* 收起态的异常极简提示（明细在展开区） */
.exc-mini {
  display: inline-block;
  padding: 0 6px;
  border-radius: 8px;
  background: #fffaf0;
  border: 1px solid #fbd38d;
  color: #c05621;
  font-size: 11px;
  font-weight: 600;
  line-height: 16px;
  white-space: nowrap;
}

/* 节点详情行：色条/信息/状态/偏差 */
.row-grid-detail {
  display: grid;
  grid-template-columns: 6px 1fr auto auto;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;  /* 紧凑化：14 → 10 */
}
.row-info { min-width: 0; }
/* 数量行：左 "共计X/完成Y"  右 "最新完成日期 2026-xx-xx"，紧凑一行 */
.row-qty-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  white-space: nowrap;
  font-weight: 600;
}
.latest-date { font-size: 12px; color: #64748b; white-space: nowrap; display: inline-flex; align-items: baseline; gap: 4px; }
.latest-date .ld-key { color: #718096; font-size: 12px; font-weight: 600; }
.latest-date .ld-val { color: #1a365d; font-size: 12px; font-variant-numeric: tabular-nums; }
.deviation-label { font-size: 12px; color: #718096; text-align: right; white-space: nowrap; }

/* 计划/实际日期：左右两列独立块，间距 18px，块最小宽 130px，防止挤压；tabular-nums 防数字抖位 */
.row-dates { display: flex; gap: 18px; align-items: center; }
.date-block { display: flex; gap: 6px; align-items: baseline; min-width: 130px; padding: 2px 0; }
.date-key { color: #1a365d; font-size: 13px; font-weight: 700; }
.date-val { color: #1a365d; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; font-size: 14px; }
.date-empty { color: #a0aec0; font-style: italic; font-weight: 400; }
/* 异常解决后重算的计划日：附带「原 X」对照，弱化显示避免抢主日期 */
.date-orig {
  font-size: 11px; color: #a0aec0; font-weight: 400;
  text-decoration: line-through; white-space: nowrap;
}

/* === 异常暂停（2026-10）：所属套标识 === */
/* 行级醒目标识：红框 + 淡红底 + 柔和外发光（与「存在异常」工序卡片同视觉语言） */
.row-card.row-has-exception {
  border: 1px solid #fc8181;
  background: #fffafa;
  box-shadow: 0 0 0 3px rgba(229, 62, 62, 0.06);
  border-radius: 8px;
}
/* 「哪一套」小标签：红底白字系，带异常工序名 + 该套下料计划日 */
.exc-chip {
  display: inline-flex; align-items: center; gap: 2px;
  padding: 1px 8px; border-radius: 10px;
  background: #fff5f5; color: #c53030;
  border: 1px solid #feb2b2;
  font-size: 11px; font-weight: 600; line-height: 17px;
  white-space: nowrap; flex-shrink: 0;
}
/* 节点详情顶部汇总条：本工序有哪几套存在未关闭异常 + 口径说明 */
.exc-banner {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px;
  padding: 8px 14px; margin-bottom: 10px;
  background: #fffaf0; border: 1px solid #f6ad55; border-radius: 8px;
  font-size: 12px; color: #7b341e;
}
.exc-banner-title { font-weight: 700; color: #c05621; }
.exc-banner-body { display: flex; flex-wrap: wrap; gap: 6px; }
.exc-banner-item {
  background: #fff; border: 1px solid #fbd38d; border-radius: 10px;
  padding: 1px 8px; font-weight: 600; color: #9c4221;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.exc-banner-hint { color: #975a16; flex-basis: 100%; }
/* 已超计划关闭日（expired）：灰字提示——暂停已失效、已恢复逾期判定（不等于关闭） */
.exc-banner-expired {
  flex-basis: 100%;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.6;
  border-top: 1px dashed #fbd38d;
  padding-top: 4px;
}
/* 异常记录页签：提报表单折叠区 */
.exc-form-collapse { margin-top: 14px; }
.exc-form-collapse :deep(.el-collapse-item__header) {
  font-size: 13px;
  font-weight: 600;
  color: #1a365d;
}
.exc-form-hint { font-size: 12px; color: #94a3b8; padding: 8px 0; }

/* === 「第 N 套」展示（2026-10，只读） === */
/* 浅色可点角标：紧贴「N 套」右侧，弱化视觉层级（不抢计划/实际套数） */
.set-badge {
  display: inline-flex; align-items: center;
  padding: 0 8px; border-radius: 9px;
  background: #f0f4f9; color: #4a5568;
  border: 1px dashed #cbd5e0;
  font-size: 11px; font-weight: 600; line-height: 17px;
  white-space: nowrap; flex-shrink: 0;
  cursor: pointer; user-select: none;
  transition: background-color .12s, border-color .12s, color .12s;
}
.set-badge:hover { background: #e6effa; border-color: #90b4d8; color: #1a365d; }
/* 填报 tab 里的角标再弱一级（纯只读查看，与详情页开关区分） */
.set-badge-lite { background: #f7fafc; border-style: solid; border-color: #e2e8f0; color: #718096; }

/* 逐套子行列表：缩进对齐父行内容区，左侧竖线表示「属于上一行」 */
.set-child-list {
  margin: -4px 0 8px 24px;
  padding: 6px 0 2px 14px;
  border-left: 2px solid #e2e8f0;
}
.set-child {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 14px;
  padding: 5px 10px; margin-bottom: 4px;
  background: #fcfdfe; border: 1px solid #edf2f7; border-radius: 6px;
  font-size: 12px; color: #4a5568;
}
/* 该套被异常暂停：与整行「异常暂停」同视觉语言（灰+淡黄提醒边） */
.set-child.set-child-paused {
  background: #fffaf0; border-color: #fbd38d;
}
.set-child .set-name {
  font-weight: 700; color: #1a365d;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.set-child .set-date {
  color: #1a365d; font-weight: 600;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.set-child .set-actual { color: #4a5568; white-space: nowrap; }
.set-child .status-pill { font-size: 11px; line-height: 17px; padding: 0 8px; }
.set-derived { font-size: 11px; color: #b7791f; font-weight: 400; }
.set-src { font-size: 11px; color: #a0aec0; }
.set-child-hint { font-size: 11px; color: #94a3b8; padding: 2px 4px 0; line-height: 1.6; }

/* 填报 tab 的只读气泡 */
.set-bubble { font-size: 12px; color: #4a5568; }
.set-bubble-title { font-weight: 700; color: #1a365d; margin-bottom: 8px; }
.set-bubble-row {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px;
  padding: 3px 0; border-bottom: 1px dashed #edf2f7;
}
.set-bubble-row:last-of-type { border-bottom: none; }
.set-bubble-date { color: #1a365d; font-variant-numeric: tabular-nums; }
.set-bubble-done { color: #2f855a; }
.set-bubble-todo { color: #a0aec0; }
.set-bubble-hint { margin-top: 8px; font-size: 11px; color: #94a3b8; line-height: 1.65; }
.cell-plan-date { font-size: 13px; color: #64748b; white-space: nowrap; }
.cell-plan-qty { display: inline-flex; align-items: baseline; gap: 4px; white-space: nowrap; }
.qty-num { font-weight: 600; font-variant-numeric: tabular-nums; font-size: 15px; }
.qty-unit { color: #718096; font-size: 13px; }
.cell-qty-input { width: 120px; }
/* 恢复步进按钮后适配：默认组件宽度会被内建样式控制，此处覆盖；步进按钮 28px×2 + 输入区约 64px 可容纳 3 位数 */
.cell-qty-input :deep(.el-input-number__decrease),
.cell-qty-input :deep(.el-input-number__increase) { width: 28px; }
.cell-qty-input :deep(.el-input__inner) { text-align: center; font-variant-numeric: tabular-nums; }
.cell-status { white-space: nowrap; }
.cell-pending { font-size: 12px; color: #64748b; white-space: nowrap; }
.cell-done-record { display: inline-flex; align-items: center; font-size: 13px; color: #1a365d; font-weight: 600; white-space: nowrap; }
.cell-done-date { margin-left: 8px; white-space: nowrap; }
/* 色条宽度与 grid 第 1 列（6px）对齐，覆盖全局 theme.css 的 .row-card .row-bar{width:4px} */
.row-grid .row-bar, .row-grid-detail .row-bar { width: 6px; }
.cell-report-date { display: flex; align-items: center; gap: 10px; }
/* 展开更多按钮：分页展开区域，置中、淡灰背景，与 row-card 视觉区隔 */
.expand-more { text-align: center; padding: 12px 0 4px; margin-top: 4px; border-top: 1px dashed #e2e8f0; }
.rd-tag {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 10px; border-radius: 6px;
  background: #ebf8ff; color: #1a365d;
  font-size: 12px; font-weight: 600;
  font-variant-numeric: tabular-nums; min-width: 92px; text-align: center;
  white-space: nowrap;
}
.rd-today { background: #f7fafc; color: #2d3748; }   /* 未开始/未填写的「今天」标识稍灰 */
.rd-btn { padding: 4px 10px; font-size: 12px; }
.rd-picker-panel { padding: 4px 0; }
.rd-picker-hint { margin-bottom: 6px; font-size: 11px; color: #64748b; }

/* 一键提报弹窗 */
.batch-body { padding: 4px 0; }
.batch-option {
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: #ffffff;
  cursor: pointer;
  transition: border-color .15s, box-shadow .15s, background .15s;
}
.batch-option:hover { border-color: #cbd5e0; }
.batch-option.opt-active {
  border-color: #1a365d;
  background: #f0f4f9;
  box-shadow: 0 0 0 3px rgba(26, 54, 93, 0.08);
}
.batch-option.opt-disabled {
  background: #f7fafc;
  cursor: not-allowed;
  opacity: 0.65;
}
.batch-option.opt-disabled:hover { border-color: #e2e8f0; }
.batch-option.opt-disabled .opt-row { color: #a0aec0; }
.opt-row { display: flex; align-items: center; gap: 10px; }
.opt-title { font-weight: 600; font-size: 15px; color: #1a365d; padding-left: 2px; }
.opt-desc {
  margin-top: 8px;
  margin-left: 24px;       /* 缩进对齐 radio 文字 */
  font-size: 13px;
  line-height: 1.7;
  color: #4a5568;
}
.opt-disabled-hint {
  margin-top: 6px;
  margin-left: 24px;
  font-size: 12px;
  color: #e53e3e;
  background: #fff5f5;
  border-left: 3px solid #e53e3e;
  padding: 4px 8px;
  border-radius: 4px;
}
.batch-empty {
  text-align: center;
  padding: 14px;
  color: #718096;
  font-size: 13px;
  background: #f7fafc;
  border-radius: 8px;
}

/* 按段填报弹窗（v7.1 行级化） */
/* 行内「按段填报」小按钮：与行内其他按钮（更改填报日期）同高 */
.seg-btn { padding: 4px 10px; font-size: 12px; }
/* 行内「异常提报」小按钮：与按段填报同高，橙色描边（warning plain）与主操作「按段填报」区分 */
.exc-btn { padding: 4px 10px; font-size: 12px; }
.seg-body { padding: 4px 0; }
/* 蓝色说明条 */
.seg-tip {
  background: #ebf8ff;
  border: 1px solid #bee3f8;
  color: #2c5282;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.7;
  margin-bottom: 16px;
}
.seg-fields { display: flex; gap: 28px; margin-bottom: 16px; }
.seg-field { display: flex; align-items: center; gap: 10px; }
.seg-field-label { font-size: 14px; color: #1a365d; font-weight: 600; white-space: nowrap; }
/* 已完成段数：只读展示，仅能通过点击下方方块修改（不再提供步进器） */
.seg-done-readonly {
  display: flex; align-items: center; gap: 4px;
  min-width: 78px; height: 32px;
  padding: 0 14px; box-sizing: border-box;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f7fafc;
  color: #1a365d;
  font-size: 15px; font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.seg-done-unit { font-size: 12px; font-weight: 400; color: #94a3b8; }
/* 分段进度可视化：一排小块，前 done 个绿色其余灰色；点击第 i 块 = 已完成 i 段 */
.seg-blocks { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.seg-block {
  width: 30px; height: 30px;
  border-radius: 6px;
  background: #e2e8f0; color: #64748b;
  border: 1px solid transparent;
  box-sizing: border-box;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  user-select: none;
  transition: background-color .12s, border-color .12s;
}
.seg-block:hover { border-color: #38a169; background: #eaf5ee; color: #2f7a4f; }
.seg-block-done { background: #38a169; color: #ffffff; }
.seg-block-done:hover { background: #2f8f5b; border-color: #2f8f5b; color: #ffffff; }
.seg-block-disabled { cursor: not-allowed; opacity: .6; }
.seg-hint { font-size: 12px; color: #94a3b8; margin-bottom: 10px; }
.seg-progress-line { font-size: 13px; color: #4a5568; }
.seg-progress-line b { color: #1a365d; }
/* 「已保存按段记录」提示：低调橙色底，说明取消按段的影响范围（不动完成套数） */
.seg-record-hint {
  margin-top: 12px;
  padding: 8px 10px;
  background: #fffaf0;
  border: 1px solid #fbd38d;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: #975a16;
}
.seg-record-hint b { color: #744210; }

@media (max-width: 1100px) {
  .row-grid { gap: 10px; padding: 10px 14px; }
  .row-left-section { gap: 10px; }
  .row-center-section { gap: 8px; }
  .cell-qty-input { width: 110px; }
  .row-grid-detail { padding: 8px 14px; gap: 10px; }
  .latest-date { font-size: 11px; }
}
</style>

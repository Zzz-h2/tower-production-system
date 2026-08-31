<template>
  <div ref="chartRef" :style="{ height: height + 'px', width: '100%' }"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  processes: { type: Array, default: () => [] },
  height: { type: Number, default: 480 },
})

// 图例隐藏的工序名集合：点击右侧图例切换，真正从坐标轴上移除对应工序
const emit = defineEmits(['visible-change'])
const hidden = ref(new Set())

const chartRef = ref(null)
let chart = null

const colorMap = {
  done: '#38a169',
  in_progress: '#3182ce',
  warning: '#d69e2e',
  overdue: '#e53e3e',
  pending: '#cbd5e0',
}
const labelMap = {
  done: '达标/提前完成',
  in_progress: '进行中/提前进行中',
  warning: '部分完成',
  overdue: '逾期未完成',
  pending: '未到',
}

function render() {
  if (!chart) return
  const allProcesses = props.processes || []
  const allRows = props.rows || []
  // 过滤掉被图例隐藏的工序
  const displayProcesses = allProcesses.filter((p) => !hidden.value.has(p))
  const displayRows = allRows.filter((r) => !hidden.value.has(r.process_name))
  // 对外通知当前可见工序数（父组件据以重算时间轴高度，实现实时布局更新）
  emit('visible-change', displayProcesses.length)
  if (!displayProcesses.length || !allRows.length) {
    chart.clear()
    return
  }
  // 按工序分组（保持传入顺序）；被隐藏的工序保留空 series，以便图例可随时取消隐藏
  const series = []
  allProcesses.forEach((pn) => {
    if (hidden.value.has(pn)) {
      series.push({ name: pn, type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, data: [] })
      return
    }
    const nodes = displayRows.filter((r) => r.process_name === pn)
    if (!nodes.length) return
    series.push({
      name: pn,
      type: 'scatter',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: nodes.map((r) => ({
        // time 轴推荐传时间戳，避免字符串解析不一致
        value: [new Date(r.plan_date).getTime(), pn],
        status: r.status,                 // 附带状态，tooltip 直接使用
        itemStyle: { color: colorMap[r.status] || '#cbd5e0' },
        symbolSize: 12,
        label: { show: false },
      })),
    })
  })
  // 今天竖线（转时间戳）
  const today = new Date().toISOString().slice(0, 10)
  const todayTs = new Date(today).getTime()
  const markLine = {
    symbol: 'none',
    lineStyle: { color: '#e53e3e', width: 2, type: 'dashed' },
    label: { formatter: '今天', color: '#e53e3e', position: 'end' },
    data: [{ xAxis: todayTs }],
  }
  // 显式计算 x 轴范围（用数字而非动态函数），保证新数据导入后轴范围一定更新到最新
  // 仅取可见工序的日期，避免隐藏项拉伸轴范围
  let minTs = Infinity
  let maxTs = -Infinity
  for (const r of displayRows) {
    const t = new Date(r.plan_date).getTime()
    if (Number.isFinite(t)) {
      if (t < minTs) minTs = t
      if (t > maxTs) maxTs = t
    }
  }
  const pad = 2 * 24 * 3600 * 1000  // 前后各留 2 天 padding
  const fallbackSpan = 30 * 24 * 3600 * 1000
  const now = Date.now()
  const xMin = Number.isFinite(minTs) ? minTs - pad : now - fallbackSpan
  const xMax = Number.isFinite(maxTs) ? maxTs + pad : now + fallbackSpan
  chart.setOption({
    backgroundColor: '#fff',
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const status = p.data?.status || ''
        const dateStr = p.value[0]
          ? new Date(p.value[0]).toLocaleDateString('zh-CN')
          : ''
        return `${p.name}<br/>计划：${dateStr}<br/>状态：${labelMap[status] || '未知'}`
      },
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 10,
      top: 'middle',
      textStyle: { color: '#222222' },
      // 列出全部工序，便于取消隐藏；selected 反映当前隐藏状态
      data: allProcesses,
      selected: Object.fromEntries(allProcesses.map((p) => [p, !hidden.value.has(p)])),
    },
    grid: { left: 120, right: 160, top: 40, bottom: 40, containLabel: true },
    xAxis: {
      type: 'time',
      min: xMin,
      max: xMax,
      axisLabel: { color: '#64748b', formatter: '{yyyy}-{MM}-{dd}', rotate: 30 },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: {
      type: 'category',
      // 仅展示未隐藏的工序 → 隐藏后对应工序从坐标轴上移除
      data: displayProcesses,
      axisLabel: { color: '#222222', fontSize: 13 },
    },
    series: [...series, { type: 'scatter', markLine, data: [] }],
  })
}

// 点击右侧图例 → 切换隐藏集合 → 重绘（同时移除坐标轴标签与散点）
function onLegendSelectChanged(params) {
  const next = new Set(hidden.value)
  for (const [name, sel] of Object.entries(params.selected || {})) {
    if (sel) next.delete(name)
    else next.add(name)
  }
  hidden.value = next
  render()
}

let resizeObserver = null
onMounted(() => {
  chart = echarts.init(chartRef.value)
  render()
  // 初始尺寸可能尚未稳定，显式 resize 一次
  chart.resize()
  // 容器尺寸变化（height prop 变 / 窗口变 / 侧栏折叠）都强制 ECharts 跟随，
  // 避免"导入后排产数据变了但画布/范围没刷新"的问题
  if (window.ResizeObserver && chartRef.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartRef.value)
  }
  // 点击右侧图例 → 切换工序显隐（隐藏后从坐标轴移除，可再次点击取消隐藏）
  chart.on('legendselectchanged', onLegendSelectChanged)
})
watch(() => props.height, () => {
  // height prop 变化（visible_processes 数量变化触发 timelineHeight 重算）→ 重绘
  nextTick(() => chart?.resize())
})
watch(() => [props.rows, props.processes], render, { deep: true })
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

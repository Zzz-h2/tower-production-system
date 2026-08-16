<template>
  <div ref="chartRef" :style="{ height: height + 'px', width: '100%' }"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  processes: { type: Array, default: () => [] },
  height: { type: Number, default: 480 },
})

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
  if (!chart || !props.rows.length) return
  // 按工序分组（保持传入顺序）
  const series = []
  props.processes.forEach((pn) => {
    const nodes = props.rows.filter((r) => r.process_name === pn)
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
    },
    grid: { left: 120, right: 160, top: 40, bottom: 40, containLabel: true },
    xAxis: {
      type: 'time',
      // {yyyy}-{MM}-{dd} 才是完整年月日；{m} 是分钟会显示错误刻度
      min: (value) => value.min - 24 * 3600 * 1000 * 2,   // 最小值前推 2 天
      max: (value) => value.max + 24 * 3600 * 1000 * 2,   // 最大值后推 2 天
      axisLabel: { color: '#64748b', formatter: '{yyyy}-{MM}-{dd}', rotate: 30 },
      axisLine: { lineStyle: { color: '#cbd5e0' } },
    },
    yAxis: {
      type: 'category',
      data: props.processes,
      axisLabel: { color: '#222222', fontSize: 13 },
    },
    series: [...series, { type: 'scatter', markLine, data: [] }],
  })
}

onMounted(() => {
  chart = echarts.init(chartRef.value)
  render()
})
watch(() => [props.rows, props.processes], render, { deep: true })
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

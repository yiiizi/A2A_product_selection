<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { ProductAnalysisResult } from '../types/chat'

use([RadarChart, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  product: ProductAnalysisResult | null
}>()

const option = computed(() => {
  if (!props.product) return null

  const bd = props.product.score_breakdown
  const indicators = [
    { name: '市场趋势', max: 100 },
    { name: '竞争优势', max: 100 },
    { name: '利润空间', max: 100 },
    { name: '供应稳定', max: 100 },
    { name: '口碑机会', max: 100 },
    { name: '风险控制', max: 100 },
  ]

  const values = [
    bd.trend_score ?? 0,
    bd.competition_score ?? 0,
    bd.profit_score ?? 0,
    bd.supply_score ?? 0,
    bd.review_score ?? 0,
    bd.risk_score ?? 0,
  ]

  const styles = getComputedStyle(document.documentElement)
  const axisColor = styles.getPropertyValue('--text-secondary').trim() || '#606266'
  const borderColor = styles.getPropertyValue('--border-color').trim() || '#dcdfe6'
  const accentBlue = styles.getPropertyValue('--accent-blue').trim() || '#2f7cf6'

  return {
    backgroundColor: 'transparent',
    tooltip: {},
    radar: {
      indicator: indicators,
      shape: 'polygon',
      splitNumber: 5,
      axisName: {
        color: axisColor,
        fontSize: 12,
      },
      splitLine: {
        lineStyle: { color: borderColor },
      },
      splitArea: {
        areaStyle: { color: ['transparent'] },
      },
      axisLine: {
        lineStyle: { color: borderColor },
      },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: values,
            name: props.product.product_name,
            lineStyle: { color: accentBlue, width: 2 },
            areaStyle: { color: 'rgba(47, 124, 246, 0.18)' },
            itemStyle: { color: accentBlue },
          },
        ],
      },
    ],
  }
})
</script>

<template>
  <el-card v-if="product" class="radar-card">
    <template #header>
      <div class="panel-header">
        <el-icon><DataAnalysis /></el-icon>
        <span>评分维度雷达图</span>
        <el-tag size="small">{{ product.product_name }}</el-tag>
      </div>
    </template>
    <div class="chart-container">
      <VChart v-if="option" :option="option" autoresize />
    </div>
  </el-card>
</template>

<style scoped>
.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.chart-container {
  height: 320px;
}
</style>

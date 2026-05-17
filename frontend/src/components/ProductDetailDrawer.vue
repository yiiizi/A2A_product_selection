<script setup lang="ts">
import { computed } from 'vue'
import type { AgentResult, ProductAnalysisResult } from '../types/chat'
import ScoreRadar from './ScoreRadar.vue'

const props = defineProps<{
  visible: boolean
  product: ProductAnalysisResult | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
}>()

const drawerVisible = computed({
  get: () => props.visible,
  set: (val) => emit('update:visible', val),
})

const agentLabels: Record<string, string> = {
  MarketAgent: '市场趋势分析',
  ProfitAgent: '利润测算',
  SupplyRiskAgent: '供应链与风险',
  ReviewInsightAgent: '评论洞察',
}

const agentColors: Record<string, string> = {
  MarketAgent: 'var(--accent-blue)',
  ProfitAgent: 'var(--accent-green)',
  SupplyRiskAgent: 'var(--accent-orange)',
  ReviewInsightAgent: 'var(--accent-purple)',
}

const scoreLabels: Record<string, string> = {
  trend_score: '市场趋势',
  competition_score: '竞争优势',
  profit_score: '利润空间',
  supply_score: '供应稳定',
  review_score: '口碑机会',
  risk_score: '风险控制',
}

const detailLabels: Record<string, string> = {
  trend_data: '趋势数据',
  competitor_data: '竞品数据',
  price_band_data: '价格带数据',
  price_band: '价格带判断',
  differentiation_opportunity: '差异化机会',
  profit_data: '利润测算数据',
  suggest_data: '建议售价数据',
  break_even_data: '盈亏平衡数据',
  gross_margin: '毛利率',
  suggested_price: '建议售价',
  break_even_units: '盈亏平衡销量',
  supplier_data: '供应商数据',
  stock_data: '备货建议数据',
  risk_data: '风险评估数据',
  risk_level: '风险等级',
  lead_time_days: '交期天数',
  moq: '最小起订量',
  initial_stock_suggestion: '首批备货建议',
  risk_items: '风险项',
  review_search: '评论检索结果',
  doc_search: '资料检索结果',
  review_stats: '评论统计',
  positive_points: '好评点',
  negative_points: '差评点',
  pain_points: '用户痛点',
  selling_point_opportunities: '卖点机会',
  listing_copy_suggestions: '详情页文案建议',
}

function statusText(status: string) {
  if (status === 'success') return '成功'
  if (status === 'partial') return '部分完成'
  return '失败'
}

function statusTag(status: string) {
  if (status === 'success') return 'success'
  if (status === 'partial') return 'warning'
  return 'danger'
}

function recommendationText(rec: string) {
  if (rec === 'recommend') return '建议选品'
  if (rec === 'neutral') return '谨慎观察'
  return '暂不建议'
}

function recommendationTag(rec: string) {
  if (rec === 'recommend') return 'success'
  if (rec === 'neutral') return 'warning'
  return 'danger'
}

function scoreItems(scores: Record<string, number>) {
  return Object.entries(scores || {}).map(([key, value]) => ({
    label: scoreLabels[key] || key,
    value,
  }))
}

function detailItems(details: Record<string, any>) {
  return Object.entries(details || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => ({
      label: detailLabels[key] || key,
      value,
    }))
}

function valueToText(value: any): string {
  if (Array.isArray(value)) {
    if (!value.length) return '暂无'
    return value.map((item) => valueToText(item)).join('；')
  }
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}

function hasAgentDetail(result: AgentResult) {
  return detailItems(result.details).length > 0 || scoreItems(result.scores).length > 0
}
</script>

<template>
  <el-drawer
    v-model="drawerVisible"
    :title="product?.product_name ?? '商品详情'"
    size="680px"
  >
    <template v-if="product">
      <div class="detail-section">
        <h3>商品概览</h3>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="商品名称">{{ product.product_name }}</el-descriptions-item>
          <el-descriptions-item label="类目">{{ product.category }}</el-descriptions-item>
          <el-descriptions-item label="综合评分">
            <span class="score">{{ product.final_score }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="选品建议">
            <el-tag :type="recommendationTag(product.recommendation)">
              {{ recommendationText(product.recommendation) }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="detail-section">
        <ScoreRadar :product="product" />
      </div>

      <div class="detail-section" v-if="product.highlights.length">
        <h3>核心结论</h3>
        <ul>
          <li v-for="(h, i) in product.highlights" :key="i">{{ h }}</li>
        </ul>
      </div>

      <div class="detail-section" v-if="product.risks.length">
        <h3>风险提醒</h3>
        <ul class="risks">
          <li v-for="(r, i) in product.risks" :key="i">{{ r }}</li>
        </ul>
      </div>

      <div class="detail-section" v-for="(result, agentName) in product.agent_results" :key="agentName">
        <h3 :style="{ color: agentColors[agentName as string] }">
          {{ agentLabels[agentName as string] ?? '智能体分析' }}
          <el-tag
            :type="statusTag(result.status)"
            size="small"
            style="margin-left: 8px;"
          >
            {{ statusText(result.status) }}
          </el-tag>
        </h3>

        <p v-if="result.summary" class="agent-summary">{{ result.summary }}</p>
        <p v-else-if="result.error" class="agent-summary error-text">{{ result.error }}</p>

        <div v-if="hasAgentDetail(result)" class="agent-block">
          <div v-if="scoreItems(result.scores).length" class="score-grid">
            <div v-for="item in scoreItems(result.scores)" :key="item.label" class="score-item">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>

          <div v-if="detailItems(result.details).length" class="detail-list">
            <div v-for="item in detailItems(result.details)" :key="item.label" class="detail-row">
              <span class="detail-label">{{ item.label }}</span>
              <pre v-if="typeof item.value === 'object'" class="detail-value">{{ valueToText(item.value) }}</pre>
              <span v-else class="detail-value">{{ valueToText(item.value) }}</span>
            </div>
          </div>
        </div>

        <div v-if="result.suggestions.length" class="suggestions">
          <p class="label">执行建议</p>
          <ul>
            <li v-for="(s, i) in result.suggestions" :key="i">{{ s }}</li>
          </ul>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.detail-section {
  margin-bottom: 24px;
}

.detail-section h3 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 12px;
}

.score {
  font-size: 20px;
  font-weight: 700;
  color: var(--accent-green);
}

.agent-summary {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin-bottom: 10px;
}

.error-text {
  color: var(--accent-red);
}

.agent-block {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  background: var(--bg-secondary);
}

.score-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.score-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--bg-card);
  font-size: 13px;
  color: var(--text-secondary);
}

.score-item strong {
  color: var(--text-primary);
}

.detail-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-label,
.suggestions .label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 600;
}

.detail-value {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

.suggestions {
  margin-top: 10px;
}

.suggestions ul,
ul {
  padding-left: 20px;
}

.suggestions li,
li {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.risks li {
  color: var(--accent-red);
}

@media (max-width: 720px) {
  .score-grid {
    grid-template-columns: 1fr;
  }
}
</style>

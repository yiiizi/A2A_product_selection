<script setup lang="ts">
import { computed } from 'vue'
import type { ProductAnalysisResult } from '../types/chat'

const props = defineProps<{
  product: ProductAnalysisResult
  active: boolean
}>()

const emit = defineEmits<{
  (e: 'click'): void
  (e: 'detail'): void
}>()

const SHORT_LABELS: Record<string, string> = {
  trend_score: '趋势',
  competition_score: '竞争',
  profit_score: '利润',
  supply_score: '供应',
  review_score: '口碑',
  risk_score: '风险',
}

function scoreColor(score: number): string {
  if (score >= 80) return 'var(--accent-green)'
  if (score >= 60) return 'var(--accent-orange)'
  return 'var(--accent-red)'
}

function recTag(rec: string) {
  if (rec === 'recommend') return { text: '建议', type: 'success' as const }
  if (rec === 'neutral') return { text: '观察', type: 'warning' as const }
  return { text: '不建议', type: 'danger' as const }
}

const breakdownEntries = computed(() => {
  return Object.entries(props.product.score_breakdown || {}).slice(0, 6)
})
</script>

<template>
  <div class="product-mini-card" :class="{ active }" @click="emit('click')">
    <div class="rank-badge">{{ product.rank }}</div>
    <div class="card-body">
      <h4>{{ product.product_name }}</h4>
      <div class="score-row">
        <span class="final-score" :style="{ color: scoreColor(product.final_score) }">
          {{ product.final_score }}
        </span>
        <el-tag :type="recTag(product.recommendation).type" size="small">
          {{ recTag(product.recommendation).text }}
        </el-tag>
      </div>
      <div class="mini-bars">
        <div v-for="[key, val] in breakdownEntries" :key="key" class="mini-bar">
          <span class="bar-label">{{ SHORT_LABELS[key] || key }}</span>
          <div class="bar-track">
            <div
              class="bar-fill"
              :style="{ width: (val || 0) + '%', background: scoreColor(val) }"
            />
          </div>
          <span class="bar-val">{{ val }}</span>
        </div>
      </div>
      <div class="card-actions">
        <el-button size="small" text type="primary" @click.stop="emit('detail')">
          查看详情
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.product-mini-card {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  border: 1px solid transparent;
  margin-bottom: 8px;
}

.product-mini-card:hover,
.product-mini-card.active {
  background: var(--bg-secondary);
}

.product-mini-card.active {
  border-color: var(--accent-blue);
}

.rank-badge {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent-blue);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-body h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.score-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.final-score {
  font-size: 22px;
  font-weight: 700;
}

.mini-bars {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 4px;
}

.mini-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.bar-label {
  font-size: 11px;
  color: var(--text-secondary);
  width: 32px;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 4px;
  background: var(--bg-secondary);
  border-radius: 2px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

.bar-val {
  font-size: 11px;
  color: var(--text-secondary);
  width: 24px;
  text-align: right;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
}
</style>

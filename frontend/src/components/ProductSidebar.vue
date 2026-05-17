<script setup lang="ts">
import ProductCardMini from './ProductCardMini.vue'
import type { ProductAnalysisResult } from '../types/chat'

defineProps<{
  products: ProductAnalysisResult[]
  selectedProduct: ProductAnalysisResult | null
}>()

const emit = defineEmits<{
  (e: 'select-product', product: ProductAnalysisResult): void
  (e: 'view-detail', product: ProductAnalysisResult): void
  (e: 'export-report'): void
}>()
</script>

<template>
  <aside class="product-sidebar">
    <div class="sidebar-header">
      <h3>选品结果</h3>
      <el-tag v-if="products.length" size="small" type="info">
        {{ products.length }} 个
      </el-tag>
    </div>

    <div v-if="!products.length" class="empty-hint">
      <el-empty description="分析完成后这里会展示候选商品" :image-size="80" />
    </div>

    <div v-else class="product-list">
      <ProductCardMini
        v-for="p in products"
        :key="p.product_id"
        :product="p"
        :active="selectedProduct?.product_id === p.product_id"
        @click="emit('select-product', p)"
        @detail="emit('view-detail', p)"
      />
    </div>

    <div v-if="products.length" class="sidebar-actions">
      <el-button size="small" @click="emit('export-report')">
        <el-icon><Download /></el-icon>
        导出报告
      </el-button>
    </div>
  </aside>
</template>

<style scoped>
.product-sidebar {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border-color);
  background: var(--bg-card);
}

.sidebar-header {
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-color);
}

.sidebar-header h3 {
  font-size: 15px;
  font-weight: 600;
}

.empty-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.product-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.sidebar-actions {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}
</style>

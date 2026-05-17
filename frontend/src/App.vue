<script setup lang="ts">
import { ref } from 'vue'
import ChatSidebar from './components/ChatSidebar.vue'
import ChatMain from './components/ChatMain.vue'
import ProductSidebar from './components/ProductSidebar.vue'
import ProductDetailDrawer from './components/ProductDetailDrawer.vue'
import type { ProductAnalysisResult } from './types/chat'

const loading = ref(false)
const products = ref<ProductAnalysisResult[]>([])
const selectedProduct = ref<ProductAnalysisResult | null>(null)
const drawerVisible = ref(false)
const activeSessionId = ref('')

function handleProductsUpdate(newProducts: ProductAnalysisResult[]) {
  products.value = newProducts
  if (newProducts.length > 0) {
    selectedProduct.value = newProducts[0]
  }
}

function handleViewDetail(product: ProductAnalysisResult) {
  selectedProduct.value = product
  drawerVisible.value = true
}

function handleSelectProduct(product: ProductAnalysisResult) {
  selectedProduct.value = product
}

function handleExportReport() {
  const apiBase = import.meta.env.VITE_API_BASE || ''
  window.open(`${apiBase}/api/selection/reports`, '_blank')
}
</script>

<template>
  <div class="app-layout">
    <ChatSidebar
      v-model:active-session-id="activeSessionId"
      :loading="loading"
    />

    <ChatMain
      v-model:active-session-id="activeSessionId"
      :products="products"
      :loading="loading"
      @update:loading="(val: boolean) => loading = val"
      @update:products="handleProductsUpdate"
      @view-detail="handleViewDetail"
    />

    <ProductSidebar
      :products="products"
      :selected-product="selectedProduct"
      @select-product="handleSelectProduct"
      @view-detail="handleViewDetail"
      @export-report="handleExportReport"
    />

    <ProductDetailDrawer
      v-model:visible="drawerVisible"
      :product="selectedProduct"
    />
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background-color: var(--bg-primary);
}
</style>

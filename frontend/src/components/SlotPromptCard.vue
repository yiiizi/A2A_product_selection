<script setup lang="ts">
import type { FollowUp } from '../types/chat'

defineProps<{
  followUp: FollowUp
}>()

const emit = defineEmits<{
  (e: 'quick-reply', option: string): void
}>()
</script>

<template>
  <div class="slot-prompt-card">
    <div class="options-row">
      <el-button
        v-for="opt in followUp.options"
        :key="opt"
        size="small"
        round
        @click="emit('quick-reply', opt)"
      >
        {{ opt }}
      </el-button>
    </div>
    <div v-if="followUp.missing_slots.length" class="missing-hint">
      待补充：{{ followUp.missing_slots.join('、') }}
    </div>
  </div>
</template>

<style scoped>
.slot-prompt-card {
  align-self: flex-start;
  margin-left: 42px;
  margin-bottom: 8px;
}

.options-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.missing-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}
</style>

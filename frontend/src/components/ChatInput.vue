<script setup lang="ts">
const props = defineProps<{
  modelValue: string
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: string): void
  (e: 'send', message: string): void
}>()

function handleSend() {
  const text = props.modelValue.trim()
  if (!text || props.loading) return
  emit('send', text)
  emit('update:modelValue', '')
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input-area">
    <div class="input-wrapper">
      <textarea
        :value="modelValue"
        :disabled="loading"
        class="input-field"
        placeholder="输入选品需求或补充条件..."
        rows="1"
        @input="(e: Event) => emit('update:modelValue', (e.target as HTMLTextAreaElement).value)"
        @keydown="handleKeydown"
      />
      <el-button
        type="primary"
        :disabled="!modelValue.trim() || loading"
        :loading="loading"
        class="send-btn"
        @click="handleSend"
      >
        <el-icon><Promotion /></el-icon>
      </el-button>
    </div>
    <div class="input-hint">Enter 发送，Shift+Enter 换行</div>
  </div>
</template>

<style scoped>
.chat-input-area {
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-card);
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
  transition: border-color 0.15s;
}

.input-wrapper:focus-within {
  border-color: var(--accent-blue);
}

.input-field {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-primary);
  resize: none;
  min-height: 22px;
  max-height: 120px;
  font-family: inherit;
}

.input-field::placeholder {
  color: var(--text-secondary);
}

.input-field:disabled {
  opacity: 0.6;
}

.send-btn {
  flex-shrink: 0;
}

.input-hint {
  text-align: center;
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 6px;
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '../types/chat'

const props = defineProps<{
  message: ChatMessage
}>()

const isUser = computed(() => props.message.role === 'user')
const isSystem = computed(() => props.message.role === 'system')
const isReport = computed(() => props.message.message_type === 'report_card')

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = escapeHtml(text)
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
  html = html.replace(/\n\n/g, '</p><p>')
  html = '<p>' + html + '</p>'
  html = html.replace(/<p><\/p>/g, '')
  html = html.replace(/<p>(<h[1-3]>)/g, '$1')
  html = html.replace(/(<\/h[1-3]>)<\/p>/g, '$1')
  html = html.replace(/<p>(<ul>)/g, '$1')
  html = html.replace(/(<\/ul>)<\/p>/g, '$1')
  return html
}
</script>

<template>
  <div class="chat-bubble" :class="{ user: isUser, system: isSystem, report: isReport }">
    <div class="bubble-avatar">
      <el-icon v-if="isUser"><User /></el-icon>
      <el-icon v-else-if="isSystem"><InfoFilled /></el-icon>
      <el-icon v-else-if="isReport"><Document /></el-icon>
      <el-icon v-else><Cpu /></el-icon>
    </div>

    <div class="bubble-content">
      <div v-if="isReport" class="report-title">
        <el-icon><Document /></el-icon>
        <span>综合选品报告</span>
      </div>
      <div class="bubble-text" v-html="renderMarkdown(message.content)" />
    </div>
  </div>
</template>

<style scoped>
.chat-bubble {
  display: flex;
  gap: 10px;
  padding: 12px 0;
  max-width: 85%;
  align-self: flex-start;
}

.chat-bubble.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.chat-bubble.system {
  align-self: center;
  max-width: 95%;
  opacity: 0.85;
}

.chat-bubble.report {
  max-width: 96%;
}

.bubble-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 16px;
}

.chat-bubble.user .bubble-avatar {
  background: var(--accent-blue);
  color: #fff;
}

.chat-bubble:not(.user) .bubble-avatar {
  background: var(--bg-secondary);
  color: var(--accent-purple);
}

.bubble-content {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-bubble.user .bubble-content {
  align-items: flex-end;
}

.report-title {
  display: flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  padding: 7px 10px;
  border: 1px solid var(--border-color);
  border-bottom: none;
  border-radius: 12px 12px 0 0;
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.bubble-text {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.chat-bubble.user .bubble-text {
  background: var(--accent-blue);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.chat-bubble:not(.user) .bubble-text {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-bottom-left-radius: 4px;
}

.chat-bubble.report .bubble-text {
  border-top-left-radius: 0;
  padding: 16px 18px;
}

.bubble-text :deep(h1) {
  font-size: 18px;
  margin: 4px 0 12px;
}

.bubble-text :deep(h2) {
  font-size: 16px;
  margin: 14px 0 8px;
}

.bubble-text :deep(h3) {
  font-size: 15px;
  margin: 12px 0 6px;
}

.bubble-text :deep(ul) {
  padding-left: 18px;
  margin: 6px 0;
}

.bubble-text :deep(li) {
  font-size: 13px;
  line-height: 1.7;
}

.bubble-text :deep(strong) {
  color: inherit;
}

.chat-bubble.user .bubble-text :deep(strong) {
  color: #fff;
}
</style>

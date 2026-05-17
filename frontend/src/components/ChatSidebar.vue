<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createSession, deleteSession, listSessions } from '../api/chat'
import type { SessionSummary } from '../types/chat'

const props = defineProps<{
  activeSessionId: string
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:activeSessionId', val: string): void
}>()

const sessions = ref<SessionSummary[]>([])
const SESSION_IDS_KEY = 'ps_chat_session_ids'

function getStoredSessionIds(): string[] {
  try {
    const raw = localStorage.getItem(SESSION_IDS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function storeSessionId(sessionId: string) {
  const ids = getStoredSessionIds()
  if (!ids.includes(sessionId)) {
    ids.unshift(sessionId)
    localStorage.setItem(SESSION_IDS_KEY, JSON.stringify(ids.slice(0, 100)))
  }
}

function removeStoredSessionId(sessionId: string) {
  const ids = getStoredSessionIds().filter((id) => id !== sessionId)
  localStorage.setItem(SESSION_IDS_KEY, JSON.stringify(ids))
}

async function loadSessions() {
  const ids = getStoredSessionIds()
  if (!ids.length) {
    sessions.value = []
    return
  }
  try {
    sessions.value = await listSessions(ids)
  } catch {
    sessions.value = []
  }
}

async function newChat() {
  if (props.loading) return
  try {
    const sessionId = await createSession()
    storeSessionId(sessionId)
    emit('update:activeSessionId', sessionId)
    await loadSessions()
  } catch (e: any) {
    ElMessage.error('创建对话失败：' + (e.message || '未知错误'))
  }
}

function switchSession(sessionId: string) {
  emit('update:activeSessionId', sessionId)
}

async function deleteChat(sessionId: string) {
  try {
    await ElMessageBox.confirm('确定删除这个对话吗？', '提示', { type: 'warning' })
    await deleteSession(sessionId)
    removeStoredSessionId(sessionId)
    if (props.activeSessionId === sessionId) {
      emit('update:activeSessionId', '')
    }
    await loadSessions()
  } catch {
    // 用户取消或删除失败时不打断当前操作
  }
}

onMounted(loadSessions)

watch(() => props.activeSessionId, (newId) => {
  if (newId && !sessions.value.find((s) => s.session_id === newId)) {
    loadSessions()
  }
})
</script>

<template>
  <aside class="chat-sidebar">
    <div class="sidebar-header">
      <el-button type="primary" :disabled="loading" class="new-chat-btn" @click="newChat">
        <el-icon><Plus /></el-icon>
        <span>新对话</span>
      </el-button>
    </div>

    <div class="session-list">
      <div
        v-for="s in sessions"
        :key="s.session_id"
        class="session-item"
        :class="{ active: s.session_id === activeSessionId }"
        @click="switchSession(s.session_id)"
      >
        <div class="session-info">
          <span class="session-title">{{ s.title || '新对话' }}</span>
          <span class="session-meta">{{ s.message_count }} 条消息</span>
        </div>
        <el-button
          class="delete-btn"
          :icon="'Delete'"
          text
          size="small"
          @click.stop="deleteChat(s.session_id)"
        />
      </div>

      <el-empty
        v-if="!sessions.length"
        description="暂无历史对话"
        :image-size="60"
      />
    </div>

    <div class="sidebar-footer">
      <span class="tip">分析中也可以切换历史对话</span>
    </div>
  </aside>
</template>

<style scoped>
.chat-sidebar {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color);
  background: var(--bg-card);
}

.sidebar-header {
  padding: 16px;
}

.new-chat-btn {
  width: 100%;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}

.session-item:hover,
.session-item.active {
  background: var(--bg-secondary);
}

.session-item.active {
  border: 1px solid var(--accent-blue);
}

.session-info {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex: 1;
  gap: 2px;
}

.session-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.15s;
  flex-shrink: 0;
}

.session-item:hover .delete-btn {
  opacity: 1;
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  text-align: center;
}

.tip {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>

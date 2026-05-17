<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createSession, getSession, streamMessage } from '../api/chat'
import ChatBubble from './ChatBubble.vue'
import ChatInput from './ChatInput.vue'
import SlotPromptCard from './SlotPromptCard.vue'
import type { ChatMessage as ChatMessageType, FollowUp, ProductAnalysisResult } from '../types/chat'

const props = defineProps<{
  activeSessionId: string
  products: ProductAnalysisResult[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:activeSessionId', val: string): void
  (e: 'update:loading', val: boolean): void
  (e: 'update:products', products: ProductAnalysisResult[]): void
  (e: 'view-detail', product: ProductAnalysisResult): void
}>()

type UiMessage = ChatMessageType & {
  follow_up?: FollowUp
  metadata?: string | Record<string, unknown> | null
}

const messages = ref<UiMessage[]>([])
const inputMessage = ref('')
const messagesContainer = ref<HTMLElement | null>(null)
const currentTitle = ref('新建对话')
const skipNextSessionLoad = ref('')
const pendingText = '正在理解你的需求...\n\n'

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

function rememberSession(sessionId: string) {
  const key = 'ps_chat_session_ids'
  const ids = JSON.parse(localStorage.getItem(key) || '[]')
  if (!ids.includes(sessionId)) {
    ids.unshift(sessionId)
    localStorage.setItem(key, JSON.stringify(ids.slice(0, 100)))
  }
}

async function ensureSession() {
  if (props.activeSessionId) return props.activeSessionId
  const sessionId = await createSession()
  rememberSession(sessionId)
  skipNextSessionLoad.value = sessionId
  emit('update:activeSessionId', sessionId)
  return sessionId
}

function normalizeHistoryMessage(message: UiMessage): UiMessage {
  if (message.follow_up) return message

  let metadata = message.metadata
  if (typeof metadata === 'string') {
    try {
      metadata = JSON.parse(metadata)
    } catch {
      metadata = null
    }
  }

  const followUp = (metadata as any)?.follow_up
  if (message.message_type === 'slot_prompt' && followUp) {
    return { ...message, follow_up: followUp }
  }
  return message
}

async function handleSend(message: string) {
  if (!message.trim() || props.loading) return

  let sessionId = ''
  try {
    sessionId = await ensureSession()
  } catch (e: any) {
    ElMessage.error('创建会话失败：' + (e.message || '未知错误'))
    return
  }

  messages.value.push({
    role: 'user',
    content: message,
    message_type: 'text',
  })
  let activeAssistantIndex = messages.value.push({
    role: 'assistant',
    content: pendingText,
    message_type: 'text',
  }) - 1

  currentTitle.value = message.slice(0, 24).replace(/\n/g, ' ')
  emit('update:products', [])
  scrollToBottom()

  emit('update:loading', true)
  try {
    await streamMessage(sessionId, message, (event, data) => {
      if (props.activeSessionId !== sessionId) return

      let assistant = messages.value[activeAssistantIndex]
      if (!assistant) return

      if (event === 'delta') {
        if (assistant.content === pendingText) assistant.content = ''
        assistant.content += data.content || ''
      } else if (event === 'follow_up') {
        assistant.content = data.question || ''
        assistant.message_type = 'slot_prompt'
        assistant.follow_up = {
          question: data.question || '',
          options: data.options || [],
          missing_slots: data.missing_slots || [],
        }
      } else if (event === 'report_start') {
        activeAssistantIndex = messages.value.push({
          role: 'assistant',
          content: '',
          message_type: 'report_card',
        }) - 1
        assistant = messages.value[activeAssistantIndex]
      } else if (event === 'report_delta') {
        assistant.content += data.content || ''
      } else if (event === 'products') {
        if (data.products?.length) {
          emit('update:products', data.products)
        }
      } else if (event === 'error') {
        assistant.message_type = 'text'
        if (assistant.content === pendingText) assistant.content = ''
        assistant.content += `\n\n${data.message || '分析失败'}`
      }

      scrollToBottom()
    })
  } catch (e: any) {
    if (props.activeSessionId === sessionId) {
      const assistant = messages.value[activeAssistantIndex]
      if (assistant) {
        assistant.message_type = 'text'
        assistant.content = '请求失败：' + (e.message || '未知错误')
      }
    }
    ElMessage.error('请求失败：' + (e.message || '未知错误'))
  } finally {
    emit('update:loading', false)
  }
}

function handleQuickReply(option: string) {
  handleSend(option)
}

async function loadSession(sessionId: string) {
  if (!sessionId) {
    messages.value = []
    currentTitle.value = '新建对话'
    return
  }

  if (skipNextSessionLoad.value === sessionId) {
    skipNextSessionLoad.value = ''
    return
  }

  try {
    const detail = await getSession(sessionId)
    messages.value = (detail.history || []).map((item) => normalizeHistoryMessage(item as UiMessage))
    currentTitle.value = detail.session?.title || '选品对话'
    scrollToBottom()
  } catch {
    messages.value = []
    currentTitle.value = '新建对话'
  }
}

watch(() => props.activeSessionId, loadSession, { immediate: true })
</script>

<template>
  <main class="chat-main">
    <header class="chat-header">
      <h2>{{ currentTitle }}</h2>
      <span v-if="loading" class="loading-indicator">分析中...</span>
    </header>

    <div ref="messagesContainer" class="messages-container">
      <div v-if="!messages.length" class="welcome">
        <div class="welcome-icon">
          <el-icon :size="48"><ChatDotRound /></el-icon>
        </div>
        <h3>电商选品 A2A 智能体</h3>
        <p>输入类目、季节、价格区间和偏好。信息不完整时，我会先追问补齐槽位，再调用多智能体分析。</p>
        <div class="quick-starters">
          <el-button
            size="small"
            @click="handleSend('夏季 家居小电器 100-300 元，高利润，低竞争')"
          >
            夏季家居小电器
          </el-button>
          <el-button
            size="small"
            @click="handleSend('推荐 5 个 Amazon 夏季高利润小家电，价格 100-300 元')"
          >
            Amazon 小家电
          </el-button>
        </div>
      </div>

      <template v-for="(msg, i) in messages" :key="i">
        <ChatBubble :message="msg" />
        <SlotPromptCard
          v-if="msg.message_type === 'slot_prompt' && msg.follow_up"
          :follow-up="msg.follow_up"
          @quick-reply="handleQuickReply"
        />
      </template>
    </div>

    <ChatInput
      v-model="inputMessage"
      :loading="loading"
      @send="handleSend"
    />
  </main>
</template>

<style scoped>
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-primary);
}

.chat-header {
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-card);
  flex-shrink: 0;
}

.chat-header h2 {
  font-size: 16px;
  font-weight: 600;
}

.loading-indicator {
  font-size: 13px;
  color: var(--accent-blue);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 60px 20px;
  color: var(--text-secondary);
}

.welcome-icon {
  margin-bottom: 16px;
  color: var(--accent-blue);
}

.welcome h3 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.welcome p {
  max-width: 520px;
  margin-bottom: 24px;
  line-height: 1.7;
}

.quick-starters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
</style>

import axios from 'axios'
import type { ChatResponse, SessionDetail, SessionSummary } from '../types/chat'

const API_BASE = import.meta.env.VITE_API_BASE || ''

const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,
})

export async function sendMessage(sessionId: string, message: string): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>('/api/chat/send', {
    session_id: sessionId,
    message,
  })
  return data
}

export type StreamEventHandler = (event: string, data: any) => void

export async function streamMessage(
  sessionId: string,
  message: string,
  onEvent: StreamEventHandler,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
    }),
  })

  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败：${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''

    for (const block of blocks) {
      const lines = block.split('\n')
      const eventLine = lines.find((line) => line.startsWith('event:'))
      const dataLine = lines.find((line) => line.startsWith('data:'))
      if (!eventLine || !dataLine) continue

      const event = eventLine.slice(6).trim()
      const raw = dataLine.slice(5).trim()
      try {
        onEvent(event, JSON.parse(raw))
      } catch {
        onEvent(event, { content: raw })
      }
    }
  }
}

export async function listSessions(sessionIds: string[]): Promise<SessionSummary[]> {
  const ids = sessionIds.join(',')
  const { data } = await api.get<{ status: string; data: SessionSummary[] }>('/api/chat/sessions', {
    params: { ids },
  })
  return data.data || []
}

export async function createSession(): Promise<string> {
  const { data } = await api.post<{ status: string; session_id: string }>('/api/chat/sessions')
  return data.session_id
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const { data } = await api.get<{ status: string; data: SessionDetail }>(`/api/chat/sessions/${sessionId}`)
  return data.data
}

export async function deleteSession(sessionId: string): Promise<void> {
  await api.delete(`/api/chat/sessions/${sessionId}`)
}

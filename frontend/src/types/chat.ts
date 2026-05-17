// 聊天相关类型

export interface ChatRequest {
  session_id: string
  message: string
}

export interface ChatMessage {
  role: string            // user / assistant / system
  content: string         // Markdown text
  message_type: string    // text / options / slot_prompt / product_card / report_card
  timestamp?: string
}

export interface FollowUp {
  question: string
  options: string[]
  missing_slots: string[]
}

export interface ChatResult {
  result_type: string
  products: ProductAnalysisResult[]
  report: string
  quick_actions: string[]
}

export interface ChatResponse {
  session_id: string
  message: ChatMessage
  follow_up: FollowUp | null
  result: ChatResult | null
}

// Session types
export interface SessionSummary {
  session_id: string
  title: string
  status: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface SessionDetail {
  session: SessionSummary
  history: ChatMessage[]
}

export interface AgentResult {
  agent: string
  product_id: number
  status: string
  scores: Record<string, number>
  summary: string
  details: Record<string, any>
  suggestions: string[]
  error: string | null
}

// Reuse existing product types
export interface ProductAnalysisResult {
  product_id: number
  product_name: string
  category: string
  final_score: number
  rank: number
  agent_results: Record<string, any>
  score_breakdown: Record<string, number>
  recommendation: string
  highlights: string[]
  risks: string[]
}

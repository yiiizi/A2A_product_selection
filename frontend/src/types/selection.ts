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

export interface ProductAnalysisResult {
  product_id: number
  product_name: string
  category: string
  final_score: number
  rank: number
  agent_results: Record<string, AgentResult>
  score_breakdown: Record<string, number>
  recommendation: string
  highlights: string[]
  risks: string[]
}

export interface SelectionReport {
  request_id: string
  query: string
  constraints: Record<string, any>
  products: ProductAnalysisResult[]
  final_report: string
  created_at: string
}

export interface SelectionResponse {
  status: string
  request_id: string
  data: SelectionReport
}

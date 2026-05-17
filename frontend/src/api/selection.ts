import axios from 'axios'
import type { SelectionResponse } from '../types/selection'

const API_BASE = import.meta.env.VITE_API_BASE || ''

const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,
})

export async function analyzeSelection(query: string, topK: number = 5): Promise<SelectionResponse> {
  const { data } = await api.post<SelectionResponse>('/api/selection/analyze', {
    query,
    top_k: topK,
  })
  return data
}

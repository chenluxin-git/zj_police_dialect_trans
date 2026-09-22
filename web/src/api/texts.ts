/**
 * 文本分配 API（对应后端 P-media T7 /api/texts）
 * - assign：领取一条文本（120s 惰性锁）；无可用文本时后端 404 + code=1，拦截器统一报错 reject
 * - refresh：续期分配（录音过程中防超时）
 * - release：放弃分配（「换一条」）
 * - custom：自定义文本入库即自动分配
 */
import { api } from "./http"

export interface AssignedText {
  text_id: number
  content: string
  category: string
  dialect: string
  region_code: string
  dialect_code: string
  remaining_seconds: number
}

export function assignText(category?: string) {
  if (category) {
    return api.post<AssignedText>("/texts/assign", undefined, { params: { category } })
  }
  return api.post<AssignedText>("/texts/assign")
}

export function refreshAssignment(textId: number) {
  return api.post<{ msg: string }>(`/texts/assign/${textId}/refresh`)
}

export function releaseAssignment(textId: number) {
  return api.delete<{ msg: string }>(`/texts/assign/${textId}`)
}

export function createCustomText(content: string) {
  return api.post<AssignedText>("/texts/custom", { content })
}

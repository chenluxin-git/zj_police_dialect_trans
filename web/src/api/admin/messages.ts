/**
 * 管理端消息发送 API（后端 P-admin-data T22：/admin/messages）
 */
import { api } from "../http"

export interface SentMessage {
  id: number
  title: string
  content: string
  created_at: string | null
  recipient_count: number
  read_count: number
}

export interface SentMessagePage {
  items: SentMessage[]
  total: number
  page: number
  page_size: number
}

/** 按单位多选的单位引用（名+区县码，后端据此收紧同名单位匹配） */
export interface StationRef {
  name: string
  region_code: string
}

export interface SendMessagePayload {
  target_type: "user" | "region" | "station"
  /** user=id；region=区域码；station=单位名（多选时传名数组，仅供审计可读，实际收件以 stations 为准） */
  target_value: number | string | string[]
  title: string
  content: string
  /** station 多选：[{name, region_code}]，提供时后端按 名+区县 匹配 */
  stations?: StationRef[]
}

export interface SendResult {
  sent: number
  skipped: number
}

export function sendMessage(payload: SendMessagePayload) {
  return api.post<SendResult>("/admin/messages", payload)
}

export function listSentMessages(params: { page?: number; page_size?: number } = {}) {
  return api.get<SentMessagePage>("/admin/messages", { params })
}

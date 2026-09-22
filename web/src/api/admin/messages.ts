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

export interface SendMessagePayload {
  target_type: "user" | "region" | "station"
  target_value: number | string
  title: string
  content: string
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

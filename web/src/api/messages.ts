/**
 * 站内消息 API（对应后端 P-social T13）
 */
import { api } from "./http"

export interface MessageItem {
  id: number
  title: string
  content: string
  read: boolean
  created_at: string
}

export interface MessageDetail extends MessageItem {
  sender_id: number | null
}

export interface MessagePage {
  items: MessageItem[]
  total: number
  page: number
  page_size: number
}

export function listMessages(params: { box?: string; page?: number; page_size?: number }) {
  return api.get<MessagePage>("/messages", { params })
}

export function getUnreadCount() {
  return api.get<{ count: number }>("/messages/unread-count")
}

export function getMessage(id: number) {
  return api.get<MessageDetail>(`/messages/${id}`)
}

export function readAllMessages() {
  return api.post<{ updated: number }>("/messages/read-all")
}

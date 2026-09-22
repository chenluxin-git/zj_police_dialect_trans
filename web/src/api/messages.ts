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

/** 四类消息 tag 映射（T31：后端无类型字段，前端按 title 前缀映射） */
export interface MessageTag {
  cls: string
  label: string
}

export function messageTag(title: string): MessageTag {
  if (title.startsWith("录音质检未通过")) return { cls: "zp-tag--danger", label: "质检" }
  if (title.startsWith("新任务")) return { cls: "zp-tag--navy", label: "任务" }
  if (title.includes("公告")) return { cls: "zp-tag--gold", label: "公告" }
  return { cls: "zp-tag--blue", label: "通知" }
}

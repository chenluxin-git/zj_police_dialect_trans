/**
 * 语音转译 API（对应后端 /api/transcriptions，工作台 + 历史共用）
 * - 上传 FormData(file)，入库即 pending，后台泵识别，前端 3s 轮询 ?ids= 批量取状态
 * - file_url 为 /api/... 全路径；试听用 fetchTranscriptionBlob 带 token 转 Blob
 * - fix/retry 返回整行 TranscriptionItem（corrected 为派生字段）
 */
import { api } from "./http"

export interface TranscriptionItem {
  id: number
  file_name: string
  file_ext: string
  file_size: number
  duration: number
  status: string // pending | processing | done | failed
  text_raw: string
  text_fixed: string
  corrected: boolean
  error_message: string
  created_at: string
  file_url: string
}

export interface TranscriptionPage {
  total: number
  page: number
  page_size: number
  items: TranscriptionItem[]
}

export interface ListTranscriptionsParams {
  status?: string
  corrected?: boolean
  file_ext?: string
  q?: string
  /** 逗号分隔 id 批量轮询（后端 ≤50） */
  ids?: string
  /** 1 = 仅 pending/processing（工作台刷新后水化在途队列） */
  active?: number
  page?: number
  page_size?: number
}

export function listTranscriptions(params: ListTranscriptionsParams = {}) {
  return api.get<TranscriptionPage>("/transcriptions", { params })
}

export function fetchTranscription(id: number) {
  return api.get<TranscriptionItem>(`/transcriptions/${id}`)
}

/** 上传即入队（返回 pending 行，工作台 unshift 进会话队列）。
 * 大文件 + 后端 ffmpeg 转码耗时可观：单独放宽本请求超时（全局默认 30s）。 */
export function uploadTranscription(file: File | Blob, filename: string) {
  const form = new FormData()
  form.append("file", file, filename)
  return api.post<TranscriptionItem>("/transcriptions", form, { timeout: 300000 })
}

/** 带 token 拉取音频 Blob（file_url 为 /api/... 全路径，剥离 /api 复用 baseURL；管理端复用） */
export function fetchTranscriptionBlob(fileUrl: string) {
  return api.get<Blob>(fileUrl.replace(/^\/api/, ""), { responseType: "blob" })
}

/** 修正识别结果：text 与 text_raw 相同即撤销修正（后端回 ""） */
export function fixTranscription(id: number, text: string) {
  return api.post<TranscriptionItem>(`/transcriptions/${id}/fix`, { text })
}

/** 重试失败识别：回置 pending、清结果字段 */
export function retryTranscription(id: number) {
  return api.post<TranscriptionItem>(`/transcriptions/${id}/retry`)
}

export function deleteTranscription(id: number) {
  return api.delete<{ msg: string }>(`/transcriptions/${id}`)
}

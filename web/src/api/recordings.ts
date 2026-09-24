/**
 * 录音 API（对应后端 P-media T8 /api/recordings）
 * - 上传 FormData(file + text_id)，入库即 pending
 * - file_url 为 /api/... 全路径；试听/下载用 fetchRecordingBlob 带 token 转 Blob
 */
import { api } from "./http"

export interface RecordingItem {
  id: number
  text_id: number
  text_content: string
  category: string
  dialect: string
  duration: number
  file_size: number
  qc_status: string
  created_at: string
  file_url: string
}

export interface RecordingPage {
  total: number
  page: number
  page_size: number
  items: RecordingItem[]
}

export interface UploadResult {
  id: number
  duration: number
  file_size: number
  qc_status: string
}

export interface ListRecordingsParams {
  category?: string
  q?: string
  qc_status?: string
  page?: number
  page_size?: number
}

export function listMyRecordings(params: ListRecordingsParams = {}) {
  return api.get<RecordingPage>("/recordings", { params })
}

export function uploadRecording(file: Blob, textId: number) {
  const form = new FormData()
  form.append("file", file, "recording.webm")
  form.append("text_id", String(textId))
  return api.post<UploadResult>("/recordings", form)
}

export function deleteRecording(id: number) {
  return api.delete<{ msg: string }>(`/recordings/${id}`)
}

/** 带 token 拉取音频 Blob（file_url 为 /api/... 全路径，剥离 /api 复用 baseURL） */
export function fetchRecordingBlob(fileUrl: string) {
  return api.get<Blob>(fileUrl.replace(/^\/api/, ""), { responseType: "blob" })
}

/** 质检流水行（原文/转译/相似度对比，result=error 时 similarity 为 null） */
export interface QcLogItem {
  id: number
  result: "passed" | "failed" | "error"
  similarity: number | null
  asr_text: string
  text_content: string
  error_message: string
  created_at: string
}

/** 质检详情：按 (user, text) 聚合的全历史（含重录替换旧行前的流水） */
export interface QcDetail {
  recording_id: number
  text_id: number
  text_content: string
  items: QcLogItem[]
}

export function fetchRecordingQc(id: number) {
  return api.get<QcDetail>(`/recordings/${id}/qc`)
}

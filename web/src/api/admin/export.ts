/**
 * 管理端录音/标注/数据集导出 API（后端 P-admin-data T18 + P-export T23）
 * - 录音管理列表（qc_status 筛选，试听/下载复用 /api/recordings/{id}/file 转 Blob）
 * - 标注管理列表/删除（音频流 /api/audio/files/{id}/file）
 * - 数据集导出（两源合并清单、导出所选/全部、任务轮询、下载即焚）
 */
import { api } from "../http"

/** 带 token 拉取音频 Blob（file_url 为 /api/... 全路径，剥离 /api 复用 baseURL） */
export function fetchAudioBlob(fileUrl: string) {
  return api.get<Blob>(fileUrl.replace(/^\/api/, ""), { responseType: "blob" })
}

// ---------- 录音管理（T18） ----------

export interface AdminRecording {
  id: number
  user_id: number
  user_name: string
  text_content: string
  category: string
  dialect: string
  region_code: string
  duration: number
  file_size: number
  qc_status: string
  created_at: string | null
  file_url: string
}

export interface AdminRecordingPage {
  items: AdminRecording[]
  total: number
  page: number
  page_size: number
}

export interface AdminRecordingQuery {
  region?: string
  category?: string
  q?: string
  qc_status?: string
  page?: number
  page_size?: number
}

export function listAdminRecordings(params: AdminRecordingQuery = {}) {
  return api.get<AdminRecordingPage>("/admin/recordings", { params })
}

// ---------- 标注管理（T18） ----------

export interface AdminAnnotation {
  id: number
  file_id: number
  annotator_id: number
  annotator_name: string
  is_dialect: boolean
  translation: string | null
  region_code: string
  file_name: string
  created_at: string | null
}

export interface AdminAnnotationPage {
  items: AdminAnnotation[]
  total: number
  page: number
  page_size: number
}

export interface AdminAnnotationQuery {
  region?: string
  is_dialect?: boolean
  q?: string
  page?: number
  page_size?: number
}

export function listAdminAnnotations(params: AdminAnnotationQuery = {}) {
  return api.get<AdminAnnotationPage>("/admin/annotations", { params })
}

export function deleteAnnotation(id: number) {
  return api.delete<{ msg: string }>(`/admin/annotations/${id}`)
}

// ---------- 数据集导出（T23） ----------

export interface ExportListItem {
  id: number
  source: string // recording | audio_file
  text_or_name: string
  category: string
  region_code: string
  dialect_code: string
  translation: string | null
  user_real_name: string
  duration: number
  created_at: string
}

export interface ExportListPage {
  total: number
  page: number
  page_size: number
  items: ExportListItem[]
}

export interface ExportListQuery {
  region?: string
  category?: string
  dialect?: string
  annotated?: boolean
  page?: number
  page_size?: number
}

export function listExportAudio(params: ExportListQuery = {}) {
  return api.get<ExportListPage>("/admin/export/audio-list", { params })
}

export interface ExportCreated {
  task_id: number
}

export function exportSelected(items: { source: string; id: number }[]) {
  return api.post<ExportCreated>("/admin/export/audio", { items })
}

export function exportAll(payload: {
  region?: string
  category?: string
  dialect?: string
  annotated?: boolean
}) {
  return api.post<ExportCreated>("/admin/export/audio-all", payload)
}

export interface ExportTaskStatus {
  status: string // pending | processing | completed | failed
  total_count: number
  processed_count: number
  file_url: string | null
}

export function getExportTask(taskId: number) {
  return api.get<ExportTaskStatus>(`/admin/export/task/${taskId}`)
}

export function downloadExport(taskId: number) {
  return api.get<Blob>(`/admin/export/download/${taskId}`, { responseType: "blob" })
}

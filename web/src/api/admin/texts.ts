/**
 * 管理端文本线 + 音频入库 API（后端 P-admin-content T16/T17/T19）
 * - 文本导入（txt/docx 模板下载、后台任务轮询、句号切分）
 * - 导入台账（列表/详情/撤销）
 * - 文本管理（列表/批量删除回显 skipped）
 * - 音频上传（多文件 FormData）/ 音频扫盘（后台任务轮询 + 统计格）
 * 另附 listRegions 复用公开 /regions 端点，供「归属区域」选择（super_admin 可指定）。
 */
import { api } from "../http"

// ---------- 区域（复用公开 /regions） ----------

export interface RegionItem {
  code: string
  name: string
  level: string
  parent_code: string | null
  sort_order?: number
}

export function listRegions() {
  return api.get<RegionItem[]>("/regions")
}

// ---------- 文本导入 ----------

export interface TextImportStart {
  task_id: number
}

export function importTexts(form: FormData) {
  return api.post<TextImportStart>("/admin/texts/import", form)
}

export interface TextImportPoll {
  task_id: number
  status: string // pending | processing | completed | failed
  error_message: string | null
  total_count: number
}

export function pollTextImport(taskId: number) {
  return api.get<TextImportPoll>(`/admin/texts/import/${taskId}`)
}

export function downloadTextTemplate(fmt: "txt" | "docx") {
  return api.get<Blob>(`/admin/texts/template/${fmt}`, { responseType: "blob" })
}

// ---------- 导入台账 ----------

export interface ImportManageItem {
  id: number
  status: string
  file_name: string
  category: string
  region_code: string
  total_count: number
  error_message: string | null
  created_at: string
}

export interface ImportManagePage {
  total: number
  page: number
  page_size: number
  items: ImportManageItem[]
}

export function listImportManage(params: { page?: number; page_size?: number } = {}) {
  return api.get<ImportManagePage>("/admin/text-import-manage", { params })
}

export interface ImportManageDetail extends ImportManageItem {
  sample_texts: string[]
}

export function getImportManageDetail(taskId: number) {
  return api.get<ImportManageDetail>(`/admin/text-import-manage/${taskId}`)
}

export function undoImport(taskId: number) {
  return api.delete<{ deleted: number }>(`/admin/text-import-manage/${taskId}`)
}

// ---------- 文本管理 ----------

export interface AdminText {
  id: number
  content: string
  dialect: string
  category: string
  region_code: string
  dialect_code: string
  created_at: string
}

export interface AdminTextPage {
  total: number
  page: number
  page_size: number
  items: AdminText[]
}

export interface AdminTextQuery {
  category?: string
  region_code?: string
  q?: string
  date_start?: string
  date_end?: string
  page?: number
  page_size?: number
}

export function listAdminTexts(params: AdminTextQuery = {}) {
  return api.get<AdminTextPage>("/admin/texts", { params })
}

export interface TextBatchDeleteResult {
  deleted: number[]
  skipped: number[]
}

export function deleteTextsBatch(ids: number[]) {
  return api.delete<TextBatchDeleteResult>("/admin/texts/batch", { data: { ids } })
}

// ---------- 音频上传 ----------

export interface AudioUploadResultItem {
  file_name: string
  id?: number
  error?: string
}

export interface AudioUploadResult {
  imported: number
  results: AudioUploadResultItem[]
}

export function uploadAudio(form: FormData) {
  return api.post<AudioUploadResult>("/admin/audio/upload", form)
}

// ---------- 音频扫盘 ----------

export interface AudioScanStart {
  task_id: number
}

export interface AudioScanPayload {
  server_path: string
  recursive: boolean
  region_code?: string
}

export function startAudioScan(payload: AudioScanPayload) {
  return api.post<AudioScanStart>("/admin/audio/import", payload)
}

export interface AudioScanFailItem {
  path: string
  error: string
}

export interface AudioScanPoll {
  task_id: number
  status: string
  error_message: string | null
  found: number
  imported: number
  skipped: number
  failed: AudioScanFailItem[]
}

export function pollAudioScan(taskId: number) {
  return api.get<AudioScanPoll>(`/admin/audio/import/${taskId}`)
}

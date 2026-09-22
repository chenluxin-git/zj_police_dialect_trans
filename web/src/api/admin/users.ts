/**
 * 管理端用户管理 API（后端 P-admin-users T14+T15：/admin/users）
 */
import { api } from "../http"

export interface TaskProgress {
  type: string
  target_count: number
  base_count: number
  done: number
  status: string
  note: string
}

export interface UserItem {
  id: number
  phone: string
  real_name: string
  role: string // user | admin | super_admin
  region_code: string
  region_name: string
  police_station: string
  created_at: string | null
  recording_count: number
  annotation_count: number
  task_progress: TaskProgress | null
}

export interface UserPage {
  items: UserItem[]
  total: number
  page: number
  page_size: number
}

export interface UserQuery {
  real_name?: string
  phone?: string
  role?: string
  region_code?: string
  station?: string
  page?: number
  page_size?: number
}

export interface UserCreatePayload {
  phone: string
  real_name: string
  region_code: string
  police_station?: string
  role?: string
}

export interface UserUpdatePayload {
  real_name?: string
  region_code?: string
  police_station?: string
  role?: string
  password?: string
}

export interface ImportDetailRow {
  phone: string
  ok: boolean
  msg: string
}

export interface ImportStatus {
  batch_id: number
  file_name: string
  status: string // processing | completed
  total: number
  success: number
  fail: number
  detail: ImportDetailRow[]
}

export function listUsers(params: UserQuery = {}) {
  return api.get<UserPage>("/admin/users", { params })
}

export function createUser(payload: UserCreatePayload) {
  return api.post<{ id: number }>("/admin/users", payload)
}

export function updateUser(id: number, payload: UserUpdatePayload) {
  return api.put<unknown>(`/admin/users/${id}`, payload)
}

export function deleteUser(id: number) {
  return api.delete<unknown>(`/admin/users/${id}`)
}

export function exportUsers(params: UserQuery = {}) {
  return api.get<Blob>("/admin/users/export", { params, responseType: "blob" })
}

export function importUsers(file: File) {
  const fd = new FormData()
  fd.append("file", file)
  return api.post<{ batch_id: number }>("/admin/users/import", fd)
}

export function getImportStatus(batchId: number) {
  return api.get<ImportStatus>(`/admin/users/import/${batchId}`)
}

export function downloadImportTemplate() {
  return api.get<Blob>("/admin/users/import-template", { responseType: "blob" })
}

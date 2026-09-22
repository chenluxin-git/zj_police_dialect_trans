/**
 * 管理端任务管理 API（后端 P-admin-data T21：/admin/tasks）
 */
import { api } from "../http"

export interface TaskItem {
  id: number
  user_id: number
  real_name: string
  police_station: string
  type: string // recording | annotation
  target_count: number
  base_count: number
  done: number
  status: string // active | cancelled
  note: string
  created_at: string | null
}

export interface TaskPage {
  items: TaskItem[]
  total: number
  page: number
  page_size: number
}

export interface TaskQuery {
  real_name?: string
  type?: string
  status?: string
  page?: number
  page_size?: number
}

export interface TaskAssignPayload {
  user_id: number
  type: string
  target_count: number
  note?: string
}

export interface TaskBatchPayload {
  user_ids: number[]
  type: string
  target_count: number
  note?: string
}

export interface TaskUpdatePayload {
  target_count?: number
  note?: string
  status?: string
}

export function listTasks(params: TaskQuery = {}) {
  return api.get<TaskPage>("/admin/tasks", { params })
}

export function assignTask(payload: TaskAssignPayload) {
  return api.post<unknown>("/admin/tasks", payload)
}

export function assignTaskBatch(payload: TaskBatchPayload) {
  return api.post<unknown>("/admin/tasks/batch", payload)
}

export function updateTask(id: number, payload: TaskUpdatePayload) {
  return api.put<unknown>(`/admin/tasks/${id}`, payload)
}

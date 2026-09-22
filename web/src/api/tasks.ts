/**
 * 我的任务进度 API（对应后端 P-social T12 /api/tasks/my）
 * data: { recording, annotation }，各自为 null（无 active 任务）或进度载荷
 */
import { api } from "./http"

export interface TaskProgress {
  target_count: number
  base_count: number
  done: number
  status: string
  note: string
}

export interface MyTasks {
  recording: TaskProgress | null
  annotation: TaskProgress | null
}

export function getMyTasks() {
  return api.get<MyTasks>("/tasks/my")
}

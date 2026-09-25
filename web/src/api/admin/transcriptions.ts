/**
 * 管理端转译记录 API（后端 /api/admin/transcriptions，层级辖区列表：本级+下级全部）
 * - 仅列表 + 播放（试听复用用户侧 /api/transcriptions/{id}/file，管理员 scope 已放行）
 * - 行含录制人 user_name / 区域 region_name；corrected 由 text_fixed 派生（后端未算好，前端判空）
 * - region 筛选支持省/市码整域（后端 BFS 展开 ∩ scope）
 */
import { api } from "../http"

export interface AdminTranscription {
  id: number
  user_id: number
  user_name: string
  region_code: string
  region_name: string
  file_name: string
  file_ext: string
  file_size: number
  duration: number
  status: string // pending | processing | done | failed
  text_raw: string
  text_fixed: string
  error_message: string
  created_at: string | null
  file_url: string
}

export interface AdminTranscriptionPage {
  items: AdminTranscription[]
  total: number
  page: number
  page_size: number
}

export interface AdminTranscriptionQuery {
  region?: string
  status?: string
  corrected?: boolean
  file_ext?: string
  q?: string
  page?: number
  page_size?: number
}

export function listAdminTranscriptions(params: AdminTranscriptionQuery = {}) {
  return api.get<AdminTranscriptionPage>("/admin/transcriptions", { params })
}

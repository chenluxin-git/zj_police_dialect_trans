/**
 * 管理端数据总览 API（后端 P-admin-data T20：GET /admin/stats/overview）
 * 响应已含 category_counts（类别分布条形图直接消费，后端一次做齐）。
 */
import { api } from "../http"

export interface RegionStatRow {
  code: string
  name: string
  users: number
  recordings: number
  seconds: number
  size_bytes: number
  texts: number
  audio_files: number
  annotated: number
}

export interface OverviewTasks {
  target_sum: number
  done_sum: number
  rate: number
  started: number
  not_started: number
}

export interface Overview {
  level: string | null
  rows: RegionStatRow[]
  total: RegionStatRow
  tasks: OverviewTasks
  category_counts: Record<string, number>
}

export function getOverview(regionCode?: string, by?: "region" | "station") {
  return api.get<Overview>("/admin/stats/overview", {
    params: {
      ...(regionCode ? { region_code: regionCode } : {}),
      ...(by ? { by } : {}),
    },
  })
}

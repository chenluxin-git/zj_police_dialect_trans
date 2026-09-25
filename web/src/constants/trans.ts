/**
 * 语音转译状态/筛选常量（工作台 + 历史 + 管理端三页共用）
 * - status 生命周期：pending（排队中）→ processing（识别中）→ done / failed
 * - corrected 为人工修正金标（text_fixed 非空）；识别结果展示一律 displayText()
 */

export interface TransStatusMeta {
  label: string
  cls: string
}

const META: Record<string, TransStatusMeta> = {
  pending: { label: "排队中", cls: "zp-tag--gray" },
  processing: { label: "识别中", cls: "zp-tag--blue" },
  done: { label: "完成", cls: "zp-tag--green" },
  failed: { label: "失败", cls: "zp-tag--danger" },
}

export function transLabel(status: string): string {
  return META[status]?.label || status || "—"
}

export function transTagClass(status: string): string {
  return META[status]?.cls || "zp-tag--gray"
}

/** 民警端筛选（历史页）：全部 / 完成 / 已修正 / 失败 */
export const TRANS_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "done", label: "完成" },
  { value: "done_fixed", label: "已修正" },
  { value: "failed", label: "失败" },
]

/** 管理端筛选：比民警端多 排队中 / 识别中 */
export const TRANS_ADMIN_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "排队中" },
  { value: "processing", label: "识别中" },
  { value: "done", label: "完成" },
  { value: "done_fixed", label: "已修正" },
  { value: "failed", label: "失败" },
]

/** 文件类型筛选（与后端白名单一致） */
export const TRANS_EXT_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "wav", label: "WAV" },
  { value: "mp3", label: "MP3" },
  { value: "m4a", label: "M4A" },
  { value: "webm", label: "WEBM" },
  { value: "mp4", label: "MP4" },
  { value: "mov", label: "MOV" },
]

/** 工作台轮询间隔（毫秒），与后端 trans_scan_interval=3s 对齐 */
export const TRANS_POLL_INTERVAL = 3000

/** 上传大小上限（MB，与后端 TRANS_MAX_BYTES 一致，前端预检先行提示） */
export const TRANS_MAX_MB = 100

/** 音频时长上限（分钟，与后端 TRANS_MAX_DURATION 一致） */
export const TRANS_MAX_MINUTES = 15

/** 扩展名白名单（input accept 与前端预检共用） */
export const TRANS_ALLOWED_EXTS = ["wav", "mp3", "m4a", "webm", "mp4", "mov"]

/** 识别结果展示：人工修正优先，未修正回退原始识别 */
export function displayText(it: { text_fixed?: string | null; text_raw?: string | null }): string {
  return (it.text_fixed || "") !== "" ? (it.text_fixed as string) : (it.text_raw || "")
}

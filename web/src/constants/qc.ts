/**
 * 录音质检状态（P0 公用件）
 *
 * 原本在 2 个页面里各抄了一份：admin/RecordingsView（三态）与 MyRecordingsView（两态）。
 * 注意两者口径不同是**刻意的**：
 * - 管理端能看到 failed（未通过），因为要审计被质检拦下的录音；
 * - 民警端看不到 failed，因为未通过的录音已自动移除并通过消息通知重录（见 README）。
 * 所以这里提供三态全集 + 民警端两态子集，而不是强行合成一套。
 */

export interface QcStatusMeta {
  label: string
  cls: string
}

const META: Record<string, QcStatusMeta> = {
  pending: { label: "待质检", cls: "zp-tag--warn" },
  passed: { label: "已通过", cls: "zp-tag--green" },
  failed: { label: "未通过", cls: "zp-tag--danger" },
}

/** 管理端筛选下拉：待质检 / 已通过 / 未通过 */
export const QC_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "待质检" },
  { value: "passed", label: "已通过" },
  { value: "failed", label: "未通过" },
]

/** 民警端筛选下拉：待质检 / 已通过（未通过的录音民警看不到） */
export const QC_MINE_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "待质检" },
  { value: "passed", label: "已通过" },
]

export function qcLabel(status: string): string {
  return META[status]?.label || status || "—"
}

export function qcTagClass(status: string): string {
  return META[status]?.cls || "zp-tag--gray"
}

/**
 * 录音质检状态（P0 公用件）
 *
 * 原本在 2 个页面里各抄了一份：admin/RecordingsView 与 MyRecordingsView，现统一为一套。
 * - failed（未通过）行保留在两端列表：民警可筛选、试听、查看质检对比详情；
 *   对应文本已释放回池，重新领取后上传会替换掉旧的 failed 行；
 * - error 只出现在质检流水（qc_logs，录音行保持 pending 重试），供对比弹窗展示。
 */

export interface QcStatusMeta {
  label: string
  cls: string
}

const META: Record<string, QcStatusMeta> = {
  pending: { label: "待质检", cls: "zp-tag--warn" },
  passed: { label: "已通过", cls: "zp-tag--green" },
  failed: { label: "未通过", cls: "zp-tag--danger" },
  error: { label: "接口异常", cls: "zp-tag--warn" },
}

/** 管理端筛选下拉：待质检 / 已通过 / 未通过 */
export const QC_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "待质检" },
  { value: "passed", label: "已通过" },
  { value: "failed", label: "未通过" },
]

/** 民警端筛选下拉：待质检 / 已通过 / 未通过 */
export const QC_MINE_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "待质检" },
  { value: "passed", label: "已通过" },
  { value: "failed", label: "未通过" },
]

export function qcLabel(status: string): string {
  return META[status]?.label || status || "—"
}

export function qcTagClass(status: string): string {
  return META[status]?.cls || "zp-tag--gray"
}

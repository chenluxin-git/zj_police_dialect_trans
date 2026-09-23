/**
 * 文本类别枚举（P0 公用件）
 *
 * 原本在 4 个页面里各抄了一份：RecordingsView / TextsView / TextImportManageView / ExportView。
 * 且 TextImportView 的导入类别数组漏了 custom（自定义），与「文本管理」的 6 项列表不一致 —— 这里统一。
 */

export interface CategoryOption {
  value: string
  label: string
}

/** 含「全部类别」空值项，用于筛选下拉 */
export const CATEGORY_OPTIONS: CategoryOption[] = [
  { value: "", label: "全部类别" },
  { value: "police", label: "警情" },
  { value: "life", label: "生活" },
  { value: "dirty", label: "俚语" },
  { value: "place", label: "地名" },
  { value: "custom", label: "自定义" },
]

/** 不含空值项，用于「导入时选择类别」等必须选具体类别的场景 */
export const CATEGORY_PICK_OPTIONS: CategoryOption[] = CATEGORY_OPTIONS.filter((c) => c.value !== "")

const LABEL: Record<string, string> = {
  police: "警情",
  life: "生活",
  dirty: "俚语",
  place: "地名",
  custom: "自定义",
}

const TAG_CLASS: Record<string, string> = {
  police: "zp-tag--blue",
  life: "zp-tag--green",
  dirty: "zp-tag--warn",
  place: "zp-tag--gold",
  custom: "zp-tag--gray",
}

export function categoryLabel(code: string): string {
  return LABEL[code] || code || "—"
}

export function categoryTagClass(code: string): string {
  return TAG_CLASS[code] || "zp-tag--gray"
}

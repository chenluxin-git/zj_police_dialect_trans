<script setup lang="ts">
/**
 * 文本管理（dome/admin-texts.html 1:1）：类别/日期区间/关键词筛选 + checkbox 表
 * + 批量删除（后端回显 skipped 明细：被录音引用/越界自动跳过）
 */
import { computed, onMounted, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import {
  deleteTextsBatch,
  listAdminTexts,
  listRegions,
  type AdminText,
  type RegionItem,
} from "@/api/admin/texts"

const CATEGORIES = [
  { value: "", label: "全部类别" },
  { value: "police", label: "警情" },
  { value: "life", label: "生活" },
  { value: "dirty", label: "俚语" },
  { value: "place", label: "地名" },
  { value: "custom", label: "自定义" },
]
const CAT_TAG: Record<string, string> = {
  police: "zp-tag--blue",
  life: "zp-tag--green",
  dirty: "zp-tag--warn",
  place: "zp-tag--gold",
  custom: "zp-tag--gray",
}
const catLabel = (c: string) =>
  ({ police: "警情", life: "生活", dirty: "俚语", place: "地名", custom: "自定义" }[c] || c)

const items = ref<AdminText[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const regions = ref<RegionItem[]>([])

const category = ref("")
const dateStart = ref("")
const dateEnd = ref("")
const keyword = ref("")

const selected = ref<Set<number>>(new Set())
const allChecked = computed(
  () => items.value.length > 0 && items.value.every((t) => selected.value.has(t.id)),
)

const regionName = (code: string) => regions.value.find((r) => r.code === code)?.name || code

function fmtDateTime(iso: string) {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    const data = await listAdminTexts({
      category: category.value || undefined,
      q: keyword.value || undefined,
      date_start: dateStart.value || undefined,
      date_end: dateEnd.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}
function reset() {
  category.value = ""
  dateStart.value = ""
  dateEnd.value = ""
  keyword.value = ""
  page.value = 1
  void load()
}
function toggleAll() {
  if (allChecked.value) {
    items.value.forEach((t) => selected.value.delete(t.id))
  } else {
    items.value.forEach((t) => selected.value.add(t.id))
  }
  selected.value = new Set(selected.value)
}
function toggleOne(id: number) {
  if (selected.value.has(id)) selected.value.delete(id)
  else selected.value.add(id)
  selected.value = new Set(selected.value)
}

async function batchDelete() {
  const ids = [...selected.value]
  if (!ids.length) {
    ElMessage.warning("请先勾选要删除的文本")
    return
  }
  await ElMessageBox.confirm(
    `已选择 ${ids.length} 条文本，确定删除吗？`,
    "批量删除文本",
    {
      confirmButtonText: "确认删除",
      cancelButtonText: "取消",
      type: "warning",
    },
  )
  const data = await deleteTextsBatch(ids)
  selected.value = new Set()
  if (data.skipped.length) {
    ElMessage.warning(`已删除 ${data.deleted.length} 条，跳过 ${data.skipped.length} 条（被录音引用或越界）`)
  } else {
    ElMessage.success(`已删除 ${data.deleted.length} 条`)
  }
  void load()
}

onMounted(async () => {
  try {
    regions.value = await listRegions()
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
  void load()
})
</script>

<template>
  <div class="zp-content" style="padding: 0">
    <div class="zp-page-head">
      <h1>文本管理</h1>
      <span class="sub">辖区朗读文本库 · 被录音引用的文本不可删除</span>
      <div class="zp-head-actions">
        <button class="zp-btn zp-btn--danger" type="button" @click="batchDelete">批量删除</button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="zp-filter">
      <select class="zp-select" v-model="category" aria-label="类别">
        <option v-for="c in CATEGORIES" :key="c.value" :value="c.value">{{ c.label }}</option>
      </select>
      <input class="zp-input" type="date" v-model="dateStart" aria-label="开始日期" />
      <span class="zp-text-3" style="padding-top: 8px">至</span>
      <input class="zp-input" type="date" v-model="dateEnd" aria-label="结束日期" />
      <input class="zp-input" v-model="keyword" placeholder="文本关键词" aria-label="文本关键词" @keyup.enter="search" />
      <button class="zp-btn zp-btn--primary" type="button" @click="search">查询</button>
      <button class="zp-btn zp-btn--ghost" type="button" @click="reset">重置</button>
    </div>

    <!-- 列表 -->
    <div class="zp-card">
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th style="width: 36px">
                <input type="checkbox" :checked="allChecked" @change="toggleAll" />
              </th>
              <th style="width: 42%">文本内容</th>
              <th>类别</th>
              <th>区域</th>
              <th>导入时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id">
              <td><input type="checkbox" :checked="selected.has(row.id)" @change="toggleOne(row.id)" /></td>
              <td>{{ row.content }}</td>
              <td><span class="zp-tag" :class="CAT_TAG[row.category] || 'zp-tag--gray'">{{ catLabel(row.category) }}</span></td>
              <td>{{ regionName(row.region_code) }}</td>
              <td class="num">{{ fmtDateTime(row.created_at) }}</td>
            </tr>
            <tr v-if="!loading && items.length === 0">
              <td colspan="5" style="color: var(--ink-3); padding: 32px; text-align: center">暂无文本记录</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style="padding: 14px 20px; display: flex; justify-content: flex-end">
        <el-pagination
          background
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="(p: number) => { page = p; load() }"
        />
      </div>
    </div>
  </div>
</template>

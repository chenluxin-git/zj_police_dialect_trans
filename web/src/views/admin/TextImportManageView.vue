<script setup lang="ts">
/**
 * 导入台账（dome/admin-text-import-manage.html 1:1）：批次表 + 详情 dialog 样本文本
 * + 撤销（后端 409「被录音引用拒撤」由拦截器透出提示）
 */
import { onMounted, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import {
  getImportManageDetail,
  listImportManage,
  listRegions,
  undoImport,
  type ImportManageDetail,
  type ImportManageItem,
  type RegionItem,
} from "@/api/admin/texts"

const CAT_TAG: Record<string, string> = {
  police: "zp-tag--blue",
  life: "zp-tag--green",
  dirty: "zp-tag--warn",
  place: "zp-tag--gold",
  custom: "zp-tag--gray",
}
const catLabel = (c: string) =>
  ({ police: "警情", life: "生活", dirty: "俚语", place: "地名", custom: "自定义" }[c] || c)

const STATUS_TAG: Record<string, { label: string; cls: string }> = {
  pending: { label: "排队中", cls: "zp-tag--gray" },
  processing: { label: "解析中", cls: "zp-tag--warn" },
  completed: { label: "完成", cls: "zp-tag--green" },
  failed: { label: "失败", cls: "zp-tag--danger" },
}

const items = ref<ImportManageItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const regions = ref<RegionItem[]>([])

const detail = ref<ImportManageDetail | null>(null)
const detailVisible = ref(false)

const regionName = (code: string) => regions.value.find((r) => r.code === code)?.name || code

function fmtDateTime(iso: string) {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    const data = await listImportManage({ page: page.value, page_size: pageSize })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function openDetail(row: ImportManageItem) {
  try {
    detail.value = await getImportManageDetail(row.id)
    detailVisible.value = true
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

async function revoke(row: ImportManageItem) {
  await ElMessageBox.confirm(
    `确定撤销「${row.file_name}（${row.total_count} 条）」吗？该批文本将整批删除。`,
    "撤销导入",
    {
      confirmButtonText: "确认撤销",
      cancelButtonText: "取消",
      type: "warning",
      distinguishCancelAndClose: true,
    },
  )
  const data = await undoImport(row.id)
  ElMessage.success(`已撤销，删除 ${data.deleted} 条`)
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
      <h1>导入台账</h1>
      <span class="sub">历史导入批次，可查看样本文本；未被录音引用的批次可整批撤销</span>
    </div>

    <div class="zp-card">
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>类别</th>
              <th>区域</th>
              <th>导入条数</th>
              <th>状态</th>
              <th>导入时间</th>
              <th class="zp-text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id" :style="row.status === 'failed' ? 'opacity:.62' : ''">
              <td class="num">{{ row.file_name }}</td>
              <td><span class="zp-tag" :class="CAT_TAG[row.category] || 'zp-tag--gray'">{{ catLabel(row.category) }}</span></td>
              <td>{{ regionName(row.region_code) }}</td>
              <td class="num">{{ row.total_count }}</td>
              <td>
                <span class="zp-tag" :class="STATUS_TAG[row.status]?.cls || 'zp-tag--gray'">
                  {{ STATUS_TAG[row.status]?.label || row.status }}
                </span>
              </td>
              <td class="num">{{ fmtDateTime(row.created_at) }}</td>
              <td class="zp-text-right">
                <button v-if="row.status === 'completed'" class="zp-btn zp-btn--text" type="button" @click="openDetail(row)">详情</button>
                <button v-if="row.status === 'completed'" class="zp-btn zp-btn--text is-danger" type="button" @click="revoke(row)">撤销</button>
                <button v-else-if="row.status === 'processing' || row.status === 'pending'" class="zp-btn zp-btn--text" type="button" @click="load">刷新</button>
                <span v-else class="zp-text-3">{{ row.error_message || "—" }}</span>
              </td>
            </tr>
            <tr v-if="!loading && items.length === 0">
              <td colspan="7" style="color: var(--ink-3); padding: 32px; text-align: center">暂无导入批次</td>
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

    <!-- 批次详情 -->
    <el-dialog v-model="detailVisible" width="560px">
      <template #header>
        <h3 style="font-size: 16px; font-weight: 600">{{ detail?.file_name }}</h3>
      </template>
      <div v-if="detail" class="zp-dialog-body" style="padding: 0">
        <p class="zp-text-3" style="margin-bottom: 12px">
          {{ catLabel(detail.category) }} · {{ regionName(detail.region_code) }} · {{ detail.total_count }} 条 ·
          {{ fmtDateTime(detail.created_at) }} 导入 · 样本（前 {{ detail.sample_texts.length }} 条）：
        </p>
        <ul class="zp-line-list" v-if="detail.sample_texts.length">
          <li v-for="(s, i) in detail.sample_texts" :key="i"><span class="txt">{{ s }}</span></li>
        </ul>
        <p v-else class="zp-text-3">暂无样本</p>
      </div>
      <template #footer>
        <button class="zp-btn zp-btn--primary" type="button" @click="detailVisible = false">关闭</button>
      </template>
    </el-dialog>
  </div>
</template>

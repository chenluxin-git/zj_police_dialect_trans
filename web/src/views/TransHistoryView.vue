<script setup lang="ts">
/**
 * 转译历史记录（dome/trans-history.html 定稿 + MyRecordingsView 骨架）
 * - 只看本人：状态（含「已修正」= done+corrected）/ 文件类型 / 关键字筛选 + 分页
 * - 行内：done 播放/修正/复制；failed 播放/重试/删除（确认弹窗）；修正弹窗保存后原位替换
 * - 当页含 pending/processing 时 3s 轮询静默刷新（识别完成即见结果）
 */
import { onMounted, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { useBlobPlayer } from "@/composables/useBlobDownload"
import { usePollingJob } from "@/composables/usePollingJob"
import TransFixDialog from "@/components/TransFixDialog.vue"
import {
  deleteTranscription,
  fetchTranscriptionBlob,
  listTranscriptions,
  retryTranscription,
  type TranscriptionItem,
} from "@/api/trans"
import {
  TRANS_EXT_OPTIONS,
  TRANS_FILTER_OPTIONS,
  TRANS_POLL_INTERVAL,
  displayText,
  transLabel,
  transTagClass,
} from "@/constants/trans"

const audio = useBlobPlayer()
const items = ref<TranscriptionItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const statusFilter = ref("")
const extFilter = ref("")
const keyword = ref("")
const loading = ref(false)

function fmtDur(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.max(0, Math.floor(s % 60))
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}
function fmtSize(n: number) {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}
function fmtDateTime(iso: string) {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    const data = await listTranscriptions({
      status: statusFilter.value === "done_fixed" ? "done" : statusFilter.value || undefined,
      corrected: statusFilter.value === "done_fixed" ? true : undefined,
      file_ext: extFilter.value || undefined,
      q: keyword.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = data.items
    total.value = data.total
    syncPolling()
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}
function reset() {
  statusFilter.value = ""
  extFilter.value = ""
  keyword.value = ""
  page.value = 1
  void load()
}

// 当页有在途行（pending/processing）时 3s 静默刷新，全部落定即停
const poll = usePollingJob({ interval: TRANS_POLL_INTERVAL })
function pageActive() {
  return items.value.some((r) => r.status === "pending" || r.status === "processing")
}
function syncPolling() {
  if (!pageActive()) {
    poll.stop()
    return
  }
  poll.start(async () => {
    const data = await listTranscriptions({
      status: statusFilter.value === "done_fixed" ? "done" : statusFilter.value || undefined,
      corrected: statusFilter.value === "done_fixed" ? true : undefined,
      file_ext: extFilter.value || undefined,
      q: keyword.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = data.items
    total.value = data.total
    return !pageActive()
  })
}

async function listen(row: TranscriptionItem) {
  const blob = await fetchTranscriptionBlob(row.file_url)
  audio.play(blob)
}

async function copyResult(row: TranscriptionItem) {
  const text = displayText(row)
  if (!text) {
    ElMessage.warning("识别结果为空")
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success("已复制到剪贴板")
  } catch {
    ElMessage.warning("复制失败，请手动选择文本")
  }
}

async function retry(row: TranscriptionItem) {
  const item = await retryTranscription(row.id)
  const idx = items.value.findIndex((r) => r.id === row.id)
  if (idx >= 0) items.value.splice(idx, 1, item)
  syncPolling()
}

async function remove(row: TranscriptionItem) {
  await ElMessageBox.confirm(
    `确定删除这条转译记录吗？音频文件与识别结果将同时清除，无法恢复。\n${row.file_name}`,
    "删除转译记录",
    { confirmButtonText: "确认删除", cancelButtonText: "取消", type: "warning" },
  )
  await deleteTranscription(row.id)
  ElMessage.success("已删除")
  void load()
}

const fixVisible = ref(false)
const fixTarget = ref<TranscriptionItem | null>(null)
function openFix(row: TranscriptionItem) {
  fixTarget.value = row
  fixVisible.value = true
}
function onFixed(item: TranscriptionItem) {
  const idx = items.value.findIndex((r) => r.id === item.id)
  if (idx >= 0) items.value.splice(idx, 1, item)
  fixTarget.value = null
}

onMounted(() => void load())
</script>

<template>
  <div class="zp-page-head">
    <h1>转译历史记录</h1>
    <span class="sub">共 {{ total }} 条 · 只看本人转写记录</span>
    <div class="zp-head-actions">
      <router-link class="zp-btn zp-btn--ghost zp-btn--sm" to="/trans/work">← 返回工作台</router-link>
    </div>
  </div>

  <div class="zp-alert zp-alert--info zp-mb-16">
    <span>按账号隔离，只看本人转写记录；支持播放原始音频、修正与复制；失败的记录可重试或删除。</span>
  </div>

  <!-- 筛选栏 -->
  <div class="zp-filter">
    <select class="zp-select" v-model="statusFilter" aria-label="状态">
      <option v-for="s in TRANS_FILTER_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
    </select>
    <select class="zp-select" v-model="extFilter" aria-label="文件类型">
      <option v-for="t in TRANS_EXT_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}</option>
    </select>
    <input
      class="zp-input"
      v-model="keyword"
      placeholder="搜索文件名或转写内容"
      aria-label="搜索文件名或转写内容"
      @keyup.enter="search"
    />
    <button class="zp-btn zp-btn--primary" type="button" @click="search">查询</button>
    <button class="zp-btn zp-btn--ghost" type="button" @click="reset">重置</button>
  </div>

  <!-- 列表 -->
  <div class="zp-card">
    <div class="zp-table-wrap">
      <table class="zp-table">
        <thead>
          <tr>
            <th style="width: 80px">状态</th>
            <th style="width: 240px">文件</th>
            <th style="width: 64px">时长</th>
            <th>识别结果</th>
            <th style="width: 150px">时间</th>
            <th class="zp-text-right" style="width: 190px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td>
              <span class="zp-tag" :class="transTagClass(row.status)">{{ transLabel(row.status) }}</span>
            </td>
            <td>
              <div class="tr-f-name" :title="row.file_name">{{ row.file_name }}</div>
              <div class="tr-f-meta">{{ fmtSize(row.file_size) }} · {{ row.file_ext }}</div>
            </td>
            <td class="num">{{ fmtDur(row.duration) }}</td>
            <td>
              <div v-if="row.status === 'done'" class="tr-r">
                {{ displayText(row) }}<span v-if="row.corrected" class="zp-tag zp-tag--gold">已修正</span>
              </div>
              <span v-else-if="row.status === 'failed'" class="tr-fail-hint">
                识别失败：{{ row.error_message || "可重试" }}
              </span>
              <span v-else-if="row.status === 'processing'" class="tr-eq" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
              <span v-else class="zp-text-3">—</span>
            </td>
            <td class="num">{{ fmtDateTime(row.created_at) }}</td>
            <td class="zp-text-right">
              <button class="zp-btn zp-btn--text" type="button" @click="listen(row)">播放</button>
              <template v-if="row.status === 'done'">
                <button class="zp-btn zp-btn--text" type="button" @click="openFix(row)">修正</button>
                <button class="zp-btn zp-btn--text" type="button" @click="copyResult(row)">复制</button>
              </template>
              <template v-else-if="row.status === 'failed'">
                <button class="zp-btn zp-btn--text" type="button" @click="retry(row)">重试</button>
                <button class="zp-btn zp-btn--text is-danger" type="button" @click="remove(row)">删除</button>
              </template>
            </td>
          </tr>
          <tr v-if="!loading && items.length === 0">
            <td colspan="6" class="zp-center" style="color: var(--ink-3); padding: 32px">暂无转写记录</td>
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

  <TransFixDialog v-model="fixVisible" :item="fixTarget" @saved="onFixed" />
</template>

<style scoped>
/* 与工作台同款视觉词汇：文件名截断 / 结果两行截断 */
.tr-f-name {
  font-size: 13px;
  color: var(--ink);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tr-f-meta {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 2px;
}
.tr-r {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13px;
  color: var(--ink);
  line-height: 1.6;
  max-width: 520px;
}
.tr-r .zp-tag {
  vertical-align: 1px;
  margin-left: 6px;
}
.tr-fail-hint {
  font-size: 12px;
  color: var(--danger);
}
.tr-eq {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 13px;
}
.tr-eq i {
  width: 2.5px;
  height: 8px;
  background: var(--blue-500);
  border-radius: 1px;
  animation: tr-eqb 1s ease-in-out infinite;
}
.tr-eq i:nth-child(2) {
  animation-delay: 0.18s;
}
.tr-eq i:nth-child(3) {
  animation-delay: 0.36s;
}
@keyframes tr-eqb {
  0%,
  100% {
    height: 4px;
  }
  50% {
    height: 13px;
  }
}
</style>

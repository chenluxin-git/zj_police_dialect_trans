<script setup lang="ts">
/**
 * 我的录音（dome/my-recordings.html 1:1）：类别/质检状态/搜索筛选 + 表格
 * 质检列双色标签；行内试听（audioManager 单声道）/下载（带 token 转 blob）/删除（提示进度扣减）
 */
import { onMounted, onUnmounted, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { useAudioStore } from "@/stores/audio"
import {
  deleteRecording,
  fetchRecordingBlob,
  listMyRecordings,
  type RecordingItem,
} from "@/api/recordings"

const CATEGORY: Record<string, { label: string; cls: string }> = {
  police: { label: "警情", cls: "zp-tag--blue" },
  life: { label: "生活", cls: "zp-tag--green" },
  dirty: { label: "俚语", cls: "zp-tag--warn" },
  place: { label: "地名", cls: "zp-tag--gold" },
  custom: { label: "自定义", cls: "zp-tag--gray" },
}
const catLabel = (c: string) => CATEGORY[c]?.label || c
const catCls = (c: string) => CATEGORY[c]?.cls || "zp-tag--gray"

const audio = useAudioStore()
const items = ref<RecordingItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const category = ref("")
const qcStatus = ref("")
const keyword = ref("")
const loading = ref(false)

let listenUrl = ""

function fmtDur(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.max(0, Math.floor(s % 60))
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}
function fmtSize(n: number) {
  return `${Math.max(1, Math.round(n / 1024))} KB`
}
function fmtDateTime(iso: string) {
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  const hh = String(d.getHours()).padStart(2, "0")
  const mi = String(d.getMinutes()).padStart(2, "0")
  return `${mm}-${dd} ${hh}:${mi}`
}
const qcLabel = (s: string) => (s === "passed" ? "已通过" : "待质检")
const qcCls = (s: string) => (s === "passed" ? "zp-tag--green" : "zp-tag--warn")

async function load() {
  loading.value = true
  try {
    const data = await listMyRecordings({
      category: category.value || undefined,
      qc_status: qcStatus.value || undefined,
      q: keyword.value || undefined,
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
  qcStatus.value = ""
  keyword.value = ""
  page.value = 1
  void load()
}
function onPageChange(p: number) {
  page.value = p
  void load()
}

async function listen(row: RecordingItem) {
  const blob = await fetchRecordingBlob(row.file_url)
  const url = URL.createObjectURL(blob)
  audio.play(url)
  if (listenUrl) URL.revokeObjectURL(listenUrl)
  listenUrl = url
}

async function download(row: RecordingItem) {
  const blob = await fetchRecordingBlob(row.file_url)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `recording_${row.id}.wav`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function remove(row: RecordingItem) {
  await ElMessageBox.confirm(
    `确定删除这条录音吗？删除后音频文件同时清除，且任务进度将相应扣减，无法恢复。\n${row.text_content}`,
    "删除录音",
    { confirmButtonText: "确认删除", cancelButtonText: "取消", type: "warning" },
  )
  await deleteRecording(row.id)
  ElMessage.success("已删除")
  void load()
}

onMounted(() => void load())
onUnmounted(() => {
  if (listenUrl) URL.revokeObjectURL(listenUrl)
})
</script>

<template>
  <div class="zp-page-head">
    <h1>我的录音</h1>
    <span class="sub">共 {{ total }} 条</span>
  </div>

  <div class="zp-alert zp-alert--info zp-mb-16">
    <span>
      录音上传后自动质检：与方言转译接口比对，相似度 ≥ 50% 正式入库；未通过的录音已自动移除并通过消息通知重录，不会出现在下方列表。
    </span>
  </div>

  <!-- 筛选栏 -->
  <div class="zp-filter">
    <select class="zp-select" v-model="category" aria-label="类别">
      <option value="">全部类别</option>
      <option value="police">警情</option>
      <option value="life">生活</option>
      <option value="dirty">俚语</option>
      <option value="place">地名</option>
      <option value="custom">自定义</option>
    </select>
    <select class="zp-select" v-model="qcStatus" aria-label="质检状态">
      <option value="">全部状态</option>
      <option value="pending">待质检</option>
      <option value="passed">已通过</option>
    </select>
    <input
      class="zp-input"
      v-model="keyword"
      placeholder="搜索文本内容"
      aria-label="搜索文本内容"
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
            <th style="width: 34%">文本内容</th>
            <th>类别</th>
            <th>方言</th>
            <th>时长</th>
            <th>大小</th>
            <th>录制时间</th>
            <th>质检</th>
            <th class="zp-text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td>{{ row.text_content }}</td>
            <td><span class="zp-tag" :class="catCls(row.category)">{{ catLabel(row.category) }}</span></td>
            <td>{{ row.dialect }}</td>
            <td class="num">{{ fmtDur(row.duration) }}</td>
            <td class="num">{{ fmtSize(row.file_size) }}</td>
            <td class="num">{{ fmtDateTime(row.created_at) }}</td>
            <td><span class="zp-tag" :class="qcCls(row.qc_status)">{{ qcLabel(row.qc_status) }}</span></td>
            <td class="zp-text-right">
              <button class="zp-btn zp-btn--text" type="button" @click="listen(row)">播放</button>
              <button class="zp-btn zp-btn--text" type="button" @click="download(row)">下载</button>
              <button class="zp-btn zp-btn--text is-danger" type="button" @click="remove(row)">删除</button>
            </td>
          </tr>
          <tr v-if="!loading && items.length === 0">
            <td colspan="8" class="zp-center" style="color: var(--ink-3); padding: 32px">暂无录音记录</td>
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
        @current-change="onPageChange"
      />
    </div>
  </div>
</template>

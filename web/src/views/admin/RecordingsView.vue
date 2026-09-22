<script setup lang="ts">
/**
 * 录音管理（dome/admin-recordings.html 1:1）：类别/质检状态/关键词筛选 + 表格
 * 试听（audioManager 单声道，带 token 转 Blob）+ 下载。
 * 注：后端管理端仅提供列表（GET /admin/recordings），无管理端删除端点，故本页不含删除（与 dome 的删除键有偏差）。
 */
import { onMounted, onUnmounted, ref } from "vue"
import { useAudioStore } from "@/stores/audio"
import {
  fetchAudioBlob,
  listAdminRecordings,
  type AdminRecording,
} from "@/api/admin/export"

const CAT_TAG: Record<string, string> = {
  police: "zp-tag--blue",
  life: "zp-tag--green",
  dirty: "zp-tag--warn",
  place: "zp-tag--gold",
  custom: "zp-tag--gray",
}
const catLabel = (c: string) =>
  ({ police: "警情", life: "生活", dirty: "俚语", place: "地名", custom: "自定义" }[c] || c)

const QC: Record<string, { label: string; cls: string }> = {
  pending: { label: "待质检", cls: "zp-tag--warn" },
  passed: { label: "已通过", cls: "zp-tag--green" },
  failed: { label: "未通过", cls: "zp-tag--danger" },
}

const audio = useAudioStore()
const items = ref<AdminRecording[]>([])
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
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
function fmtDateTime(iso: string | null) {
  if (!iso) return "—"
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    const data = await listAdminRecordings({
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

async function listen(row: AdminRecording) {
  const blob = await fetchAudioBlob(row.file_url)
  const url = URL.createObjectURL(blob)
  audio.play(url)
  if (listenUrl) URL.revokeObjectURL(listenUrl)
  listenUrl = url
}

async function download(row: AdminRecording) {
  const blob = await fetchAudioBlob(row.file_url)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `recording_${row.id}.wav`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

onMounted(() => void load())
onUnmounted(() => {
  if (listenUrl) URL.revokeObjectURL(listenUrl)
})
</script>

<template>
  <div class="zp-content" style="padding: 0">
    <div class="zp-page-head">
      <h1>录音管理</h1>
      <span class="sub">辖区全部采集录音 · 支持质检状态筛选、试听与下载</span>
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
        <option value="failed">未通过</option>
      </select>
      <input class="zp-input" v-model="keyword" placeholder="文本内容关键词" aria-label="文本内容关键词" @keyup.enter="search" />
      <button class="zp-btn zp-btn--primary" type="button" @click="search">查询</button>
      <button class="zp-btn zp-btn--ghost" type="button" @click="reset">重置</button>
    </div>

    <!-- 列表 -->
    <div class="zp-card">
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th>录制人</th>
              <th style="width: 34%">文本内容</th>
              <th>类别</th>
              <th>时长</th>
              <th>大小</th>
              <th>质检</th>
              <th>录制时间</th>
              <th class="zp-text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id">
              <td><b>{{ row.user_name }}</b></td>
              <td>{{ row.text_content }}</td>
              <td><span class="zp-tag" :class="CAT_TAG[row.category] || 'zp-tag--gray'">{{ catLabel(row.category) }}</span></td>
              <td class="num">{{ fmtDur(row.duration) }}</td>
              <td class="num">{{ fmtSize(row.file_size) }}</td>
              <td><span class="zp-tag" :class="QC[row.qc_status]?.cls || 'zp-tag--gray'">{{ QC[row.qc_status]?.label || row.qc_status }}</span></td>
              <td class="num">{{ fmtDateTime(row.created_at) }}</td>
              <td class="zp-text-right">
                <button class="zp-btn zp-btn--text" type="button" @click="listen(row)">播放</button>
                <button class="zp-btn zp-btn--text" type="button" @click="download(row)">下载</button>
              </td>
            </tr>
            <tr v-if="!loading && items.length === 0">
              <td colspan="8" style="color: var(--ink-3); padding: 32px; text-align: center">暂无录音记录</td>
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

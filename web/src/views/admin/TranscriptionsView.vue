<script setup lang="ts">
/**
 * 转译记录管理（仿 admin/RecordingsView.vue）：层级辖区列表（本级+下级全部），仅查看 + 播放
 * - 后端 GET /admin/transcriptions（行含录制人 user_name / 区域 region_name）
 * - 试听复用用户侧 /api/transcriptions/{id}/file（管理员 scope 已放行）
 * - 与录音管理同口径：后端仅提供列表，本页不含删除/修正（转译记录归上传民警本人所有）
 * - 区域筛选 RegionPicker（filter 模式：省/超管全省、市管锁本市选区县、县管只读本辖区；
 *   选市不发区县 = 整域筛选，后端 BFS 展开）；关键词命中 文件名/识别内容/录制人
 * - 识别结果两行截断，点击展开/收起；播放为结果格行内播放器（tailect PC 对齐，
 *   服务端只有转码 WAV → 音频播放）
 */
import { onMounted, ref } from "vue"
import { fetchTranscriptionBlob } from "@/api/trans"
import { listAdminTranscriptions, type AdminTranscription } from "@/api/admin/transcriptions"
import { TRANS_ADMIN_FILTER_OPTIONS, TRANS_EXT_OPTIONS, displayText, transLabel, transTagClass } from "@/constants/trans"
import TransRowPlayer from "@/components/TransRowPlayer.vue"
import RegionPicker from "@/components/RegionPicker.vue"

const items = ref<AdminTranscription[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const statusFilter = ref("")
const extFilter = ref("")
const keyword = ref("")
const loading = ref(false)

// 区域筛选：由 RegionPicker 统一维护（区县码优先，否则地市码整域；县管只读本辖区）
const filterRegionCode = ref("")

// 识别结果点击展开/收起（tailect .r-text.full 同款）
const expanded = ref(new Set<number>())
function toggleExpand(id: number) {
  if (expanded.value.has(id)) expanded.value.delete(id)
  else expanded.value.add(id)
}

// 行内播放：页面级单实例互斥，播放钮变「收起播放」
const playingId = ref<number | null>(null)
function togglePlay(row: AdminTranscription) {
  playingId.value = playingId.value === row.id ? null : row.id
}
function loadRowBlob(row: AdminTranscription) {
  return fetchTranscriptionBlob(row.file_url)
}
/** 行离开当前页（翻页/筛选）时收起播放器 */
function clampPlaying() {
  if (playingId.value !== null && !items.value.some((r) => r.id === playingId.value)) {
    playingId.value = null
  }
}

function fmtDur(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.max(0, Math.floor(s % 60))
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}
function fmtSize(n: number) {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}
function fmtDateTime(iso: string | null) {
  if (!iso) return "—"
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function isFixed(row: AdminTranscription) {
  return (row.text_fixed || "") !== ""
}

async function load() {
  loading.value = true
  try {
    const data = await listAdminTranscriptions({
      region: filterRegionCode.value || undefined,
      status: statusFilter.value === "done_fixed" ? "done" : statusFilter.value || undefined,
      corrected: statusFilter.value === "done_fixed" ? true : undefined,
      file_ext: extFilter.value || undefined,
      q: keyword.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = data.items
    total.value = data.total
    clampPlaying()
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
  filterRegionCode.value = ""
  page.value = 1
  void load()
}

onMounted(() => void load())
</script>

<template>
  <div class="zp-content" style="padding: 0">
    <div class="zp-page-head">
      <h1>转译记录</h1>
      <span class="sub">本级及下级辖区全部语音转译记录 · 支持区域/状态筛选与试听</span>
    </div>

    <!-- 筛选栏 -->
    <div class="zp-filter">
      <RegionPicker
        v-model:value="filterRegionCode"
        mode="filter"
        city-placeholder="全部地市"
        district-placeholder="全部区县"
        style="width: 290px"
      />
      <select class="zp-select" v-model="statusFilter" aria-label="状态">
        <option v-for="s in TRANS_ADMIN_FILTER_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
      <select class="zp-select" v-model="extFilter" aria-label="文件类型">
        <option v-for="t in TRANS_EXT_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}</option>
      </select>
      <input class="zp-input" v-model="keyword" placeholder="搜索文件名 / 识别内容 / 录制人" aria-label="搜索文件名、识别内容或录制人" @keyup.enter="search" />
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
              <th style="width: 90px">区域</th>
              <th style="width: 80px">状态</th>
              <th style="width: 220px">文件</th>
              <th style="width: 64px">时长</th>
              <th>识别结果</th>
              <th style="width: 150px">时间</th>
              <th class="zp-text-right" style="width: 80px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id">
              <td><b>{{ row.user_name || "—" }}</b></td>
              <td>{{ row.region_name || "—" }}</td>
              <td>
                <span class="zp-tag" :class="transTagClass(row.status)">{{ transLabel(row.status) }}</span>
              </td>
              <td>
                <div class="tr-f-name" :title="row.file_name">{{ row.file_name }}</div>
                <div class="tr-f-meta">{{ fmtSize(row.file_size) }} · {{ row.file_ext }}</div>
              </td>
              <td class="num">{{ fmtDur(row.duration) }}</td>
              <td>
                <div
                  v-if="row.status === 'done'"
                  class="tr-r"
                  :class="{ 'is-full': expanded.has(row.id) }"
                  title="点击展开/收起"
                  @click="toggleExpand(row.id)"
                >
                  {{ displayText(row) }}<span v-if="isFixed(row)" class="zp-tag zp-tag--gold">已修正</span>
                </div>
                <span v-else-if="row.status === 'failed'" class="tr-fail-hint">
                  识别失败：{{ row.error_message || "可重试" }}
                </span>
                <span v-else class="zp-text-3">{{ row.status === "processing" ? "识别中…" : "—" }}</span>
                <TransRowPlayer
                  v-if="playingId === row.id"
                  :load="() => loadRowBlob(row)"
                  @closed="playingId = null"
                />
              </td>
              <td class="num">{{ fmtDateTime(row.created_at) }}</td>
              <td class="zp-text-right">
                <button class="zp-btn zp-btn--text" type="button" @click="togglePlay(row)">
                  {{ playingId === row.id ? "收起播放" : "播放" }}
                </button>
              </td>
            </tr>
            <tr v-if="!loading && items.length === 0">
              <td colspan="8" style="color: var(--ink-3); padding: 32px; text-align: center">暂无转译记录</td>
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

<style scoped>
/* 与工作台同款视觉词汇：文件名截断 / 结果两行截断 */
.tr-f-name {
  font-size: 13px;
  color: var(--ink);
  max-width: 200px;
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
  max-width: 440px;
  cursor: pointer;
}
.tr-r.is-full {
  -webkit-line-clamp: unset;
}
.tr-r .zp-tag {
  vertical-align: 1px;
  margin-left: 6px;
}
.tr-fail-hint {
  font-size: 12px;
  color: var(--danger);
}
</style>

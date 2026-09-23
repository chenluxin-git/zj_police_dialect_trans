<script setup lang="ts">
/**
 * 数据总览（T32 / dome/admin-overview.html 1:1）
 * 6 统计卡 + 任务进度卡 + 类别分布条形 + 区域统计表（本辖区金色高亮）
 * 区域下钻：仅 super_admin / 省管展示级联，市管/县管固定自身 scope。
 * 2026-09-22 三级展开：区域表行内点击展开 市→区县→派出所（懒加载+缓存；
 * 派出所行按民警单位名称归属，音频素材无单位维度展示为 —）。
 */
import { computed, onMounted, ref } from "vue"
import { useUserStore } from "@/stores/user"
import RegionPicker from "@/components/RegionPicker.vue"
import { getOverview } from "@/api/admin/stats"
import type { Overview, RegionStatRow } from "@/api/admin/stats"

/** 展示行：在接口行上追加层级信息（depth 0 根行 / 1 展开子行） */
interface DisplayRow extends RegionStatRow {
  depth: number
  kind: "city" | "district" | "station"
  expandable: boolean
  loading: boolean
}

interface StatCard {
  label: string
  value: string
  unit: string
  delta: string
  cls: string
}

interface CategoryBar {
  label: string
  count: number
  width: number
  color: string
}

const CATEGORY_LABEL: Record<string, string> = {
  police: "警情",
  life: "生活",
  place: "地名",
  custom: "自定义",
  dirty: "俚语",
}

const CATEGORY_COLOR: Record<string, string> = {
  police: "var(--navy-700)",
  life: "var(--navy-700)",
  place: "var(--gold-500)",
  custom: "var(--line-strong)",
  dirty: "var(--warn)",
}

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1)
}

function formatBytes(b: number): string {
  if (b >= 1024 * 1024 * 1024) return `${(b / 1024 / 1024 / 1024).toFixed(1)} GB`
  if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${b} B`
}

function fmtNum(n: number): string {
  return n.toLocaleString("zh-CN")
}

function pct(part: number, whole: number): string {
  if (!whole) return "0"
  return ((part / whole) * 100).toFixed(1)
}

const userStore = useUserStore()
const isSuper = computed(() => userStore.user?.role === "super_admin")
const ownCode = computed(() => userStore.user?.region_code || "")

const loading = ref(false)
const overview = ref<Overview | null>(null)

// 区域筛选（超管）：由 RegionPicker 统一维护，区县码优先、否则地市码；「确定」后才重新加载
const regionCode = ref("")

// 三级展开状态：expanded 已展开行码；childCache 行码→子行（区县行或派出所行）；childLoading 加载中
const expanded = ref<Set<string>>(new Set())
const childCache = ref<Map<string, RegionStatRow[]>>(new Map())
const childLoading = ref<Set<string>>(new Set())

const statsCards = computed<StatCard[]>(() => {
  const t = overview.value?.total
  if (!t) return []
  return [
    { label: "辖区用户", value: fmtNum(t.users), unit: "人", delta: `辖区 ${t.name}`, cls: "" },
    { label: "录音总数", value: fmtNum(t.recordings), unit: "条", delta: "质检通过口径", cls: "" },
    { label: "录音总时长", value: formatHours(t.seconds), unit: "小时", delta: `容量约 ${formatBytes(t.size_bytes)}`, cls: "" },
    { label: "音频素材", value: fmtNum(t.audio_files), unit: "条", delta: "标注素材库", cls: "zp-stat--gold" },
    { label: "已标注", value: fmtNum(t.annotated), unit: "条", delta: `标注率 ${pct(t.annotated, t.recordings)}%`, cls: "zp-stat--ok" },
  ]
})

const taskRatePct = computed(() => Math.round((overview.value?.tasks.rate || 0) * 100))

const categoryBars = computed<CategoryBar[]>(() => {
  const cc = overview.value?.category_counts || {}
  const entries = Object.entries(cc).sort((a, b) => b[1] - a[1])
  const max = entries.length ? Math.max(...entries.map(([, c]) => c)) : 0
  return entries.map(([cat, count]) => ({
    label: CATEGORY_LABEL[cat] || cat,
    count,
    width: max ? Math.round((count / max) * 100) : 0,
    color: CATEGORY_COLOR[cat] || "var(--navy-700)",
  }))
})

/** 根行层级：省级视图根行是市，市/县级视图根行是区县（区县行可再展开派出所） */
const displayRows = computed<DisplayRow[]>(() => {
  const ov = overview.value
  if (!ov) return []
  const rootKind: "city" | "district" = ov.level === "province" ? "city" : "district"
  const out: DisplayRow[] = []
  for (const r of ov.rows) {
    out.push({ ...r, depth: 0, kind: rootKind, expandable: true,
               loading: childLoading.value.has(r.code) })
    if (!expanded.value.has(r.code)) continue
    const childKind: "district" | "station" = rootKind === "city" ? "district" : "station"
    for (const c of childCache.value.get(r.code) ?? []) {
      out.push({ ...c, depth: 1, kind: childKind, expandable: childKind === "district",
                 loading: childLoading.value.has(c.code) })
    }
  }
  return out
})

async function toggleExpand(row: DisplayRow) {
  const code = row.code
  if (expanded.value.has(code)) {
    expanded.value = new Set([...expanded.value].filter((c) => c !== code))
    return
  }
  expanded.value = new Set([...expanded.value, code])
  if (childCache.value.has(code)) return
  childLoading.value = new Set([...childLoading.value, code])
  try {
    const data = row.kind === "city"
      ? await getOverview(code)                 // 市行 → 区县行
      : await getOverview(code, "station")      // 区县行 → 派出所行
    childCache.value = new Map(childCache.value).set(code, data.rows)
  } finally {
    childLoading.value = new Set([...childLoading.value].filter((c) => c !== code))
  }
}

async function load() {
  loading.value = true
  try {
    expanded.value = new Set()
    childCache.value = new Map()
    // 区域筛选由 RegionPicker 维护：区县码精确、地市码展开整域、空=本辖区
    overview.value = await getOverview(regionCode.value || undefined)
  } finally {
    loading.value = false
  }
}

function onConfirm() {
  void load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div v-loading="loading">
    <div class="zp-page-head">
      <h1>数据总览</h1>
      <span class="sub">辖区数据汇总 · 数据范围随管理员层级自动限定</span>
      <div v-if="isSuper" class="zp-head-actions">
        <RegionPicker
          v-model:value="regionCode"
          mode="filter"
          city-placeholder="全部地市"
          district-placeholder="全部区县"
          style="width: 310px"
        />
        <button class="zp-btn zp-btn--primary" type="button" @click="onConfirm">确定</button>
      </div>
    </div>

    <!-- 统计卡 -->
    <div class="zp-overview-grid zp-mb-16">
      <div v-for="c in statsCards" :key="c.label" class="zp-stat" :class="c.cls">
        <span class="bar"></span>
        <div class="label">{{ c.label }}</div>
        <div class="value">{{ c.value }}<small>{{ c.unit }}</small></div>
        <div class="delta">{{ c.delta }}</div>
      </div>
    </div>

    <!-- 任务进度 + 文本类别 -->
    <div class="zp-grid-2 zp-mb-16">
      <div class="zp-card">
        <div class="zp-card-head"><h2>辖区任务进度</h2></div>
        <div class="zp-card-body">
          <div class="zp-field" style="margin-bottom: 14px">
            <label>任务指标（已完成 / 总指标）</label>
            <div class="zp-progress">
              <div class="track"><div class="fill" :style="{ width: taskRatePct + '%' }"></div></div>
              <span class="num"><b>{{ overview?.tasks.done_sum ?? 0 }}</b> / {{ overview?.tasks.target_sum ?? 0 }}</span>
            </div>
          </div>
          <div class="zp-flex" style="justify-content: space-between">
            <span class="zp-tag zp-tag--green">已启动 {{ overview?.tasks.started ?? 0 }}</span>
            <span class="zp-tag zp-tag--gray">完成率 {{ taskRatePct }}%</span>
          </div>
          <div v-if="(overview?.tasks.not_started ?? 0) > 0" class="zp-alert zp-alert--warn zp-mt-16">
            <span>辖区 {{ overview?.total.users ?? 0 }} 人中 <b>{{ overview?.tasks.not_started }}</b> 人的任务尚未启动，可发消息提醒。</span>
          </div>
        </div>
      </div>
      <div class="zp-card">
        <div class="zp-card-head"><h2>文本类别分布</h2></div>
        <div class="zp-card-body">
          <div v-for="b in categoryBars" :key="b.label" class="zp-cat-bar">
            <span class="name">{{ b.label }}</span>
            <div class="track"><div class="fill" :style="{ width: b.width + '%', background: b.color }"></div></div>
            <span class="num">{{ b.count }}</span>
          </div>
          <div v-if="!categoryBars.length" class="zp-empty"><p>暂无文本数据</p></div>
          <p class="zp-text-3 zp-mt-16">文本总量 {{ overview?.total.texts ?? 0 }} 条</p>
        </div>
      </div>
    </div>

    <!-- 区域统计表 -->
    <div class="zp-card">
      <div class="zp-card-head">
        <h2>{{ overview?.total.name ?? "" }} · 区域统计</h2>
        <span class="zp-card-sub">点击展开下级（市→区县→派出所，本辖区金色高亮）</span>
      </div>
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th>区域</th><th>用户数</th><th>录音数</th><th>录音时长</th>
              <th>音频素材</th><th>已标注</th>
            </tr>
          </thead>
          <tbody>
            <tr class="is-total">
              <td>{{ overview?.total.name ?? "合计" }}合计</td>
              <td class="num">{{ fmtNum(overview?.total.users ?? 0) }}</td>
              <td class="num">{{ fmtNum(overview?.total.recordings ?? 0) }}</td>
              <td class="num">{{ formatHours(overview?.total.seconds ?? 0) }} h</td>
              <td class="num">{{ fmtNum(overview?.total.audio_files ?? 0) }}</td>
              <td class="num">{{ fmtNum(overview?.total.annotated ?? 0) }}</td>
            </tr>
            <tr v-for="r in displayRows" :key="r.kind + '-' + r.code"
                :style="r.code === ownCode ? 'background:var(--gold-50)' : ''">
              <td>
                <div class="zp-row-tree" :style="{ paddingLeft: 4 + r.depth * 24 + 'px' }">
                  <button v-if="r.expandable" class="zp-tree-toggle" type="button"
                          :aria-label="expanded.has(r.code) ? '收起 ' + r.name : '展开 ' + r.name"
                          @click="toggleExpand(r)">
                    <span v-if="r.loading" class="zp-tree-loading">…</span>
                    <span v-else class="zp-tree-tri" :class="{ open: expanded.has(r.code) }">▶</span>
                  </button>
                  <span v-else class="zp-tree-leaf" aria-hidden="true"></span>
                  <b v-if="r.code === ownCode">{{ r.name }}（本辖区）</b>
                  <span v-else :class="{ 'zp-tree-child': r.depth > 0 }">{{ r.name }}</span>
                </div>
              </td>
              <td class="num">{{ fmtNum(r.users) }}</td>
              <td class="num">{{ fmtNum(r.recordings) }}</td>
              <td class="num">{{ formatHours(r.seconds) }} h</td>
              <td class="num">{{ r.kind === "station" ? "—" : fmtNum(r.audio_files) }}</td>
              <td class="num">{{ fmtNum(r.annotated) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* .zp-overview-grid 已收拢到 theme.css（auto-fit 按可用宽度自适应），此处不再重复定义 */
.zp-cat-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  font-size: 13px;
}
.zp-cat-bar .name {
  width: 64px;
  color: var(--ink-2);
  flex: none;
}
.zp-cat-bar .track {
  flex: 1;
  height: 10px;
  border-radius: 99px;
  background: #e8edf5;
  overflow: hidden;
}
.zp-cat-bar .fill {
  height: 100%;
  background: var(--navy-700);
}
.zp-cat-bar .num {
  width: 56px;
  text-align: right;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
  flex: none;
}
.zp-table .is-total td {
  background: #f7f9fc;
  font-weight: 600;
}
.zp-row-tree {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 24px;
}
.zp-tree-toggle {
  border: none;
  background: none;
  padding: 2px 4px;
  cursor: pointer;
  color: var(--ink-3);
  font-size: 11px;
  line-height: 1;
  flex: none;
}
.zp-tree-toggle:hover {
  color: var(--navy-700);
}
.zp-tree-tri {
  display: inline-block;
  transition: transform 0.15s ease;
}
.zp-tree-tri.open {
  transform: rotate(90deg);
}
.zp-tree-loading {
  font-size: 12px;
}
.zp-tree-leaf {
  width: 19px;
  flex: none;
  color: var(--line-strong);
}
.zp-tree-leaf::before {
  content: "·";
}
.zp-tree-child {
  color: var(--ink-2);
}
</style>

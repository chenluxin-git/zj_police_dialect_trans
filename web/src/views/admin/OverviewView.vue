<script setup lang="ts">
/**
 * 数据总览（T32 / dome/admin-overview.html 1:1）
 * 6 统计卡 + 任务进度卡 + 类别分布条形 + 区域两级统计表（本辖区金色高亮）
 * 区域下钻：仅 super_admin / 省管展示级联，市管/县管固定自身 scope。
 */
import { computed, onMounted, ref } from "vue"
import { useUserStore } from "@/stores/user"
import { api } from "@/api/http"
import { getOverview } from "@/api/admin/stats"
import type { Overview } from "@/api/admin/stats"

interface RegionNode {
  code: string
  name: string
  level: string
  children: RegionNode[]
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
  dirty: "脏话",
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
const regionTree = ref<RegionNode[]>([])
const cascadeValue = ref<string[]>([])

const statsCards = computed<StatCard[]>(() => {
  const t = overview.value?.total
  if (!t) return []
  return [
    { label: "辖区用户", value: fmtNum(t.users), unit: "人", delta: `辖区 ${t.name}`, cls: "" },
    { label: "录音总数", value: fmtNum(t.recordings), unit: "条", delta: "质检通过口径", cls: "" },
    { label: "录音总时长", value: formatHours(t.seconds), unit: "小时", delta: `容量约 ${formatBytes(t.size_bytes)}`, cls: "" },
    { label: "音频素材", value: fmtNum(t.audio_files), unit: "条", delta: "标注素材库", cls: "zp-stat--gold" },
    { label: "已标注", value: fmtNum(t.annotated), unit: "条", delta: `标注率 ${pct(t.annotated, t.recordings)}%`, cls: "zp-stat--ok" },
    { label: "判定为方言", value: fmtNum(t.dialect_count), unit: "条", delta: `占已标注 ${pct(t.dialect_count, t.annotated)}%`, cls: "zp-stat--ok" },
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

async function loadRegions() {
  regionTree.value = await api.get<RegionNode[]>("/regions/tree")
}

async function load() {
  loading.value = true
  try {
    const code = cascadeValue.value.length
      ? cascadeValue.value[cascadeValue.value.length - 1]
      : undefined
    overview.value = await getOverview(code)
  } finally {
    loading.value = false
  }
}

function onRegionChange() {
  void load()
}

onMounted(async () => {
  if (isSuper.value) await loadRegions()
  await load()
})
</script>

<template>
  <div v-loading="loading">
    <div class="zp-page-head">
      <h1>数据总览</h1>
      <span class="sub">辖区数据汇总 · 数据范围随管理员层级自动限定</span>
      <div v-if="isSuper" class="zp-head-actions">
        <el-cascader
          v-model="cascadeValue"
          :options="regionTree"
          :props="{ value: 'code', label: 'name', children: 'children', checkStrictly: true, emitPath: true }"
          placeholder="全部区域（点击下钻）"
          clearable
          style="width: 260px"
          @change="onRegionChange"
        />
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
        <span class="zp-card-sub">按区域汇总（本辖区金色高亮）</span>
      </div>
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th>区域</th><th>用户数</th><th>录音数</th><th>录音时长</th>
              <th>音频素材</th><th>已标注</th><th>方言判定</th>
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
              <td class="num">{{ fmtNum(overview?.total.dialect_count ?? 0) }}</td>
            </tr>
            <tr v-for="r in overview?.rows ?? []" :key="r.code" :style="r.code === ownCode ? 'background:var(--gold-50)' : ''">
              <td><b v-if="r.code === ownCode">{{ r.name }}（本辖区）</b><span v-else>{{ r.name }}</span></td>
              <td class="num">{{ fmtNum(r.users) }}</td>
              <td class="num">{{ fmtNum(r.recordings) }}</td>
              <td class="num">{{ formatHours(r.seconds) }} h</td>
              <td class="num">{{ fmtNum(r.audio_files) }}</td>
              <td class="num">{{ fmtNum(r.annotated) }}</td>
              <td class="num">{{ fmtNum(r.dialect_count) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.zp-overview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
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
@media (max-width: 1080px) {
  .zp-overview-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>

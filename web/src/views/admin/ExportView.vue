<script setup lang="ts">
/**
 * 数据集导出（dome/admin-export.html 1:1）：两源合并清单 checkbox 表（source 标签 录音/音频库）
 * + 类别筛选 + 「导出所选/导出全部」→ 任务卡轮询进度（打包中 processed/total）
 * + 下载（blob 下载后提示即焚）
 */
import { computed, onMounted, onUnmounted, ref } from "vue"
import { ElMessage } from "element-plus"
import { useUserStore } from "@/stores/user"
import {
  downloadExport,
  exportAll,
  exportSelected,
  getExportTask,
  listExportAudio,
  type ExportListItem,
  type ExportTaskStatus,
} from "@/api/admin/export"
import { listRegions, type RegionItem } from "@/api/admin/texts"
import { api } from "@/api/http"

interface RegionNode {
  code: string
  name: string
  level: string
  children: RegionNode[]
}

const userStore = useUserStore()
const isSuper = computed(() => userStore.user?.role === "super_admin")

const CATEGORIES = [
  { value: "", label: "全部类别" },
  { value: "police", label: "警情" },
  { value: "life", label: "生活" },
  { value: "dirty", label: "俚语" },
  { value: "place", label: "地名" },
  { value: "custom", label: "自定义" },
]

const regions = ref<RegionItem[]>([])
const items = ref<ExportListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const category = ref("")
const loading = ref(false)

// 区域筛选（超管）：地市 + 区县两级下拉，地市选定后区县才可选（市码展开整域、区县码精确）
const regionTree = ref<RegionNode[]>([])
const cityCode = ref("")
const districtCode = ref("")
const regionCode = computed(() => districtCode.value || cityCode.value)

const cityOptions = computed<RegionNode[]>(() =>
  regionTree.value.flatMap((r) => (r.level === "province" ? r.children : [r])))

const districtOptions = computed<RegionNode[]>(() =>
  cityCode.value
    ? cityOptions.value.find((c) => c.code === cityCode.value)?.children ?? []
    : [])

function onCityChange() {
  districtCode.value = ""
}

const selected = ref<Set<string>>(new Set())
const allChecked = computed(
  () => items.value.length > 0 && items.value.every((it) => selected.value.has(`${it.source}:${it.id}`)),
)

const task = ref<ExportTaskStatus | null>(null)
const taskId = ref(0)
const exporting = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const regionName = (code: string) => regions.value.find((r) => r.code === code)?.name || code

function fmtDur(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.max(0, Math.floor(s % 60))
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}
function fmtDateTime(iso: string) {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
const contentOf = (it: ExportListItem) =>
  it.source === "recording" ? it.text_or_name : it.translation || it.text_or_name

const percent = computed(() => {
  if (!task.value || !task.value.total_count) return 0
  return Math.min(100, Math.round((task.value.processed_count / task.value.total_count) * 100))
})

async function loadRegions() {
  try {
    regions.value = await listRegions()
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
  if (isSuper.value) {
    try {
      regionTree.value = await api.get<RegionNode[]>("/regions/tree")
    } catch {
      /* 错误已由 http 拦截器提示 */
    }
  }
}

async function loadList() {
  loading.value = true
  try {
    const data = await listExportAudio({
      category: category.value || undefined,
      region: isSuper.value && regionCode.value ? regionCode.value : undefined,
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
  void loadList()
}

function toggleAll() {
  if (allChecked.value) {
    items.value.forEach((it) => selected.value.delete(`${it.source}:${it.id}`))
  } else {
    items.value.forEach((it) => selected.value.add(`${it.source}:${it.id}`))
  }
  selected.value = new Set(selected.value)
}
function toggleOne(key: string) {
  if (selected.value.has(key)) selected.value.delete(key)
  else selected.value.add(key)
  selected.value = new Set(selected.value)
}

function clearTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function pollTask(taskId: number) {
  clearTimer()
  timer = setInterval(async () => {
    try {
      const t = await getExportTask(taskId)
      task.value = t
      if (t.status === "completed" || t.status === "failed") {
        clearTimer()
        exporting.value = false
      }
    } catch {
      clearTimer()
      exporting.value = false
    }
  }, 1500)
}

async function doExportSelected() {
  const payload = [...selected.value].map((k) => {
    const [source, id] = k.split(":")
    return { source, id: Number(id) }
  })
  if (!payload.length) {
    ElMessage.warning("请先勾选要导出的条目")
    return
  }
  exporting.value = true
  task.value = { status: "processing", total_count: payload.length, processed_count: 0, file_url: null }
  try {
    const data = await exportSelected(payload)
    taskId.value = data.task_id
    pollTask(data.task_id)
  } catch {
    exporting.value = false
    task.value = null
  }
}

async function doExportAll() {
  exporting.value = true
  task.value = { status: "processing", total_count: total.value, processed_count: 0, file_url: null }
  try {
    const data = await exportAll({
      category: category.value || undefined,
      region: isSuper.value && regionCode.value ? regionCode.value : undefined,
    })
    taskId.value = data.task_id
    pollTask(data.task_id)
  } catch {
    exporting.value = false
    task.value = null
  }
}

async function doDownload() {
  if (!taskId.value) return
  const blob = await downloadExport(taskId.value)
  const objUrl = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = objUrl
  a.download = `export_${taskId.value}.zip`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objUrl)
  ElMessage.success("下载开始，完成后临时文件自动清除")
}

onMounted(() => {
  void loadRegions()
  void loadList()
})
onUnmounted(clearTimer)
</script>

<template>
  <div class="zp-content" style="padding: 0">
    <div class="zp-page-head">
      <h1>数据集导出</h1>
      <span class="sub">筛选语料生成训练集 ZIP（音频 + 文本清单），下载后文件即焚</span>
    </div>

    <!-- 筛选条件 -->
    <div class="zp-card zp-mb-16">
      <div class="zp-card-head"><h2>筛选条件</h2></div>
      <div class="zp-card-body">
        <div class="zp-filter" style="margin-bottom: 0">
          <select class="zp-select" v-model="category" aria-label="类别">
            <option v-for="c in CATEGORIES" :key="c.value" :value="c.value">{{ c.label }}</option>
          </select>
          <template v-if="isSuper">
            <el-select
              v-model="cityCode"
              placeholder="全部地市"
              clearable
              style="width: 140px"
              @change="onCityChange"
            >
              <el-option v-for="c in cityOptions" :key="c.code" :label="c.name" :value="c.code" />
            </el-select>
            <el-select
              v-model="districtCode"
              placeholder="全部区县"
              clearable
              :disabled="!cityCode"
              style="width: 140px"
            >
              <el-option v-for="d in districtOptions" :key="d.code" :label="d.name" :value="d.code" />
            </el-select>
          </template>
          <button class="zp-btn zp-btn--primary" type="button" @click="search">查询清单</button>
        </div>
      </div>
    </div>

    <!-- 可导出清单 -->
    <div class="zp-card zp-mb-16">
      <div class="zp-card-head">
        <h2>可导出清单</h2>
        <span class="zp-card-sub">共 {{ total }} 条 · 已选 {{ selected.size }} 条</span>
        <div class="zp-head-actions">
          <button class="zp-btn zp-btn--ghost" type="button" :disabled="exporting" @click="doExportAll">导出全部</button>
          <button class="zp-btn zp-btn--primary" type="button" :disabled="exporting" @click="doExportSelected">导出所选</button>
        </div>
      </div>
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th style="width: 36px"><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
              <th>类型</th>
              <th style="width: 38%">文本内容 / 普通话翻译</th>
              <th>区域</th>
              <th>时长</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in items" :key="`${it.source}:${it.id}`">
              <td><input type="checkbox" :checked="selected.has(`${it.source}:${it.id}`)" @change="toggleOne(`${it.source}:${it.id}`)" /></td>
              <td>
                <span class="zp-tag" :class="it.source === 'recording' ? 'zp-tag--blue' : 'zp-tag--green'">
                  {{ it.source === "recording" ? "采集录音" : "标注音频" }}
                </span>
              </td>
              <td>{{ contentOf(it) }}</td>
              <td>{{ regionName(it.region_code) }}</td>
              <td class="num">{{ fmtDur(it.duration) }}</td>
              <td class="num">{{ fmtDateTime(it.created_at) }}</td>
            </tr>
            <tr v-if="!loading && items.length === 0">
              <td colspan="6" style="color: var(--ink-3); padding: 32px; text-align: center">暂无可导出条目</td>
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
          @current-change="(p: number) => { page = p; loadList() }"
        />
      </div>
    </div>

    <!-- 导出任务 -->
    <div class="zp-card" v-if="task || exporting">
      <div class="zp-card-head"><h2>导出任务</h2><span class="zp-card-sub">打包完成后请及时下载</span></div>
      <div class="zp-card-body">
        <div class="zp-flex" style="align-items: center; gap: 12px">
          <span v-if="task?.status === 'completed'" class="zp-tag zp-tag--green">已完成</span>
          <span v-else-if="task?.status === 'failed'" class="zp-tag zp-tag--danger">失败</span>
          <span v-else class="zp-tag zp-tag--warn">打包中</span>
          <div class="zp-flex" style="flex: 1; align-items: center; gap: 8px">
            <el-progress :percentage="percent" :stroke-width="8" style="flex: 1" />
            <span class="num" style="font-size: 13px; color: var(--ink-2)">
              {{ task?.processed_count || 0 }} / {{ task?.total_count || 0 }} 条
            </span>
          </div>
          <button v-if="task?.status === 'completed' && task.file_url" class="zp-btn zp-btn--primary zp-btn--sm"
            type="button" @click="doDownload">下载</button>
        </div>
      </div>
    </div>

    <div class="zp-alert zp-alert--warn zp-mt-16">
      <span>ZIP 内含音频与 dataset.txt（文本-文件位置对照清单）；导出文件下载后即自动删除，请妥善保管，注意保密。</span>
    </div>
  </div>
</template>

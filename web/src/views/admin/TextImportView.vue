<script setup lang="ts">
/**
 * 文本导入（dome/admin-text-import.html 1:1）：类别 + 归属区域（super_admin 可改）
 * + txt/docx 模板下载 + el-upload 单文件 + 后台导入任务轮询（句号切分）
 */
import { computed, onMounted, onUnmounted, ref } from "vue"
import { ElMessage } from "element-plus"
import type { UploadFile } from "element-plus"
import { useUserStore } from "@/stores/user"
import {
  downloadTextTemplate,
  importTexts,
  listRegions,
  pollTextImport,
  type RegionItem,
} from "@/api/admin/texts"

const userStore = useUserStore()

// 规格裁定 2026-09-22：导入强制落区县级（用户领取为精确匹配，市/省级归属成死数据）
// 区县管理员默认本辖区（后端自动）；市管限本市下辖区县、省管/超管全省区县，必选
const ownRegion = computed(() =>
  regions.value.find((r) => r.code === userStore.user?.region_code))
const needDistrictPick = computed(() =>
  regions.value.length > 0 && ownRegion.value?.level !== "district")
const districtOptions = computed(() => {
  const districts = regions.value.filter((r) => r.level === "district")
  const own = ownRegion.value
  return own?.level === "city" ? districts.filter((r) => r.parent_code === own.code) : districts
})

const CATEGORIES = [
  { value: "police", label: "警情" },
  { value: "life", label: "生活" },
  { value: "dirty", label: "脏话" },
  { value: "place", label: "地名" },
]

const STATUS_TAG: Record<string, { label: string; cls: string }> = {
  pending: { label: "排队中", cls: "zp-tag--gray" },
  processing: { label: "解析中", cls: "zp-tag--warn" },
  completed: { label: "完成", cls: "zp-tag--green" },
  failed: { label: "失败", cls: "zp-tag--danger" },
}

const regions = ref<RegionItem[]>([])
const category = ref("police")
const regionCode = ref("") // "" = 本辖区（后端按管理员归属解析）
const file = ref<File | null>(null)
const importing = ref(false)
const task = ref<{ status: string; total_count: number; error_message: string | null } | null>(null)

let timer: ReturnType<typeof setInterval> | null = null

const ownRegionName = computed(() => {
  const code = userStore.user?.region_code
  if (!code) return "本辖区"
  return regions.value.find((r) => r.code === code)?.name || code
})

const fileSizeLabel = computed(() => {
  if (!file.value) return ""
  return `${Math.max(1, Math.round(file.value.size / 1024))} KB`
})

async function loadRegions() {
  try {
    regions.value = await listRegions()
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

function onFileChange(uploadFile: UploadFile) {
  file.value = uploadFile.raw || null
}

function clearTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function downloadTemplate(fmt: "txt" | "docx") {
  try {
    const blob = await downloadTextTemplate(fmt)
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = fmt === "txt" ? "texts_template.txt" : "texts_template.docx"
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

function pollTask(taskId: number) {
  clearTimer()
  timer = setInterval(async () => {
    try {
      const t = await pollTextImport(taskId)
      task.value = { status: t.status, total_count: t.total_count, error_message: t.error_message }
      if (t.status === "completed") {
        clearTimer()
        importing.value = false
        ElMessage.success(`导入完成，共 ${t.total_count} 条文本`)
      } else if (t.status === "failed") {
        clearTimer()
        importing.value = false
        ElMessage.error(t.error_message || "导入失败")
      }
    } catch {
      clearTimer()
      importing.value = false
      task.value = null
    }
  }, 1200)
}

async function startImport() {
  if (!file.value) {
    ElMessage.warning("请先选择 txt / docx 文件")
    return
  }
  if (needDistrictPick.value && !regionCode.value) {
    ElMessage.warning("请选择归属区县（市/省级归属的文本县级用户无法领取）")
    return
  }
  const form = new FormData()
  form.append("file", file.value)
  form.append("category", category.value)
  if (regionCode.value) form.append("region_code", regionCode.value)

  importing.value = true
  task.value = { status: "processing", total_count: 0, error_message: null }
  try {
    const data = await importTexts(form)
    pollTask(data.task_id)
  } catch {
    importing.value = false
    task.value = null
  }
}

onMounted(loadRegions)
onUnmounted(clearTimer)
</script>

<template>
  <div class="zp-content" style="max-width: 880px; padding: 0">
    <div class="zp-page-head">
      <h1>文本导入</h1>
      <span class="sub">上传 txt / docx 文件，按句号自动切分为朗读文本，后台导入</span>
      <div class="zp-head-actions">
        <button class="zp-btn zp-btn--ghost" type="button" @click="downloadTemplate('txt')">txt 模板</button>
        <button class="zp-btn zp-btn--ghost" type="button" @click="downloadTemplate('docx')">docx 模板</button>
      </div>
    </div>

    <!-- 导入设置 -->
    <div class="zp-card zp-mb-16">
      <div class="zp-card-head"><h2>导入设置</h2></div>
      <div class="zp-card-body">
        <div class="zp-form-row">
          <div class="zp-field">
            <label>文本类别<span class="req">*</span></label>
            <select class="zp-select" v-model="category" aria-label="文本类别">
              <option v-for="c in CATEGORIES" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
          </div>
          <div class="zp-field">
            <label>归属区域<span class="req">*</span></label>
            <select v-if="needDistrictPick" class="zp-select" v-model="regionCode" aria-label="归属区域">
              <option value="">请选择区县</option>
              <option v-for="r in districtOptions" :key="r.code" :value="r.code">{{ r.name }}</option>
            </select>
            <input v-else class="zp-input" :value="ownRegionName" disabled />
            <p class="zp-hint">导入须落区县级：区县管理员默认本辖区；市/省级管理员请选定区县，否则县级用户无法领取</p>
          </div>
        </div>

        <div class="zp-field">
          <label>上传文件<span class="req">*</span></label>
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            accept=".txt,.docx"
            :show-file-list="false"
            :on-change="onFileChange"
          >
            <div class="zp-dropzone">
              <b>点击选择或拖入文件</b><br />
              支持 .txt / .docx，UTF-8 编码，单文件不超过 5 MB
            </div>
          </el-upload>
          <p class="zp-hint zp-mt-8">
            已选择：<b style="color: var(--ink)">{{ file ? file.name : "未选择" }}</b>
            <span v-if="file">（{{ fileSizeLabel }}）</span>
          </p>
        </div>

        <button class="zp-btn zp-btn--primary zp-btn--lg" style="width: 100%" type="button"
          :disabled="importing" @click="startImport">
          {{ importing ? "导入中…" : "开始导入" }}
        </button>
      </div>
    </div>

    <!-- 导入进度 -->
    <div class="zp-card zp-mb-16">
      <div class="zp-card-head">
        <h2>导入进度</h2>
        <span v-if="task" class="zp-tag" :class="STATUS_TAG[task.status]?.cls || 'zp-tag--gray'">
          {{ STATUS_TAG[task.status]?.label || task.status }}
        </span>
      </div>
      <div class="zp-card-body">
        <p v-if="task && task.status === 'completed'" class="zp-text-3 zp-mb-16">
          导入完成，共切分入库 <b style="color: var(--ink)">{{ task.total_count }}</b> 条文本，可在「导入台账」查看与撤销。
        </p>
        <p v-else-if="task && task.status === 'failed'" class="zp-text-3 zp-mb-16" style="color: var(--danger)">
          导入失败：{{ task.error_message || "未知错误" }}
        </p>
        <p v-else class="zp-text-3 zp-mb-16">按句号「。」切分，去空行去重复；导入完成可在「导入台账」查看与撤销。</p>
        <div class="zp-alert zp-alert--info">
          <span>切分示例：「你们不要吵了，都先坐下来，有话好好讲。」＋「我是社区民警，麻烦开下门。」＋「路口堵住了，让车挪一挪。」→ 3 条文本</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.zp-dropzone {
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--radius-lg);
  padding: 36px 16px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.zp-dropzone b {
  color: var(--navy-700);
  font-size: 14px;
}
</style>

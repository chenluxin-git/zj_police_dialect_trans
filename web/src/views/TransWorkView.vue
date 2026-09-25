<script setup lang="ts">
/**
 * 语音转译工作台（dome/trans-work.html 定稿 1:1，tr-* scoped 移植）
 * - 声波舞台：点击选文件 / 拖放入队（排除底部录音工具条）；内联麦克风录音（Recorder.vue 机制移植）
 * - 队列真实化：上传即建 pending 服务行，后台泵串行识别，本页 3s 轮询 ?ids= 批量合并状态
 * - 与 dome 的两处有意偏差：①「修正」仅 done 行显示（dome 全行显示是稿瑕疵）
 *   ②真实上传非瞬时，增加「上传中」本地灰标；移除/清除已完成=本地隐藏，删库入口在历史页
 * - 刷新恢复：onMounted 用 ?active=1 水化在途队列，轮询继续接管
 * - 播放对齐 tailect PC：音频 = 结果格行内播放器（本地 File 即时播）；
 *   视频 = 行下方插入本地视频对比面板（原生 video + 转写文字，服务端只存转码 WAV）；
 *   识别结果两行截断，点击展开/收起
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { ElMessage } from "element-plus"
import TransFixDialog from "@/components/TransFixDialog.vue"
import TransRowPlayer from "@/components/TransRowPlayer.vue"
import { usePollingJob } from "@/composables/usePollingJob"
import {
  fetchTranscriptionBlob,
  listTranscriptions,
  retryTranscription,
  uploadTranscription,
  type TranscriptionItem,
} from "@/api/trans"
import {
  TRANS_ALLOWED_EXTS,
  TRANS_MAX_MB,
  TRANS_MAX_MINUTES,
  TRANS_POLL_INTERVAL,
  displayText,
} from "@/constants/trans"

type RowStatus = "uploading" | "pending" | "processing" | "done" | "failed"

interface QueueRow {
  key: string
  name: string
  ext: string
  size: number
  dur: number
  status: RowStatus
  item: TranscriptionItem | null // 上传成功后挂服务行
  error: string // 本地上传失败原因（服务行失败读 item.error_message）
  file?: File | Blob // 本地原始文件（会话内行内/面板播放用；done 行不被水化，始终在内存）
}

let keySeq = 0
const items = ref<QueueRow[]>([])

function fmtSize(n: number) {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}
function fmtDur(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.max(0, Math.floor(s % 60))
  return `${m}:${String(ss).padStart(2, "0")}`
}

function statusLabel(s: RowStatus) {
  return { uploading: "上传中", pending: "排队中", processing: "识别中", done: "完成", failed: "失败" }[s]
}
function statusClass(s: RowStatus) {
  return { uploading: "zp-tag--gray", pending: "zp-tag--gray", processing: "zp-tag--blue", done: "zp-tag--green", failed: "zp-tag--danger" }[s]
}
function failHint(row: QueueRow) {
  const reason = row.item ? (row.item.error_message || "可重试") : row.error
  return `${row.item ? "识别" : "上传"}失败：${reason}`
}

const queueStat = computed(() => {
  if (items.value.length === 0) return ""
  const done = items.value.filter((r) => r.status === "done").length
  const fail = items.value.filter((r) => r.status === "failed").length
  return `共 ${items.value.length} 条 · 完成 ${done} · 失败 ${fail}`
})

// ---------- 上传：逐条串行（大文件耗时可观，避免并发挤爆转码信号量与带宽） ----------
interface UploadJob {
  row: QueueRow
  file: File | Blob
}
const uploadQueue: UploadJob[] = []
let uploadBusy = false

function extOf(name: string) {
  return (name.slice(name.lastIndexOf(".") + 1) || "").toLowerCase()
}

function enqueueFile(file: File | Blob, name: string, size: number) {
  const ext = extOf(name)
  if (TRANS_ALLOWED_EXTS.indexOf(ext) === -1) {
    ElMessage.warning(`不支持的文件格式（${name}），仅限 ${TRANS_ALLOWED_EXTS.join(" / ")}`)
    return
  }
  if (size > TRANS_MAX_MB * 1024 * 1024) {
    ElMessage.warning(`「${name}」超过 ${TRANS_MAX_MB}MB 上限`)
    return
  }
  const row: QueueRow = {
    key: `local-${++keySeq}`, name, ext, size, dur: 0,
    status: "uploading", item: null, error: "", file,
  }
  items.value.unshift(row)
  uploadQueue.push({ row, file })
  void pumpUploads()
}

async function pumpUploads() {
  if (uploadBusy) return
  uploadBusy = true
  while (uploadQueue.length > 0) {
    const job = uploadQueue.shift() as UploadJob
    try {
      const item = await uploadTranscription(job.file, job.row.name)
      job.row.item = item
      job.row.status = item.status as RowStatus
      job.row.dur = item.duration
      job.row.size = item.file_size
      job.row.ext = item.file_ext
      job.row.error = ""
      startPolling()
    } catch {
      job.row.status = "failed"
      job.row.error = "请移除后重新添加（原因见提示）"
    }
  }
  uploadBusy = false
}

// ---------- 轮询：有 pending/processing 会话行时 3s 批量取状态，无在途即停 ----------
const poll = usePollingJob({ interval: TRANS_POLL_INTERVAL })

function activeRows() {
  return items.value.filter((r) => r.status === "pending" || r.status === "processing")
}
function startPolling() {
  if (activeRows().length === 0) return
  poll.start(async () => {
    const rows = activeRows()
    if (rows.length === 0) return true
    const ids = rows
      .filter((r) => r.item)
      .slice(0, 50)
      .map((r) => String((r.item as TranscriptionItem).id))
      .join(",")
    if (!ids) return true
    const data = await listTranscriptions({ ids, page_size: 100 })
    const byId = new Map<number, TranscriptionItem>()
    for (const it of data.items) byId.set(it.id, it)
    for (const r of items.value) {
      if (r.item && byId.has(r.item.id)) {
        r.item = byId.get(r.item.id) as TranscriptionItem
        if (r.status !== "uploading") r.status = r.item.status as RowStatus
        if (r.item.duration > 0) r.dur = r.item.duration
      }
    }
    return activeRows().length === 0
  })
}

/** 刷新恢复：拉回在途行（pending/processing），轮询接管 */
async function hydrate() {
  try {
    const data = await listTranscriptions({ active: 1, page_size: 100 })
    items.value = data.items.map((it) => ({
      key: `srv-${it.id}`, name: it.file_name, ext: it.file_ext, size: it.file_size,
      dur: it.duration, status: it.status as RowStatus, item: it, error: "",
    }))
    startPolling()
  } catch {
    /* 拦截器已 toast */
  }
}

// ---------- 行内操作 ----------
// 识别结果点击展开/收起（tailect .r-text.full 同款）
const expanded = ref(new Set<string>())
function toggleExpand(key: string) {
  if (expanded.value.has(key)) expanded.value.delete(key)
  else expanded.value.add(key)
}

// 行内播放（tailect PC 对齐）：音频 = 结果格行内播放器；视频 = 行下本地视频对比面板；
// 单互斥槽（音频/视频共用），播放钮变「收起播放」
interface PlaySlot {
  key: string
  kind: "audio" | "video"
}
const activeSlot = ref<PlaySlot | null>(null)
const videoUrl = ref("")

function isVideoRow(row: QueueRow) {
  // 有本地文件按 MIME 判（麦克风录音是 audio/webm，不会误入视频面板）；
  // 无文件（水化行，不会是 done）按扩展名兜底
  return row.file ? row.file.type.indexOf("video/") === 0 : row.ext === "mp4" || row.ext === "mov"
}
function togglePlay(row: QueueRow) {
  if (!row.item) return
  const kind: "audio" | "video" = isVideoRow(row) ? "video" : "audio"
  if (activeSlot.value && activeSlot.value.key === row.key && activeSlot.value.kind === kind) {
    activeSlot.value = null
    return
  }
  activeSlot.value = { key: row.key, kind }
}
function loadRowBlob(row: QueueRow): Blob | Promise<Blob> {
  if (row.file && !isVideoRow(row)) return row.file // 本地音频即时播
  return fetchTranscriptionBlob((row.item as TranscriptionItem).file_url)
}
function releaseVideoUrl() {
  if (videoUrl.value) {
    URL.revokeObjectURL(videoUrl.value)
    videoUrl.value = ""
  }
}
// 槽切换时换视频 objectURL（pre-flush：先于面板行渲染就绪）
watch(activeSlot, () => {
  releaseVideoUrl()
  const slot = activeSlot.value
  if (slot && slot.kind === "video") {
    const row = items.value.find((r) => r.key === slot.key)
    if (row && row.file) videoUrl.value = URL.createObjectURL(row.file)
    else activeSlot.value = null // 视频只有会话内本地文件可播，兜底收起
  }
})
/** 行消失（移除/清除已完成）时收起播放槽 */
function clampActiveSlot() {
  const slot = activeSlot.value
  if (slot && !items.value.some((r) => r.key === slot.key)) activeSlot.value = null
}

const fixVisible = ref(false)
const fixTarget = ref<QueueRow | null>(null)
const fixItem = computed(() => (fixTarget.value ? fixTarget.value.item : null))

function openFix(row: QueueRow) {
  fixTarget.value = row
  fixVisible.value = true
}
function onFixed(item: TranscriptionItem) {
  if (fixTarget.value) {
    fixTarget.value.item = item
    fixTarget.value.status = item.status as RowStatus
  }
}

async function copyResult(row: QueueRow) {
  if (!row.item) return
  const text = displayText(row.item)
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

async function retry(row: QueueRow) {
  if (!row.item) return
  const item = await retryTranscription(row.item.id)
  row.item = item
  row.status = "pending"
  row.error = ""
  startPolling()
}

function removeRow(row: QueueRow) {
  items.value = items.value.filter((r) => r.key !== row.key) // 本地隐藏，历史页仍在
  clampActiveSlot()
}
function clearDone() {
  items.value = items.value.filter((r) => r.status !== "done")
  clampActiveSlot()
  ElMessage.success("已清除完成项")
}

// ---------- 舞台：点击选文件 / 拖放 ----------
const fileInput = ref<HTMLInputElement | null>(null)
const isDrag = ref(false)
const ACCEPT = TRANS_ALLOWED_EXTS.map((e) => `.${e}`).join(",")

function onStageClick(e: MouseEvent) {
  if ((e.target as HTMLElement).closest(".tr-stage-bar")) return // 工具条里的录音钮不触发选文件
  fileInput.value?.click()
}
function onInputChange(e: Event) {
  const inp = e.target as HTMLInputElement
  if (inp.files) {
    for (const f of Array.from(inp.files)) enqueueFile(f, f.name, f.size)
  }
  inp.value = "" // 允许重复选择同一文件
}
function onDrop(e: DragEvent) {
  isDrag.value = false
  const files = e.dataTransfer ? e.dataTransfer.files : null
  if (!files) return
  for (const f of Array.from(files)) enqueueFile(f, f.name, f.size)
}
function preventWindowDrop(e: DragEvent) {
  e.preventDefault() // 阻止浏览器直接打开音视频文件
}

// ---------- 内联麦克风（Recorder.vue 机制移植，15:00 硬停） ----------
const recording = ref(false)
const recSecs = ref(0)
// 30 根随机高度/相位的均衡条（录音态显形）
const recBars = Array.from({ length: 30 }, () => ({
  height: `${(6 + Math.random() * 22).toFixed(1)}px`,
  duration: `${(0.5 + Math.random() * 0.7).toFixed(2)}s`,
  delay: `${(Math.random() * 0.8).toFixed(2)}s`,
}))

let mediaRecorder: MediaRecorder | null = null
let stream: MediaStream | null = null
let chunks: BlobPart[] = []
let recTimer: ReturnType<typeof setInterval> | null = null

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
  for (const t of candidates) {
    if (MediaRecorder.isTypeSupported(t)) return t
  }
  return ""
}

async function toggleRec() {
  if (recording.value) {
    stopRec()
    return
  }
  let s: MediaStream
  try {
    s = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch {
    ElMessage.error("无法访问麦克风：请确认页面为 HTTPS 且已授予麦克风权限")
    return
  }
  stream = s
  const mimeType = pickMimeType()
  try {
    mediaRecorder = mimeType ? new MediaRecorder(s, { mimeType }) : new MediaRecorder(s)
  } catch {
    mediaRecorder = new MediaRecorder(s)
  }
  chunks = []
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data)
  }
  mediaRecorder.onstop = () => {
    const type = mediaRecorder?.mimeType || "audio/webm"
    const blob = new Blob(chunks, { type })
    const secs = recSecs.value
    cleanupRec()
    recording.value = false
    if (secs < 1) {
      ElMessage.warning("录音太短，已丢弃")
      return
    }
    // dome 命名：rec_{分}{秒}.webm（如 1:05 → rec_105.webm）
    const name = `rec_${Math.floor(secs / 60)}${String(secs % 60).padStart(2, "0")}.webm`
    enqueueFile(blob, name, blob.size)
  }
  mediaRecorder.start()
  recSecs.value = 0
  recording.value = true
  recTimer = setInterval(() => {
    recSecs.value += 1
    if (recSecs.value >= TRANS_MAX_MINUTES * 60) {
      ElMessage.warning(`已达 ${TRANS_MAX_MINUTES} 分钟上限，自动结束录音`)
      stopRec()
    }
  }, 1000)
}

function stopRec() {
  if (!recording.value || !mediaRecorder) return
  mediaRecorder.stop() // onstop 内 cleanup + 入队
}
function cleanupRec() {
  if (recTimer) {
    clearInterval(recTimer)
    recTimer = null
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop())
    stream = null
  }
  mediaRecorder = null
}

onMounted(() => {
  window.addEventListener("dragover", preventWindowDrop)
  window.addEventListener("drop", preventWindowDrop)
  void hydrate()
})
onUnmounted(() => {
  window.removeEventListener("dragover", preventWindowDrop)
  window.removeEventListener("drop", preventWindowDrop)
  releaseVideoUrl()
  if (recTimer) clearInterval(recTimer)
  if (stream) stream.getTracks().forEach((t) => t.stop())
})
</script>

<template>
  <div class="zp-page-head">
    <h1>语音转译工作台</h1>
    <span class="sub">说一段浙江话，或上传音频 / 视频，自动转写为文字</span>
    <div class="zp-head-actions">
      <router-link class="zp-btn zp-btn--ghost zp-btn--sm" to="/trans/history">历史记录 →</router-link>
    </div>
  </div>

  <div class="zp-alert zp-alert--info zp-mb-16">
    <span>上传或录音后自动排队识别：同一时刻仅一条在途，识别一条出一条；结果可在本页直接修正、复制，全部记录在「历史记录」长期保留。</span>
  </div>

  <!-- 声波舞台：上·邀请文字 / 底·录音工具条 -->
  <section
    class="tr-stage zp-mb-16"
    :class="{ 'is-drag': isDrag, 'is-recording': recording }"
    aria-label="拖入音频或视频文件，或点击选择"
    @click="onStageClick"
    @dragover.prevent="isDrag = true"
    @dragenter.prevent="isDrag = true"
    @dragleave="isDrag = false"
    @drop.prevent="onDrop"
  >
    <div class="tr-stage-main">
      <div class="tr-recbars" aria-hidden="true">
        <i
          v-for="(b, i) in recBars"
          :key="i"
          :style="{ height: b.height, animationDuration: b.duration, animationDelay: b.delay }"
        ></i>
      </div>
      <div class="tr-stage-center">
        <div class="st-title">将音频 / 视频文件拖到此处，或 <em>点击选择</em></div>
        <div class="st-sub">可多选，识别一条出一条</div>
      </div>
    </div>
    <div class="tr-stage-bar" @click.stop>
      <div class="tr-rec" :class="{ 'is-on': recording }">
        <button class="tr-rec-btn" type="button" aria-label="麦克风录音" @click="toggleRec">
          <svg v-if="!recording" width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3z"/><path d="M19 12a7 7 0 0 1-14 0H3a9 9 0 0 0 8 8.94V23h2v-2.06A9 9 0 0 0 21 12h-2z"/></svg>
          <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
        </button>
        <div class="tr-rec-info">
          <b>麦克风录音</b>
          <span class="tr-rec-hint-idle">点击开始 · 再点停止入队</span>
          <span class="tr-rec-hint-live">再次点击结束并加入队列</span>
        </div>
        <span class="tr-rec-timer">{{ fmtDur(recSecs) }}</span>
      </div>
      <div class="tr-stage-tip">音频 wav / mp3 / m4a / webm · 单个 ≤ {{ TRANS_MAX_MB }}MB　视频 mp4 / mov / webm · 自动提取音轨</div>
    </div>
  </section>
  <input
    ref="fileInput"
    type="file"
    multiple
    :accept="ACCEPT"
    style="display: none"
    aria-hidden="true"
    @change="onInputChange"
  />

  <!-- 本次识别 -->
  <div class="zp-card">
    <div class="zp-card-head">
      <h2>本次识别</h2>
      <span class="zp-card-sub">串行识别 · 同一时刻仅一条在途</span>
      <div class="zp-head-actions">
        <span class="zp-card-sub">{{ queueStat }}</span>
        <button class="zp-btn zp-btn--ghost zp-btn--sm" type="button" @click="clearDone">清除已完成</button>
      </div>
    </div>
    <div class="zp-card-body zp-card-body--flush">
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th style="width: 92px">状态</th>
              <th style="width: 240px">文件</th>
              <th style="width: 72px">时长</th>
              <th>识别结果</th>
              <th style="width: 210px">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in items" :key="row.key">
              <tr>
                <td>
                  <span class="zp-tag" :class="statusClass(row.status)">
                    <span v-if="row.status === 'processing'" class="tr-run-dot"></span>{{ statusLabel(row.status) }}
                  </span>
                </td>
                <td>
                  <div class="tr-f-name" :title="row.name">{{ row.name }}</div>
                  <div class="tr-f-meta">{{ fmtSize(row.size) }} · {{ row.ext }}</div>
                </td>
                <td class="num">{{ row.dur > 0 ? fmtDur(row.dur) : "—" }}</td>
                <td>
                  <span v-if="row.status === 'uploading' || row.status === 'pending'" class="zp-text-3">—</span>
                  <span v-else-if="row.status === 'processing'" class="tr-eq" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
                  <span v-else-if="row.status === 'failed'" class="tr-fail-hint">{{ failHint(row) }}</span>
                  <div
                    v-else-if="row.item"
                    class="tr-r"
                    :class="{ 'is-full': expanded.has(row.key) }"
                    title="点击展开/收起"
                    @click="toggleExpand(row.key)"
                  >
                    {{ displayText(row.item) }}
                    <span v-if="row.item.corrected" class="zp-tag zp-tag--gold">已修正</span>
                  </div>
                  <TransRowPlayer
                    v-if="row.status === 'done' && row.item && activeSlot && activeSlot.key === row.key && activeSlot.kind === 'audio'"
                    :load="() => loadRowBlob(row)"
                    @closed="activeSlot = null"
                  />
                </td>
                <td>
                  <template v-if="row.status === 'done' && row.item">
                    <button class="zp-btn zp-btn--text" type="button" @click="togglePlay(row)">
                      {{ activeSlot && activeSlot.key === row.key ? "收起播放" : "播放" }}
                    </button>
                    <button class="zp-btn zp-btn--text" type="button" @click="openFix(row)">修正</button>
                    <button class="zp-btn zp-btn--text" type="button" @click="copyResult(row)">复制</button>
                  </template>
                  <button v-if="row.status === 'failed' && row.item" class="zp-btn zp-btn--text" type="button" @click="retry(row)">重试</button>
                  <button class="zp-btn zp-btn--text is-danger" type="button" @click="removeRow(row)">移除</button>
                </td>
              </tr>
              <!-- 视频对比面板（tailect cmpPanel）：行下方插入，原生 video 播本地文件 + 转写文字 -->
              <tr
                v-if="activeSlot && activeSlot.key === row.key && activeSlot.kind === 'video'"
                class="tr-vcmp"
              >
                <td colspan="5">
                  <div class="tr-vcmp-inner">
                    <div class="tr-vcmp-video">
                      <video class="tr-vcmp-player" controls preload="metadata" :src="videoUrl"></video>
                      <div class="tr-vcmp-note">本地面板播放原视频 · 服务端仅保留提取的音轨</div>
                    </div>
                    <div class="tr-vcmp-text">
                      <div class="tr-vcmp-lab">转写文字 · 边看边校对</div>
                      <div class="tr-vcmp-txt">{{ row.item ? displayText(row.item) || "（无文字）" : "" }}</div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <div v-if="items.length === 0" class="tr-empty is-show">
        <div class="glyph" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
        <b>还没有识别任务</b>
        <span>把音频 / 视频文件拖到上方，或点击「麦克风录音」说一段浙江话；<br />识别一条，出一条结果。</span>
      </div>
    </div>
  </div>

  <TransFixDialog v-model="fixVisible" :item="fixItem" @saved="onFixed" />
</template>

<style scoped>
/* ===== 声波舞台（tailect PC 形态：上·邀请文字 / 底·录音工具条） ===== */
.tr-stage {
  position: relative;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--white);
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--radius-lg);
  transition: border-color 0.16s, background 0.16s, box-shadow 0.16s;
}
.tr-stage:hover {
  border-color: var(--blue-500);
  background: #fdfeff;
}
.tr-stage.is-drag {
  border-color: var(--navy-700);
  border-style: solid;
  background: var(--blue-50);
  box-shadow: 0 0 0 4px var(--blue-100);
}
.tr-stage-main {
  position: relative;
  height: 132px;
}
.tr-stage-main::before {
  content: "";
  position: absolute;
  left: 50%;
  top: 40%;
  width: 520px;
  height: 150px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(44, 107, 176, 0.1), transparent 70%);
  opacity: 0.7;
  transition: opacity 0.2s;
  pointer-events: none;
}
.tr-stage.is-drag .tr-stage-main::before {
  opacity: 1;
}
.tr-stage-center {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  padding: 0 24px;
}
.st-title {
  font-size: 15.5px;
  font-weight: 600;
  color: var(--ink);
}
.st-title em {
  font-style: normal;
  color: var(--navy-700);
  cursor: pointer;
}
.st-title em:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
.st-sub {
  font-size: 12.5px;
  color: var(--ink-3);
}
.tr-stage.is-recording .tr-stage-center {
  display: none;
}
.tr-recbars {
  position: absolute;
  inset: 0;
  display: none;
  align-items: center;
  justify-content: center;
  gap: 5px;
}
.tr-stage.is-recording .tr-recbars {
  display: flex;
}
.tr-recbars i {
  width: 3px;
  border-radius: 1.5px;
  background: rgba(197, 48, 48, 0.65);
  height: 14px;
  animation: tr-recbar 1s ease-in-out infinite alternate;
}
@keyframes tr-recbar {
  from {
    transform: scaleY(0.22);
  }
  to {
    transform: scaleY(2.4);
  }
}
.tr-stage-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 16px;
  border-top: 1px solid var(--line);
}
.tr-rec {
  display: flex;
  align-items: center;
  gap: 12px;
}
.tr-rec-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  cursor: pointer;
  flex: none;
  border: 1.5px solid var(--navy-700);
  background: var(--white);
  color: var(--navy-700);
  display: grid;
  place-items: center;
  transition: border-color 0.12s, color 0.12s, background 0.12s;
}
.tr-rec-btn:hover {
  background: var(--blue-50);
}
.tr-rec-info b {
  display: block;
  font-size: 13px;
  font-weight: 600;
}
.tr-rec-info span {
  display: block;
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 2px;
}
.tr-rec-timer {
  font-variant-numeric: tabular-nums;
  font-size: 17px;
  font-weight: 650;
  color: var(--danger);
  display: none;
}
.tr-rec.is-on .tr-rec-timer {
  display: block;
}
.tr-rec.is-on .tr-rec-btn {
  border-color: var(--danger);
  color: var(--danger);
  background: var(--danger-bg);
}
.tr-rec.is-on .tr-rec-info b {
  color: var(--danger);
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.tr-rec.is-on .tr-rec-info b::before {
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
  background: var(--danger);
  animation: tr-recpulse 1.2s ease-in-out infinite;
}
@keyframes tr-recpulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.25;
  }
}
.tr-rec-hint-live {
  display: none;
}
.tr-rec.is-on .tr-rec-hint-live {
  display: block;
}
.tr-rec.is-on .tr-rec-hint-idle {
  display: none;
}
.tr-stage-tip {
  margin-left: auto;
  font-size: 12px;
  color: var(--ink-3);
  white-space: nowrap;
}
/* ===== 队列表 ===== */
.tr-run-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--navy-700);
  margin-right: 5px;
  animation: tr-pulse 1s infinite;
}
@keyframes tr-pulse {
  50% {
    opacity: 0.25;
  }
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
/* ===== 视频对比面板（tailect cmpPanel 移植） ===== */
.tr-vcmp > td {
  padding: 0;
  background: #fafcfd;
  border-top: 1px dashed var(--line);
}
.tr-vcmp:hover {
  background: #fafcfd; /* 盖 zp-table 行悬停条纹 */
}
.tr-vcmp-inner {
  display: grid;
  grid-template-columns: minmax(300px, 7fr) minmax(240px, 5fr);
}
@media (max-width: 900px) {
  .tr-vcmp-inner {
    grid-template-columns: 1fr;
  }
}
.tr-vcmp-video {
  padding: 16px 4px 16px 16px;
  min-width: 0;
}
.tr-vcmp-player {
  display: block;
  width: 100%;
  height: 320px; /* aspect-ratio 是 Chrome 88+，基线 80 用固定高 */
  background: #0c1a24;
  border-radius: 10px;
}
.tr-vcmp-note {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-3);
}
.tr-vcmp-text {
  padding: 16px;
  border-left: 1px solid var(--line);
  min-width: 0;
}
.tr-vcmp-lab {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
  letter-spacing: 0.06em;
}
.tr-vcmp-txt {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink);
  white-space: pre-wrap;
  max-height: 300px;
  overflow: auto;
}
.tr-empty {
  display: none;
  padding: 72px 20px 64px;
  text-align: center;
}
.tr-empty.is-show {
  display: block;
}
.tr-empty .glyph {
  width: 56px;
  height: 40px;
  margin: 0 auto 16px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
}
.tr-empty .glyph i {
  width: 4px;
  border-radius: 2px;
  background: var(--line-strong);
  transform-origin: bottom;
  animation: tr-glyph 1.6s ease-in-out infinite;
}
.tr-empty .glyph i:nth-child(1) {
  height: 16px;
}
.tr-empty .glyph i:nth-child(2) {
  height: 28px;
  animation-delay: 0.2s;
}
.tr-empty .glyph i:nth-child(3) {
  height: 36px;
}
.tr-empty .glyph i:nth-child(4) {
  height: 22px;
  animation-delay: 0.35s;
}
.tr-empty .glyph i:nth-child(5) {
  height: 12px;
}
@keyframes tr-glyph {
  0%,
  100% {
    transform: scaleY(0.4);
  }
  50% {
    transform: scaleY(1);
  }
}
.tr-empty b {
  display: block;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
}
.tr-empty span {
  display: block;
  font-size: 12.5px;
  color: var(--ink-3);
  margin-top: 7px;
  line-height: 1.8;
}
</style>

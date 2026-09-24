<script setup lang="ts">
/**
 * 录音采集（dome/record.html 1:1）：任务进度 + 四步步骤条 + 领取文本（120s 倒计时）
 * + 录音（Recorder）+ 试听/上传 + 上传后质检示例 + 底部提示
 */
import { computed, onMounted, onUnmounted, ref } from "vue"
import { ElMessage } from "element-plus"
import { useAudioStore } from "@/stores/audio"
import { getMyTasks, type TaskProgress } from "@/api/tasks"
import {
  assignText,
  createCustomText,
  releaseAssignment,
  type AssignedText,
} from "@/api/texts"
import { uploadRecording } from "@/api/recordings"
import { categoryLabel, categoryTagClass } from "@/constants/category"
import Recorder from "@/components/Recorder.vue"

const steps = ["领取文本", "开始录音", "上传", "质检入库"]

const audio = useAudioStore()
const task = ref<TaskProgress | null>(null)
const text = ref<AssignedText | null>(null)
const blob = ref<Blob | null>(null)
const recordUrl = ref("")
const recordSeconds = ref(0)
const recordSize = ref(0)
const recording = ref(false)
const uploading = ref(false)
const countdown = ref(0)
const showCustom = ref(false)
const customContent = ref("")

let countdownTimer: ReturnType<typeof setInterval> | null = null

const step = computed(() => {
  if (!text.value) return 0
  if (!blob.value) return 1
  return 2
})
function stepClass(i: number) {
  if (step.value > i) return "zp-step is-done"
  if (step.value === i) return "zp-step is-active"
  return "zp-step"
}

const pct = computed(() => {
  const t = task.value
  if (!t || t.target_count <= 0) return 0
  return Math.min(100, Math.round((t.done / t.target_count) * 100))
})
const taskRemaining = computed(() => {
  const t = task.value
  return t ? Math.max(0, t.target_count - t.done) : 0
})
const sizeLabel = computed(() => `${Math.max(1, Math.round(recordSize.value / 1024))} KB`)

function fmt(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.max(0, Math.floor(s % 60))
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}

async function loadTask() {
  try {
    const data = await getMyTasks()
    task.value = data.recording
  } catch {
    task.value = null
  }
}

function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}
function startCountdown() {
  stopCountdown()
  countdown.value = text.value?.remaining_seconds ?? 120
  countdownTimer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      stopCountdown()
      text.value = null
      ElMessage.warning("分配已超时释放，请重新领取文本")
    }
  }, 1000)
}

async function claimText() {
  try {
    const t = await assignText()
    text.value = t
    startCountdown()
  } catch {
    text.value = null
    stopCountdown()
  }
}

async function skipText() {
  if (text.value) {
    try {
      await releaseAssignment(text.value.text_id)
    } catch {
      /* 忽略释放失败，继续领取 */
    }
  }
  await claimText()
}

function openCustom() {
  customContent.value = ""
  showCustom.value = true
}
async function submitCustom() {
  const content = customContent.value.trim()
  if (!content) {
    ElMessage.warning("请输入文本内容")
    return
  }
  try {
    const t = await createCustomText(content)
    text.value = t
    showCustom.value = false
    startCountdown()
  } catch {
    /* 拦截器已报错 */
  }
}

function onRecorderStop(b: Blob, secs: number) {
  recording.value = false
  blob.value = b
  recordSeconds.value = secs
  recordSize.value = b.size
  if (recordUrl.value) URL.revokeObjectURL(recordUrl.value)
  recordUrl.value = URL.createObjectURL(b)
}

function togglePreview() {
  if (recordUrl.value) audio.toggle(recordUrl.value)
}

function reRecord() {
  audio.stop()
  if (recordUrl.value) URL.revokeObjectURL(recordUrl.value)
  recordUrl.value = ""
  blob.value = null
  recordSeconds.value = 0
  recordSize.value = 0
}

async function upload() {
  if (!blob.value || !text.value) return
  uploading.value = true
  try {
    await uploadRecording(blob.value, text.value.text_id)
    ElMessage.success("已提交质检，通过后计入任务进度")
    audio.stop()
    if (recordUrl.value) URL.revokeObjectURL(recordUrl.value)
    recordUrl.value = ""
    blob.value = null
    recordSeconds.value = 0
    recordSize.value = 0
    void loadTask()
    await claimText()
  } catch {
    /* 拦截器已报错，保留录音供重试 */
  } finally {
    uploading.value = false
  }
}

onMounted(() => {
  void loadTask()
  void claimText()
})
onUnmounted(() => {
  stopCountdown()
  audio.stop()
  if (recordUrl.value) URL.revokeObjectURL(recordUrl.value)
})
</script>

<template>
  <div class="zp-page-head">
    <h1>录音采集</h1>
    <span class="sub">用本地方言朗读下方文本，一条文本只需录制一次</span>
  </div>

  <!-- 我的任务进度 -->
  <div class="zp-card zp-mb-16">
    <div class="zp-card-body zp-flex">
      <span class="zp-tag zp-tag--navy">我的任务</span>
      <template v-if="task">
        <div class="zp-progress" style="flex: 1">
          <div class="track"><div class="fill" :style="{ width: pct + '%' }"></div></div>
          <span class="num"><b>{{ task.done }}</b> / {{ task.target_count }} 条</span>
        </div>
        <span class="zp-text-3">剩余 {{ taskRemaining }} 条</span>
      </template>
      <span v-else class="zp-text-3" style="flex: 1">暂无录音任务，请联系管理员下发</span>
    </div>
  </div>

  <!-- 步骤 -->
  <div class="zp-steps">
    <div v-for="(s, i) in steps" :key="s" :class="stepClass(i)">{{ s }}</div>
  </div>

  <!-- 文本卡 -->
  <div class="zp-card zp-mb-16">
    <div class="zp-card-head">
      <h2>本次文本</h2>
      <template v-if="text">
        <span class="zp-tag" :class="categoryTagClass(text.category)">{{ categoryLabel(text.category) }}</span>
        <span class="zp-tag zp-tag--gray">{{ text.dialect || "通用" }}</span>
        <span class="zp-card-sub" style="margin-left: auto; color: var(--warn)">
          分配剩余 <b class="zp-serif" style="font-size: 16px">{{ fmt(countdown) }}</b>，超时自动释放
        </span>
      </template>
    </div>
    <div class="zp-card-body record-text-body">
      <template v-if="text">
        <p class="zp-dialect">{{ text.content }}</p>
        <div class="zp-flex zp-mt-16">
          <button class="zp-btn zp-btn--ghost" type="button" @click="skipText">换一条</button>
          <button class="zp-btn zp-btn--ghost" type="button" @click="openCustom">自定义文本</button>
          <span class="zp-text-3" style="margin-left: auto">分配的文本 2 分钟内有效，请尽快录制</span>
        </div>
      </template>
      <div v-else class="zp-empty">
        <p>暂无可用文本</p>
        <button class="zp-btn zp-btn--primary" type="button" @click="claimText">重新获取</button>
      </div>
    </div>
  </div>

  <!-- 录音 / 完成态卡 -->
  <div class="zp-card zp-mb-16">
    <div class="zp-card-head">
      <h2>{{ blob ? "录制完成后" : "正在录音" }}</h2>
      <span v-if="recording" class="zp-tag zp-tag--danger" style="margin-left: auto">● 录制中</span>
      <span v-else-if="blob" class="zp-card-sub" style="margin-left: auto">请试听确认后上传</span>
    </div>
    <div class="zp-card-body">
      <template v-if="blob">
        <div class="zp-audio-row">
          <button class="play" type="button" aria-label="播放" @click="togglePreview">▶</button>
          <span class="meta"><b>试听录音</b> · {{ text?.content || "" }}</span>
          <span class="time">{{ fmt(recordSeconds) }} · {{ sizeLabel }}</span>
        </div>
        <div class="zp-flex zp-mt-16">
          <button class="zp-btn zp-btn--ghost" type="button" @click="reRecord">重新录制</button>
          <button
            class="zp-btn zp-btn--primary zp-btn--lg zp-btn--block"
            type="button"
            :disabled="uploading"
            @click="upload"
          >
            {{ uploading ? "上传中…" : "上传录音" }}
          </button>
        </div>
      </template>
      <Recorder v-else-if="text" @start="recording = true" @stop="onRecorderStop" />
      <div v-else class="zp-empty"><p>请先领取文本再开始录音</p></div>
    </div>
  </div>

  <!-- 上传后质检（示例） -->
  <div class="zp-card zp-mb-16">
    <div class="zp-card-head">
      <h2>上传后质检</h2>
      <span class="zp-card-sub">系统自动送方言转译接口比对，无需等待即可继续录下一条</span>
    </div>
    <div class="zp-card-body">
      <div class="zp-flex zp-mb-16">
        <span class="zp-tag zp-tag--warn">待质检</span>
        <span style="flex: 1; font-size: 13px; color: var(--ink-2)">已上传，等待转译接口返回比对结果</span>
      </div>
      <div class="zp-flex zp-mb-16">
        <span class="zp-tag zp-tag--green">质检通过</span>
        <span style="flex: 1; font-size: 13px; color: var(--ink-2)">相似度 ≥ 50%，正式入库并计入任务进度</span>
      </div>
      <div class="zp-flex">
        <span class="zp-tag zp-tag--danger">未通过</span>
        <span style="flex: 1; font-size: 13px; color: var(--ink-2)">录音保留在「历史录音」中，可查看比对详情，对应文本可重新领取重录</span>
      </div>
    </div>
  </div>

  <div class="zp-alert zp-alert--info">
    <span>
      录制提示：请在安静环境中，用本地方言自然朗读；建议时长 5～20 秒。上传后系统自动质检：
      与方言转译接口返回文本比对，相似度 ≥ 50% 正式入库并计入任务进度，未通过的录音将保留在「历史录音」中并标记为未通过，对应文本可重新领取录制。
    </span>
  </div>

  <!-- 自定义文本弹窗 -->
  <div v-if="showCustom" class="zp-dialog-mask is-open">
    <div class="zp-dialog" role="dialog" aria-label="自定义文本">
      <div class="zp-dialog-head">
        <h3>自定义文本</h3>
        <button class="zp-x" type="button" aria-label="关闭" @click="showCustom = false">×</button>
      </div>
      <div class="zp-dialog-body">
        <div class="zp-field">
          <label>文本内容<span class="req">*</span></label>
          <textarea
            v-model="customContent"
            class="zp-textarea"
            placeholder="输入一句想录制的方言文本，建议不超过 40 字"
          ></textarea>
        </div>
        <p class="zp-hint">自定义文本将按你所属区域自动归入「自定义」类别，同样 2 分钟内有效。</p>
      </div>
      <div class="zp-dialog-foot">
        <button class="zp-btn zp-btn--ghost" type="button" @click="showCustom = false">取消</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="submitCustom">保存并领取</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 本次文本卡：放大占版面主体，内容垂直居中，底部留出呼吸空间 */
.record-text-body {
  min-height: 220px;
  padding-bottom: 36px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.record-text-body .zp-dialect {
  font-size: 26px;
  line-height: 1.9;
}
</style>

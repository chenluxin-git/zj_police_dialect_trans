<script setup lang="ts">
/**
 * 录音组件（dome/record.html 演进）：MediaRecorder 录音 + 开始/停止切换钮 + 计时
 * （2026-09-22 用户要求：去掉中央圆形脉冲钮改为文字按钮；去掉波纹图案）
 * - props {disabled}：无文本分配时禁用
 * - emits start（开始录音）/ stop(blob, seconds)（停止并产出 Blob）
 * - mimeType 择优 webm;codecs=opus → webm → mp4；getUserMedia 失败给出明确指引
 */
import { onUnmounted, ref } from "vue"
import { ElMessage } from "element-plus"

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{
  (e: "start"): void
  (e: "stop", blob: Blob, seconds: number): void
}>()

const recording = ref(false)
const seconds = ref(0)

let mediaRecorder: MediaRecorder | null = null
let stream: MediaStream | null = null
let chunks: BlobPart[] = []
let timer: ReturnType<typeof setInterval> | null = null

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
  for (const t of candidates) {
    if (MediaRecorder.isTypeSupported(t)) return t
  }
  return ""
}

async function start() {
  if (recording.value) return
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
    const secs = seconds.value
    cleanup()
    emit("stop", blob, secs)
  }
  mediaRecorder.start()
  seconds.value = 0
  recording.value = true
  emit("start")
  timer = setInterval(() => {
    seconds.value += 1
  }, 1000)
}

function stop() {
  if (!recording.value || !mediaRecorder) return
  mediaRecorder.stop() // onstop 内 cleanup + emit
}

function cleanup() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop())
    stream = null
  }
  mediaRecorder = null
  recording.value = false
}

function format(s: number) {
  const m = Math.floor(s / 60)
  const ss = s % 60
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (stream) stream.getTracks().forEach((t) => t.stop())
})
</script>

<template>
  <div class="zp-center" style="padding: 14px 16px 12px">
    <button
      v-if="recording"
      class="zp-btn zp-btn--danger"
      type="button"
      @click="stop()"
    >
      停止录音
    </button>
    <button
      v-else
      class="zp-btn zp-btn--primary"
      type="button"
      :disabled="disabled"
      @click="start()"
    >
      开始录音
    </button>
    <p class="zp-timer zp-mt-8">{{ format(seconds) }}</p>
    <p class="zp-text-3 zp-mt-8">
      {{ recording ? "正在录音…点击上方按钮停止" : "建议录音时长 5～20 秒" }}
    </p>
  </div>
</template>

<style scoped>
.zp-timer {
  font-size: 24px;
}
</style>

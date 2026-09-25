<script setup lang="ts">
/**
 * 行内音频播放器（tailect pc/rowPlayer.js 的 Vue 移植，zp 视觉）
 * - 隐藏 <audio> 只做引擎（seek/事件/格式兼容），UI 全自绘：
 *   播放/暂停/重播圆钮 + 3px 细进度条（点/拖 seek，pointer capture）+ cur/total 时间
 * - load prop 只在 onMounted 调一次（父传内联箭头函数，身份随渲染变化，不能 watch）
 * - blob objectURL 生命周期自管：卸载 revoke + pause/清 src/load 释放解码器
 * - 加载失败只 emit closed（axios 拦截器已统一 toast，不双弹）；
 *   audio @error 媒体解码错误才 ElMessage.error
 */
import { onMounted, onUnmounted, ref } from "vue"
import { ElMessage } from "element-plus"

const props = defineProps<{
  /** 取音频 blob：本地 File（即时）或服务端 WAV（网络） */
  load: () => Blob | Promise<Blob>
  /** 挂载后自动开播，默认 true */
  autoplay?: boolean
}>()
const emit = defineEmits<{ (e: "closed"): void }>()

const audioRef = ref<HTMLAudioElement | null>(null)
const trackRef = ref<HTMLElement | null>(null)
const loading = ref(true)
const playing = ref(false)
const ended = ref(false)
const cur = ref(0)
const dur = ref(0)
const dragging = ref(false)

let objectUrl = ""
let disposed = false

function fmtTime(sec: number) {
  if (!sec || !isFinite(sec)) return "0:00"
  const s = Math.floor(sec)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

function toggle() {
  const el = audioRef.value
  if (!el) return
  if (ended.value) {
    el.currentTime = 0
    ended.value = false
  }
  if (el.paused) el.play().catch(() => {})
  else el.pause()
}

// 点/拖进度条 seek（pointer capture，同 tailect）
function seekTo(x: number) {
  const track = trackRef.value
  const el = audioRef.value
  if (!track || !el || !isFinite(el.duration) || el.duration <= 0) return
  const rect = track.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (x - rect.left) / rect.width))
  el.currentTime = ratio * el.duration
  ended.value = false
}
function onDown(e: PointerEvent) {
  dragging.value = true
  try {
    trackRef.value?.setPointerCapture(e.pointerId)
  } catch {
    /* 捕获失败退化为仅点击 seek */
  }
  seekTo(e.clientX)
}
function onMove(e: PointerEvent) {
  if (dragging.value) seekTo(e.clientX)
}
function onUp(e: PointerEvent) {
  dragging.value = false
  try {
    trackRef.value?.releasePointerCapture(e.pointerId)
  } catch {
    /* 未捕获时忽略 */
  }
}

function onMeta() {
  const el = audioRef.value
  if (el) dur.value = isFinite(el.duration) ? el.duration : 0
}
function onTime() {
  const el = audioRef.value
  if (el) cur.value = el.currentTime || 0
}
function onMediaError() {
  ElMessage.error("音频播放失败")
  emit("closed")
}

onMounted(async () => {
  try {
    const blob = await props.load()
    if (disposed) return
    const el = audioRef.value
    if (!el) return
    objectUrl = URL.createObjectURL(blob)
    el.src = objectUrl
    el.load()
    if (props.autoplay !== false) el.play().catch(() => {})
  } catch {
    if (!disposed) emit("closed") // 拦截器已 toast，这里只收起
    return
  } finally {
    if (!disposed) loading.value = false
  }
})

onUnmounted(() => {
  disposed = true
  const el = audioRef.value
  if (el) {
    try {
      el.pause()
    } catch {
      /* 忽略 */
    }
    el.removeAttribute("src")
    el.load() // 释放解码器，防悬空 blob: src 拖住资源
  }
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = ""
  }
})
</script>

<template>
  <div class="tr-player">
    <button
      class="tr-pl-btn"
      type="button"
      :aria-label="playing ? '暂停' : ended ? '重播' : '播放'"
      @click="toggle"
    >
      <svg v-if="playing" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>
      <svg v-else-if="ended" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 5V1L7 6l5 5V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z"/></svg>
      <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
    </button>
    <span
      ref="trackRef"
      class="tr-pl-track"
      @pointerdown.prevent="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
    >
      <i :style="{ width: (dur > 0 ? (cur / dur) * 100 : 0) + '%' }"></i>
    </span>
    <span class="tr-pl-time">{{ fmtTime(cur) }} / {{ fmtTime(dur) }}</span>
    <span v-if="loading" class="tr-pl-loading">加载中…</span>
    <audio
      ref="audioRef"
      style="display: none"
      @play="playing = true; ended = false"
      @pause="playing = false"
      @ended="playing = false; ended = true"
      @timeupdate="onTime"
      @loadedmetadata="onMeta"
      @error="onMediaError"
    ></audio>
  </div>
</template>

<style scoped>
/* tailect pc.css .player/.pl-* 的 zp 化移植 */
.tr-player {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 9px;
  max-width: 420px;
}
.tr-pl-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  background: var(--white);
  color: var(--navy-700);
  cursor: pointer;
  flex: none;
  display: grid;
  place-items: center;
  transition: border-color 0.12s, background 0.12s;
}
.tr-pl-btn:hover {
  border-color: var(--navy-700);
  background: var(--blue-50);
}
.tr-pl-track {
  flex: 1;
  height: 3px;
  border-radius: 2px;
  background: var(--line);
  cursor: pointer;
  touch-action: none;
  user-select: none;
}
.tr-pl-track i {
  display: block;
  height: 100%;
  width: 0%;
  border-radius: 2px;
  background: var(--blue-500);
  transition: width 0.1s linear;
}
.tr-pl-time {
  font-size: 12px;
  color: var(--ink-3);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.tr-pl-loading {
  font-size: 12px;
  color: var(--ink-3);
  white-space: nowrap;
}
</style>

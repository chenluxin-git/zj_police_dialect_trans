<script setup lang="ts">
/**
 * 录音标注（dome/annotation.html 1:1）：任务进度 + 领取音频（180s 锁倒计时 + 续期）
 * + AudioPlayer 试听 + 是否方言分段控件 + 译文必填 + 提交后自动下一条
 */
import { computed, onMounted, onUnmounted, ref } from "vue"
import { ElMessage } from "element-plus"
import { getMyTasks, type TaskProgress } from "@/api/tasks"
import {
  nextAudio,
  refreshAnnotationAssignment,
  submitAnnotation,
  type NextAudio,
} from "@/api/annotations"
import AudioPlayer from "@/components/AudioPlayer.vue"

const LOCK_SECONDS = 180

const task = ref<TaskProgress | null>(null)
const audioItem = ref<NextAudio | null>(null)
const isDialect = ref(true)
const translation = ref("")
const submitting = ref(false)
const countdown = ref(LOCK_SECONDS)

let countdownTimer: ReturnType<typeof setInterval> | null = null

const pct = computed(() => {
  const t = task.value
  if (!t || t.target_count <= 0) return 0
  return Math.min(100, Math.round((t.done / t.target_count) * 100))
})
const taskRemaining = computed(() => {
  const t = task.value
  return t ? Math.max(0, t.target_count - t.done) : 0
})

function fmt(s: number) {
  const m = Math.floor(s / 60)
  const ss = Math.max(0, Math.floor(s % 60))
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}

async function loadTask() {
  try {
    const data = await getMyTasks()
    task.value = data.annotation
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
function startCountdown(secs: number) {
  stopCountdown()
  countdown.value = secs
  countdownTimer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      stopCountdown()
      audioItem.value = null
      ElMessage.warning("分配已超时释放，请重新获取音频")
    }
  }, 1000)
}

async function loadNext() {
  try {
    const a = await nextAudio()
    audioItem.value = a
    isDialect.value = true
    translation.value = ""
    startCountdown(LOCK_SECONDS)
  } catch {
    audioItem.value = null
    stopCountdown()
  }
}

async function refresh() {
  if (!audioItem.value) return
  await refreshAnnotationAssignment(audioItem.value.file_id)
  startCountdown(LOCK_SECONDS)
  ElMessage.success("分配已续期")
}

async function submit() {
  if (!audioItem.value) return
  if (isDialect.value && !translation.value.trim()) {
    ElMessage.warning("判定为方言时需填写普通话翻译")
    return
  }
  submitting.value = true
  try {
    await submitAnnotation({
      file_id: audioItem.value.file_id,
      is_dialect: isDialect.value,
      translation: isDialect.value ? translation.value.trim() : "",
    })
    ElMessage.success("标注已提交，自动领取下一条")
    void loadTask()
    await loadNext()
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void loadTask()
  void loadNext()
})
onUnmounted(() => stopCountdown())
</script>

<template>
  <div class="zp-page-head">
    <h1>录音标注</h1>
    <span class="sub">听音频，判断是否为方言，并翻译成普通话</span>
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
      <span v-else class="zp-text-3" style="flex: 1">暂无标注任务，请联系管理员下发</span>
    </div>
  </div>

  <!-- 当前音频 -->
  <div class="zp-card zp-mb-16">
    <div class="zp-card-head">
      <h2>当前音频</h2>
      <span class="zp-card-sub">{{ audioItem?.file_name || "" }}</span>
      <span v-if="audioItem" class="zp-card-sub" style="margin-left: auto; color: var(--warn)">
        分配剩余 <b class="zp-serif" style="font-size: 16px">{{ fmt(countdown) }}</b>，超时自动释放
      </span>
    </div>
    <div class="zp-card-body">
      <template v-if="audioItem">
        <AudioPlayer :src="audioItem.file_url" />
        <p class="zp-text-3 zp-center">只分配给你，3 分钟内提交有效</p>
        <div class="zp-flex zp-mt-16" style="justify-content: center">
          <button class="zp-btn zp-btn--ghost" type="button" @click="refresh">续期</button>
        </div>
      </template>
      <div v-else class="zp-empty">
        <p>暂无待标注音频</p>
        <button class="zp-btn zp-btn--primary" type="button" @click="loadNext">重新获取</button>
      </div>
    </div>
  </div>

  <!-- 标注表单 -->
  <div class="zp-card zp-mb-16">
    <div class="zp-card-head"><h2>标注结果</h2></div>
    <div class="zp-card-body">
      <div class="zp-field">
        <label>这段音频是否为方言<span class="req">*</span></label>
        <div class="zp-seg" role="group" aria-label="是否为方言">
          <button type="button" :class="{ 'is-active': isDialect }" @click="isDialect = true">是方言</button>
          <button type="button" :class="{ 'is-active': !isDialect }" @click="isDialect = false">不是方言</button>
        </div>
      </div>
      <div class="zp-field">
        <label>普通话翻译<span class="req">*</span></label>
        <textarea
          v-model="translation"
          class="zp-textarea"
          placeholder="请输入这段音频对应的普通话意思"
        ></textarea>
        <p class="zp-hint">判定为「是方言」时必填；判定为「不是方言」时无需填写</p>
      </div>
      <button
        class="zp-btn zp-btn--primary zp-btn--lg zp-btn--block"
        type="button"
        :disabled="submitting"
        @click="submit"
      >
        {{ submitting ? "提交中…" : "提交标注" }}
      </button>
    </div>
  </div>

  <div class="zp-alert zp-alert--info">
    <span>
      标注提示：请完整听完音频再判定；方言指与普通话差异明显的本地方言口音及用语；同一段音频只需标注一次。
    </span>
  </div>
</template>

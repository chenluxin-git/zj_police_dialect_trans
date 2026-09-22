<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { api } from "@/api/http"
import { listMessages, messageTag, type MessageItem } from "@/api/messages"
import { useUserStore } from "@/stores/user"
import { useMessageStore } from "@/stores/message"

interface TaskProgress {
  target_count: number
  base_count: number
  done: number
  status: string
  note: string
}
interface TasksData {
  recording: TaskProgress | null
  annotation: TaskProgress | null
}
interface RecordingItem {
  id: number
  text_id: number
  text_content: string
  category: string
  dialect: string
  duration: number
  file_size: number
  qc_status: string
  created_at: string
  file_url: string
}
interface RecordingPage {
  total: number
  page: number
  page_size: number
  items: RecordingItem[]
}

const userStore = useUserStore()
const messageStore = useMessageStore()

const recordingTask = ref<TaskProgress | null>(null)
const annotationTask = ref<TaskProgress | null>(null)
const recentRecordings = ref<RecordingItem[]>([])
const latestMessages = ref<MessageItem[]>([])

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return "夜深了"
  if (h < 9) return "早上好"
  if (h < 12) return "上午好"
  if (h < 14) return "中午好"
  if (h < 18) return "下午好"
  return "晚上好"
})

const today = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
})

function pct(done: number, target: number) {
  if (target <= 0) return 0
  return Math.min(100, Math.round((done / target) * 100))
}

function remaining(task: TaskProgress) {
  return Math.max(0, task.target_count - task.done)
}

const CATEGORY: Record<string, { label: string; cls: string }> = {
  police: { label: "警情", cls: "zp-tag--blue" },
  life: { label: "生活", cls: "zp-tag--green" },
  dirty: { label: "俚语", cls: "zp-tag--warn" },
  place: { label: "地名", cls: "zp-tag--gold" },
  custom: { label: "自定义", cls: "zp-tag--gray" },
}

function categoryTag(category: string) {
  return CATEGORY[category]?.cls || "zp-tag--gray"
}

function categoryLabel(category: string) {
  return CATEGORY[category]?.label || "其他"
}

function pad(n: number) {
  return n < 10 ? "0" + n : String(n)
}

function fmtShort(s: string) {
  const d = new Date(s)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(async () => {
  try {
    const tasks = await api.get<TasksData>("/tasks/my")
    recordingTask.value = tasks.recording
    annotationTask.value = tasks.annotation
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
  try {
    const rec = await api.get<RecordingPage>("/recordings", { params: { page: 1, page_size: 3 } })
    recentRecordings.value = rec.items
  } catch {
    /* noop */
  }
  try {
    const msg = await listMessages({ box: "all", page: 1, page_size: 2 })
    latestMessages.value = msg.items
  } catch {
    /* noop */
  }
})
</script>

<template>
  <div>
    <!-- 问候 -->
    <div class="zp-greet zp-mb-16">
      <h1>{{ greeting }}，{{ userStore.user?.real_name || "民警" }}</h1>
      <p>浙江公安方言语料采集平台 · {{ today }}</p>
    </div>

    <!-- 我的任务 -->
    <div class="zp-grid-2 zp-mb-16">
      <!-- 录音任务 -->
      <div class="zp-card">
        <div class="zp-card-head"><h2>录音任务</h2><span class="zp-card-sub">管理员下达</span></div>
        <div class="zp-card-body">
          <template v-if="recordingTask">
            <div class="zp-progress">
              <div class="track">
                <div class="fill" :class="{ 'is-done': recordingTask.done >= recordingTask.target_count }"
                  :style="{ width: pct(recordingTask.done, recordingTask.target_count) + '%' }"></div>
              </div>
              <span class="num"><b>{{ recordingTask.done }}</b> / {{ recordingTask.target_count }} 条</span>
            </div>
            <p class="zp-text-3 zp-mt-8">
              还差 <b style="color:var(--navy-700)">{{ remaining(recordingTask) }}</b> 条完成本次任务（录音质检通过后计入），去录一条吧
            </p>
            <div class="zp-flex zp-mt-16">
              <router-link class="zp-btn zp-btn--primary" to="/record">去录音</router-link>
              <span v-if="recordingTask.note" class="zp-tag zp-tag--gray">备注：{{ recordingTask.note }}</span>
            </div>
          </template>
          <div v-else class="zp-empty">
            <p>暂无录音任务</p>
            <router-link class="zp-btn zp-btn--primary" to="/record">去录音</router-link>
          </div>
        </div>
      </div>

      <!-- 标注任务 -->
      <div class="zp-card">
        <div class="zp-card-head"><h2>标注任务</h2><span class="zp-card-sub">管理员下达</span></div>
        <div class="zp-card-body">
          <template v-if="annotationTask">
            <div class="zp-progress">
              <div class="track">
                <div class="fill" :class="{ 'is-done': annotationTask.done >= annotationTask.target_count }"
                  :style="{ width: pct(annotationTask.done, annotationTask.target_count) + '%' }"></div>
              </div>
              <span class="num"><b>{{ annotationTask.done }}</b> / {{ annotationTask.target_count }} 条</span>
            </div>
            <p class="zp-text-3 zp-mt-8">
              完成 {{ annotationTask.target_count }} 条音频标注即达标
            </p>
            <div class="zp-flex zp-mt-16">
              <router-link class="zp-btn zp-btn--primary" to="/annotation">去标注</router-link>
              <span v-if="annotationTask.note" class="zp-tag zp-tag--gray">备注：{{ annotationTask.note }}</span>
            </div>
          </template>
          <div v-else class="zp-empty">
            <p>暂无标注任务</p>
            <router-link class="zp-btn zp-btn--primary" to="/annotation">去标注</router-link>
          </div>
        </div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="zp-quick zp-mb-16">
      <router-link to="/record">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z" /><path d="M19 10v1a7 7 0 0 1-14 0v-1" /><path d="M12 18v4" /></svg></span>
        <b>录音采集</b>
      </router-link>
      <router-link to="/my-recordings">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 12a9 9 0 0 1 9-9h3v18h-3a9 9 0 0 1-9-9z" /><circle cx="16" cy="8" r="1" /><circle cx="19" cy="12" r="1" /><circle cx="16" cy="16" r="1" /></svg></span>
        <b>我的录音</b>
      </router-link>
      <router-link to="/annotation">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg></span>
        <b>录音标注</b>
      </router-link>
      <router-link to="/my-annotations">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 4h16v13H8l-4 4z" /><path d="M8 9h8" /><path d="M8 12h5" /></svg></span>
        <b>我的标注</b>
      </router-link>
      <router-link to="/messages">
        <span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg></span>
        <b>我的消息</b>
        <span v-if="messageStore.unread > 0" class="zp-dot-badge">{{ messageStore.unread > 99 ? "99+" : messageStore.unread }}</span>
      </router-link>
    </div>

    <!-- 最近录音 + 最新消息 -->
    <div class="zp-grid-2">
      <div class="zp-card">
        <div class="zp-card-head"><h2>最近录音</h2><router-link class="zp-btn zp-btn--text" to="/my-recordings">全部</router-link></div>
        <div class="zp-card-body">
          <ul v-if="recentRecordings.length" class="zp-line-list">
            <li v-for="r in recentRecordings" :key="r.id">
              <span class="zp-tag" :class="categoryTag(r.category)">{{ categoryLabel(r.category) }}</span>
              <span class="txt">{{ r.text_content }}</span>
              <span class="time">{{ fmtShort(r.created_at) }}</span>
            </li>
          </ul>
          <div v-else class="zp-empty"><p>暂无录音记录</p></div>
        </div>
      </div>
      <div class="zp-card">
        <div class="zp-card-head"><h2>最新消息</h2><router-link class="zp-btn zp-btn--text" to="/messages">全部</router-link></div>
        <div class="zp-card-body zp-card-body--flush">
          <div v-if="latestMessages.length">
            <div v-for="m in latestMessages" :key="m.id" class="zp-msg-item" :class="{ 'is-unread': !m.read }">
              <span class="zp-tag" :class="messageTag(m.title).cls">{{ messageTag(m.title).label }}</span>
              <div style="min-width:0;flex:1">
                <h4>{{ m.title }}</h4>
                <p>{{ m.content }}</p>
              </div>
              <span class="time">{{ fmtShort(m.created_at) }}</span>
            </div>
          </div>
          <div v-else class="zp-empty"><p>暂无消息</p></div>
        </div>
      </div>
    </div>

    <!-- 管理员入口卡 -->
    <div v-if="userStore.isAdmin" class="zp-card zp-mt-16">
      <div class="zp-card-head"><h2>管理工作</h2></div>
      <div class="zp-card-body zp-flex">
        <router-link class="zp-btn zp-btn--primary" to="/admin/overview">进入数据总览</router-link>
        <router-link class="zp-btn zp-btn--ghost" to="/admin/tasks">任务管理</router-link>
      </div>
    </div>
  </div>
</template>
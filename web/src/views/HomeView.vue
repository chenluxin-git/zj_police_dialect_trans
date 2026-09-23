<script setup lang="ts">
/**
 * 首页（按角色分流）
 * - 民警（user）：问候 + 我的任务卡 + 最近录音 + 我的消息（各 5 条，行内展开）
 * - 管理员（admin/super_admin）：直接渲染数据总览（原 admin/OverviewView 整体迁入）
 *   「首页」与「数据总览」不再并存，管理员侧栏只有「首页」一项，URL 固定为 /
 *
 * 2026-09-23 调整：
 * - 管理员首页即总览，删掉「数据总览」菜单项与路由（/admin/overview 保留软重定向）
 * - 去掉「快捷入口」宫格（与侧栏重复，侧栏已是二级菜单，导航够用）
 * - 消息卡合并原「最新消息」与消息中心的未读语义：未读 + 最新按时间倒序共 5 条，
 *   点行内展开看全文（不跳消息中心）
 */
import { computed, onMounted, ref, watch } from "vue"
import { api } from "@/api/http"
import {
  getMessage,
  listMessages,
  messageTag,
  type MessageItem,
} from "@/api/messages"
import { useUserStore } from "@/stores/user"
import { useMessageStore } from "@/stores/message"
import { categoryLabel, categoryTagClass } from "@/constants/category"
import OverviewView from "@/views/admin/OverviewView.vue"

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

/** 首页消息卡展示条数（未读优先，无未读则补最新，按时间倒序） */
const MSG_LIMIT = 5

const userStore = useUserStore()
const messageStore = useMessageStore()

const isAdmin = computed(() => userStore.isAdmin)

const recordingTask = ref<TaskProgress | null>(null)
const annotationTask = ref<TaskProgress | null>(null)
const recentRecordings = ref<RecordingItem[]>([])
const messages = ref<MessageItem[]>([])

/** 当前展开的消息详情：{ id, content, senderId }，null 表示都收起 */
const expandedId = ref<number | null>(null)
const expandedContent = ref("")
const expandedSenderId = ref<number | null>(null)
const detailLoading = ref(false)

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

function pad(n: number) {
  return n < 10 ? "0" + n : String(n)
}

function fmtShort(s: string) {
  const d = new Date(s)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtDateTime(s: string) {
  const d = new Date(s)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 消息卡：先取未读，不足 5 条再用最新补齐，按时间倒序去重。
 * 这样用户不用点进消息中心就能看到「发生了什么」。
 */
async function loadMessages() {
  try {
    const unread = await listMessages({ box: "unread", page: 1, page_size: MSG_LIMIT })
    let items = unread.items
    if (items.length < MSG_LIMIT) {
      const latest = await listMessages({ box: "all", page: 1, page_size: MSG_LIMIT })
      const seen = new Set(items.map((m) => m.id))
      items = [...items, ...latest.items.filter((m) => !seen.has(m.id))]
    }
    messages.value = items
      .slice(0, MSG_LIMIT)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

/** 展开/收起某条消息；展开时取详情（后端会顺带标记已读） */
async function toggleMessage(m: MessageItem) {
  if (expandedId.value === m.id) {
    expandedId.value = null
    expandedContent.value = ""
    expandedSenderId.value = null
    return
  }
  expandedId.value = m.id
  expandedContent.value = m.content
  expandedSenderId.value = null
  detailLoading.value = true
  try {
    const detail = await getMessage(m.id)
    expandedContent.value = detail.content
    expandedSenderId.value = detail.sender_id
    if (!m.read) {
      m.read = true
      void messageStore.refresh()
    }
  } catch {
    /* 展开失败保留列表里的摘要 */
  } finally {
    detailLoading.value = false
  }
}

async function loadOfficerHome() {
  try {
    const tasks = await api.get<TasksData>("/tasks/my")
    recordingTask.value = tasks.recording
    annotationTask.value = tasks.annotation
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
  try {
    const rec = await api.get<RecordingPage>("/recordings", { params: { page: 1, page_size: 5 } })
    recentRecordings.value = rec.items
  } catch {
    /* noop */
  }
  await loadMessages()
}

// 管理员不加载民警首页数据（他的首页是总览）
onMounted(() => {
  if (!isAdmin.value) void loadOfficerHome()
})

// 角色可能在 fetchMe 之后才到位（刷新场景），到位后再决定要不要加载
watch(isAdmin, (v) => {
  if (!v && !recordingTask.value && messages.value.length === 0) void loadOfficerHome()
})
</script>

<template>
  <!-- 管理员首页 = 数据总览（原 admin/OverviewView，已从侧栏与路由中移除独立入口） -->
  <OverviewView v-if="isAdmin" />

  <!-- 民警首页 -->
  <div v-else>
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
              <router-link class="zp-btn zp-btn--primary" to="/record/work">去录音</router-link>
              <span v-if="recordingTask.note" class="zp-tag zp-tag--gray">备注：{{ recordingTask.note }}</span>
            </div>
          </template>
          <div v-else class="zp-empty">
            <p>暂无录音任务</p>
            <router-link class="zp-btn zp-btn--primary" to="/record/work">去录音</router-link>
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
              <router-link class="zp-btn zp-btn--primary" to="/annotation/work">去标注</router-link>
              <span v-if="annotationTask.note" class="zp-tag zp-tag--gray">备注：{{ annotationTask.note }}</span>
            </div>
          </template>
          <div v-else class="zp-empty">
            <p>暂无标注任务</p>
            <router-link class="zp-btn zp-btn--primary" to="/annotation/work">去标注</router-link>
          </div>
        </div>
      </div>
    </div>

    <!-- 最近录音 + 我的消息 -->
    <div class="zp-grid-2">
      <div class="zp-card">
        <div class="zp-card-head">
          <h2>最近录音</h2>
          <router-link class="zp-btn zp-btn--text" to="/record/history">全部</router-link>
        </div>
        <div class="zp-card-body">
          <ul v-if="recentRecordings.length" class="zp-line-list">
            <li v-for="r in recentRecordings" :key="r.id">
              <span class="zp-tag" :class="categoryTagClass(r.category)">{{ categoryLabel(r.category) }}</span>
              <span class="txt">{{ r.text_content }}</span>
              <span class="time">{{ fmtShort(r.created_at) }}</span>
            </li>
          </ul>
          <div v-else class="zp-empty"><p>暂无录音记录</p></div>
        </div>
      </div>

      <!-- 消息：未读 + 最新共 5 条，行内展开看全文，不需要跳消息中心 -->
      <div class="zp-card">
        <div class="zp-card-head">
          <h2>我的消息</h2>
          <span v-if="messageStore.unread > 0" class="zp-tag zp-tag--danger">
            {{ messageStore.unread > 99 ? "99+" : messageStore.unread }} 条未读
          </span>
          <router-link class="zp-btn zp-btn--text" to="/messages">消息中心</router-link>
        </div>
        <div class="zp-card-body zp-card-body--flush">
          <div v-if="messages.length">
            <div
              v-for="m in messages"
              :key="m.id"
              class="zp-msg-item is-clickable"
              :class="{ 'is-unread': !m.read }"
              @click="toggleMessage(m)"
            >
              <span class="zp-tag" :class="messageTag(m.title).cls">{{ messageTag(m.title).label }}</span>
              <div style="min-width:0;flex:1">
                <h4>{{ m.title }}</h4>
                <p>{{ m.content }}</p>

                <!-- 行内展开的全文 -->
                <div v-if="expandedId === m.id" class="zp-msg-detail" @click.stop>
                  <p class="zp-text-3" style="margin-bottom:6px">
                    {{ expandedSenderId == null ? "系统自动发送" : "管理员发送" }} · {{ fmtDateTime(m.created_at) }}
                  </p>
                  <p style="line-height:1.8;white-space:pre-wrap">
                    {{ detailLoading ? "加载中…" : expandedContent }}
                  </p>
                </div>
              </div>
              <span class="time">{{ fmtShort(m.created_at) }}</span>
            </div>
          </div>
          <div v-else class="zp-empty"><p>暂无消息</p></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.zp-msg-item.is-clickable {
  cursor: pointer;
}
/* 展开态：整行不再裁剪、底色区分，便于看清全文 */
.zp-msg-item.is-clickable:hover {
  background: var(--blue-50);
}
.zp-msg-detail {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--paper);
  border-left: 3px solid var(--gold-500);
  border-radius: var(--radius);
}
</style>

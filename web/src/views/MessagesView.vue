<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"
import { ElMessage } from "element-plus"
import {
  getMessage,
  listMessages,
  messageTag,
  readAllMessages,
  type MessageDetail,
  type MessageItem,
} from "@/api/messages"
import { useMessageStore } from "@/stores/message"

const messageStore = useMessageStore()
const PAGE_SIZE = 10

type Box = "all" | "unread" | "read"

const activeTab = ref<Box>("all")
const items = ref<MessageItem[]>([])
const total = ref(0)
const page = ref(1)
const counts = reactive({ all: 0, unread: 0, read: 0 })
const loading = ref(false)

const detail = ref<MessageDetail | null>(null)
const dialogVisible = ref(false)

const senderLabel = computed(() =>
  detail.value?.sender_id == null ? "系统自动发送" : "管理员发送",
)

function pad(n: number) {
  return n < 10 ? "0" + n : String(n)
}

function fmtDateTime(s: string) {
  const d = new Date(s)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtShort(s: string) {
  const d = new Date(s)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function loadCounts() {
  try {
    const [a, u, r] = await Promise.all([
      listMessages({ box: "all", page: 1, page_size: 1 }),
      listMessages({ box: "unread", page: 1, page_size: 1 }),
      listMessages({ box: "read", page: 1, page_size: 1 }),
    ])
    counts.all = a.total
    counts.unread = u.total
    counts.read = r.total
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

async function loadList() {
  loading.value = true
  try {
    const data = await listMessages({ box: activeTab.value, page: page.value, page_size: PAGE_SIZE })
    items.value = data.items
    total.value = data.total
  } catch {
    /* noop */
  } finally {
    loading.value = false
  }
}

async function refresh() {
  await loadCounts()
  await loadList()
}

function switchTab(tab: Box) {
  if (activeTab.value === tab) return
  activeTab.value = tab
  page.value = 1
  void loadList()
}

async function openDetail(msg: MessageItem) {
  try {
    detail.value = await getMessage(msg.id)
    dialogVisible.value = true
    if (!msg.read) {
      msg.read = true
      await refresh()
    }
    void messageStore.refresh()
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

async function readAll() {
  try {
    await readAllMessages()
    ElMessage.success("已全部标记为已读")
    await refresh()
    void messageStore.refresh()
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

onMounted(refresh)
</script>

<template>
  <div class="zp-content" style="max-width:920px;padding:0">
    <div class="zp-page-head">
      <h1>我的消息</h1>
      <span class="sub">打开消息即自动标记为已读</span>
      <div class="zp-head-actions">
        <button class="zp-btn zp-btn--ghost" type="button" @click="readAll">全部标记为已读</button>
      </div>
    </div>

    <div class="zp-card">
      <div class="zp-tabs" style="padding:0 20px">
        <button :class="{ 'is-active': activeTab === 'all' }" type="button" @click="switchTab('all')">
          全部 ({{ counts.all }})
        </button>
        <button :class="{ 'is-active': activeTab === 'unread' }" type="button" @click="switchTab('unread')">
          未读 ({{ counts.unread }})
        </button>
        <button :class="{ 'is-active': activeTab === 'read' }" type="button" @click="switchTab('read')">
          已读 ({{ counts.read }})
        </button>
      </div>

      <div v-loading="loading">
        <div v-if="items.length">
          <div v-for="m in items" :key="m.id" class="zp-msg-item" :class="{ 'is-unread': !m.read }"
            @click="openDetail(m)">
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

      <div class="zp-pagination" style="padding:14px 20px">
        <span class="total">共 {{ total }} 条</span>
        <button :disabled="page <= 1" @click="page--; loadList()">上一页</button>
        <button class="is-active">{{ page }}</button>
        <button :disabled="page * PAGE_SIZE >= total" @click="page++; loadList()">下一页</button>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="dialogVisible" width="520px" :show-close="true">
      <template #header>
        <div class="zp-flex" style="gap:8px">
          <h3 style="font-size:16px;font-weight:600">{{ detail?.title }}</h3>
          <span v-if="detail" class="zp-tag" :class="messageTag(detail.title).cls">
            {{ messageTag(detail.title).label }}
          </span>
        </div>
      </template>
      <div v-if="detail" class="zp-dialog-body" style="padding:0">
        <p class="zp-text-3" style="margin-bottom:12px">{{ senderLabel }} · {{ fmtDateTime(detail.created_at) }}</p>
        <p style="line-height:1.8">{{ detail.content }}</p>
      </div>
      <template #footer>
        <button class="zp-btn zp-btn--primary" type="button" @click="dialogVisible = false">知道了</button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
/**
 * 消息发送（T33 / dome/admin-message-send.html 1:1）
 * 收件口径 el-segmented：按人员（scope 用户远程搜索）/ 按区域（地市+区县两级下拉，市码=全市）
 * / 按单位（StationPicker 地市→区县→单位级联多选，名+区县收紧重名）
 * 右侧已发记录（标题 / 时间 / 收件数 / 已读数），行点开查看消息详情；发送成功回显 sent/skipped。
 */
import { onMounted, ref, watch } from "vue"
import { ElMessage } from "element-plus"
import RegionPicker from "@/components/RegionPicker.vue"
import StationPicker from "@/components/StationPicker.vue"
import type { StationPickItem } from "@/components/StationPicker.vue"
import { listUsers } from "@/api/admin/users"
import { listSentMessages, sendMessage } from "@/api/admin/messages"
import type { SentMessage } from "@/api/admin/messages"

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  return iso.slice(5, 16).replace("T", " ")
}

function msgTag(title: string): { label: string; cls: string } {
  if (title.startsWith("新任务")) return { label: "任务", cls: "zp-tag--navy" }
  if (title.includes("公告")) return { label: "公告", cls: "zp-tag--gold" }
  return { label: "通知", cls: "zp-tag--blue" }
}

// ---------- 发送表单 ----------
const targetTypeOptions = [
  { label: "按人员", value: "user" },
  { label: "按区域", value: "region" },
  { label: "按单位", value: "station" },
]

const targetType = ref("user")
const userId = ref<number | null>(null)
const title = ref("")
const content = ref("")

// 按单位（StationPicker 统一维护）：codes=多选值（跨区县不碰撞），items=完整项（提交带区县）
const stationCodes = ref<string[]>([])
const stationItems = ref<StationPickItem[]>([])

function onStationsChange(items: StationPickItem[]) {
  stationItems.value = items
}

// 区域收件：由 RegionPicker 统一维护（只选市 = 全市群发，选到区县 = 区县群发）
const regionCode = ref("")

const userOptions = ref<{ value: number; label: string }[]>([])
const userSearchLoading = ref(false)

async function searchUsers(q: string) {
  userSearchLoading.value = true
  try {
    const data = await listUsers({ real_name: q || undefined, page: 1, page_size: 20 })
    userOptions.value = data.items.map((u) => ({
      value: u.id,
      label: `${u.real_name} · ${u.phone} · ${u.police_station || "—"}`,
    }))
  } finally {
    userSearchLoading.value = false
  }
}

async function submit() {
  if (!title.value) {
    ElMessage.warning("请输入标题")
    return
  }
  if (!content.value) {
    ElMessage.warning("请输入内容")
    return
  }
  let targetValue: number | string | string[]
  let stations: { name: string; region_code: string }[] | undefined
  if (targetType.value === "user") {
    if (userId.value == null) {
      ElMessage.warning("请选择收件人")
      return
    }
    targetValue = userId.value
  } else if (targetType.value === "region") {
    if (!regionCode.value) {
      ElMessage.warning("请选择区域")
      return
    }
    targetValue = regionCode.value
  } else {
    if (!stationItems.value.length) {
      ElMessage.warning("请选择单位（需先选到地市/区县）")
      return
    }
    // 名数组仅审计可读，实际收件以后端 stations（名+区县收紧重名）为准
    targetValue = stationItems.value.map((i) => i.name)
    stations = stationItems.value.map((i) => ({ name: i.name, region_code: i.region_code }))
  }
  const result = await sendMessage({
    target_type: targetType.value as "user" | "region" | "station",
    target_value: targetValue,
    stations,
    title: title.value,
    content: content.value,
  })
  ElMessage.success(`发送 ${result.sent} 人 / 越界跳过 ${result.skipped}`)
  title.value = ""
  content.value = ""
  // 只清单位选择，保留区域（便于同区域连续群发）
  stationCodes.value = []
  stationItems.value = []
  void loadSent()
}

// ---------- 预计收件预览（按单位）：debounce + 序号丢弃过期响应 ----------
const previewCount = ref<number | null>(null)
const previewLoading = ref(false)
let previewSeq = 0
let previewTimer: number | undefined

watch(stationItems, (items) => {
  window.clearTimeout(previewTimer)
  if (!items.length) {
    previewCount.value = null
    previewLoading.value = false
    return
  }
  previewTimer = window.setTimeout(() => void runPreview(items), 400)
})

async function runPreview(items: StationPickItem[]) {
  const seq = ++previewSeq
  previewLoading.value = true
  try {
    // listUsers 口径与后端 stations 分支一致（region 展开 ∩ scope + 名精确）→ 预览=实际送达
    const totals = await Promise.all(items.map((i) =>
      listUsers({ region_code: i.region_code, station: i.name, page: 1, page_size: 1 }).then((d) => d.total)))
    if (seq !== previewSeq) return
    previewCount.value = totals.reduce((a, b) => a + b, 0)
  } finally {
    if (seq === previewSeq) previewLoading.value = false
  }
}

// ---------- 已发记录 ----------
const sentItems = ref<SentMessage[]>([])
const sentTotal = ref(0)
const sentPage = ref(1)
const sentPageSize = 10

async function loadSent() {
  const data = await listSentMessages({ page: sentPage.value, page_size: sentPageSize })
  sentItems.value = data.items
  sentTotal.value = data.total
}

const detailVisible = ref(false)
const detailMsg = ref<SentMessage | null>(null)

function openDetail(m: SentMessage) {
  detailMsg.value = m
  detailVisible.value = true
}

onMounted(() => {
  void searchUsers("")
  void loadSent()
})
</script>

<template>
  <div>
    <div class="zp-page-head">
      <h1>消息发送</h1>
      <span class="sub">向辖区用户发送站内消息，支持单人、按区域、按单位群发</span>
    </div>

    <div class="zp-grid-2">
      <!-- 发送表单 -->
      <div class="zp-card">
        <div class="zp-card-head"><h2>编写消息</h2></div>
        <div class="zp-card-body">
          <div class="zp-field">
            <label>发送方式<span class="req">*</span></label>
            <el-segmented v-model="targetType" :options="targetTypeOptions" />
          </div>
          <div class="zp-field">
            <label>选择收件人<span class="req">*</span></label>
            <el-select
              v-if="targetType === 'user'"
              v-model="userId"
              filterable
              remote
              :remote-method="searchUsers"
              :loading="userSearchLoading"
              placeholder="请搜索姓名 / 手机号"
              style="width: 100%"
            >
              <el-option v-for="o in userOptions" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <div v-else-if="targetType === 'region'">
              <RegionPicker
                v-model:value="regionCode"
                mode="filter"
                city-only
                city-placeholder="选择地市（全市群发）"
                district-placeholder="区县（可不选）"
              />
            </div>
            <StationPicker
              v-else
              v-model:value="stationCodes"
              standalone
              multiple
              @change="onStationsChange"
            />
            <p class="zp-hint">
              <template v-if="targetType === 'user'">按人员：向指定民警发送。</template>
              <template v-else-if="targetType === 'region'">按区域：将群发给所选区域（含下级）全部用户。</template>
              <template v-else>
                按单位：可跨区县多选，向所选各单位全体用户群发。
                <template v-if="previewLoading">（正在统计收件人数…）</template>
                <b v-else-if="previewCount === 0" style="color: var(--warn)">所选单位暂无用户。</b>
                <b v-else-if="previewCount !== null">预计收件 {{ previewCount }} 人（以实际发送结果为准）。</b>
              </template>
            </p>
          </div>
          <div class="zp-field">
            <label>标题<span class="req">*</span></label>
            <el-input v-model="title" placeholder="请输入消息标题" />
          </div>
          <div class="zp-field">
            <label>内容<span class="req">*</span></label>
            <el-input v-model="content" type="textarea" :rows="4" placeholder="请输入消息内容" />
          </div>
          <button class="zp-btn zp-btn--primary zp-btn--lg zp-btn--block" type="button" @click="submit">发送消息</button>
        </div>
      </div>

      <!-- 已发送记录 -->
      <div class="zp-card">
        <div class="zp-card-head"><h2>已发送记录</h2><span class="zp-card-sub">近 30 天</span></div>
        <div class="zp-card-body zp-card-body--flush">
          <div v-for="m in sentItems" :key="m.id" class="zp-msg-item" @click="openDetail(m)">
            <span class="zp-tag" :class="msgTag(m.title).cls">{{ msgTag(m.title).label }}</span>
            <div style="min-width: 0; flex: 1">
              <h4>{{ m.title }}</h4>
              <p>发送给 {{ m.recipient_count }} 人 · 已读 {{ m.read_count }}</p>
            </div>
            <span class="time">{{ formatDate(m.created_at) }}</span>
          </div>
          <div v-if="!sentItems.length" class="zp-empty"><p>暂无已发送记录</p></div>
        </div>
        <div class="zp-pagination" style="padding: 14px 20px">
          <span class="total">共 {{ sentTotal }} 条</span>
        </div>
      </div>
    </div>

    <!-- 消息详情 -->
    <el-dialog v-model="detailVisible" title="消息详情" width="520px">
      <template v-if="detailMsg">
        <div class="zp-field">
          <label>标题</label>
          <div>{{ detailMsg.title }}</div>
        </div>
        <div class="zp-field">
          <label>内容</label>
          <div style="white-space: pre-wrap">{{ detailMsg.content }}</div>
        </div>
        <div class="zp-flex" style="gap: 20px">
          <span class="zp-text-3">发送时间：{{ formatDate(detailMsg.created_at) }}</span>
          <span class="zp-text-3">收件 {{ detailMsg.recipient_count }} 人</span>
          <span class="zp-text-3">已读 {{ detailMsg.read_count }} 人</span>
        </div>
      </template>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="detailVisible = false">关闭</button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 消息发送（T33 / dome/admin-message-send.html 1:1）
 * 收件口径 el-segmented：按人员（scope 用户远程搜索）/ 按区域（地市+区县两级下拉，市码=全市）/ 按单位（派出所下拉）
 * 右侧已发记录（标题 / 时间 / 收件数 / 已读数），行点开查看消息详情；发送成功回显 sent/skipped。
 */
import { computed, onMounted, ref } from "vue"
import { ElMessage } from "element-plus"
import { api } from "@/api/http"
import { listUsers } from "@/api/admin/users"
import { listSentMessages, sendMessage } from "@/api/admin/messages"
import type { SentMessage } from "@/api/admin/messages"

interface RegionNode {
  code: string
  name: string
  level: string
  children: RegionNode[]
}

interface Station {
  code: string
  name: string
  region_code: string
  sort_order: number
}

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
const stationName = ref("")
const title = ref("")
const content = ref("")

const regionTree = ref<RegionNode[]>([])
const stations = ref<Station[]>([])

// 区域收件：地市 + 区县两级下拉，地市选定后区县才可选（只选市 = 全市群发，选到区县 = 区县群发）
const cityCode = ref("")
const districtCode = ref("")
const cityOptions = computed<RegionNode[]>(() =>
  regionTree.value.flatMap((r) => (r.level === "province" ? r.children : [r])))
const districtOptions = computed<RegionNode[]>(() =>
  cityCode.value
    ? cityOptions.value.find((c) => c.code === cityCode.value)?.children ?? []
    : [])
const regionCode = computed(() => districtCode.value || cityCode.value)

function onCityChange() {
  districtCode.value = ""
}

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
  let targetValue: number | string
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
    if (!stationName.value) {
      ElMessage.warning("请选择单位")
      return
    }
    targetValue = stationName.value
  }
  const result = await sendMessage({
    target_type: targetType.value as "user" | "region" | "station",
    target_value: targetValue,
    title: title.value,
    content: content.value,
  })
  ElMessage.success(`发送 ${result.sent} 人 / 越界跳过 ${result.skipped}`)
  title.value = ""
  content.value = ""
  void loadSent()
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

async function loadBase() {
  const [tree, sts] = await Promise.all([
    api.get<RegionNode[]>("/regions/tree"),
    api.get<Station[]>("/police_stations"),
  ])
  regionTree.value = tree
  stations.value = sts
}

onMounted(() => {
  void loadBase()
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
            <div v-else-if="targetType === 'region'" class="zp-flex" style="gap: 8px">
              <el-select
                v-model="cityCode"
                placeholder="选择地市（全市群发）"
                clearable
                style="flex: 1"
                @change="onCityChange"
              >
                <el-option v-for="c in cityOptions" :key="c.code" :label="c.name" :value="c.code" />
              </el-select>
              <el-select
                v-model="districtCode"
                placeholder="区县（可不选）"
                clearable
                :disabled="!cityCode"
                style="flex: 1"
              >
                <el-option v-for="d in districtOptions" :key="d.code" :label="d.name" :value="d.code" />
              </el-select>
            </div>
            <el-select
              v-else
              v-model="stationName"
              filterable
              placeholder="选择派出所"
              style="width: 100%"
            >
              <el-option v-for="s in stations" :key="s.code" :label="s.name" :value="s.name" />
            </el-select>
            <p class="zp-hint">
              <template v-if="targetType === 'user'">按人员：向指定民警发送。</template>
              <template v-else-if="targetType === 'region'">按区域：将群发给所选区域（含下级）全部用户。</template>
              <template v-else>按单位：向该派出所全体用户群发。</template>
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

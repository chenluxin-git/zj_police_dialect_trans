<script setup lang="ts">
/**
 * 主布局（dome/home.html 1:1 为基底）：藏青侧栏 + 顶栏
 *
 * 侧栏为**二级菜单**（P1 改造）：
 * - 一级 = 分组标题（日常工作 / 消息 / 管理工作），不可点
 * - 二级 = 直接项（无 children）或可展开组（有 children）
 * - 三级 = 可展开组下的二级项
 * 菜单按角色渲染：user=日常工作 + 消息；admin/super_admin 追加管理工作。
 * 当前路由所在的组自动展开并高亮，用户永远看得到自己在哪一组。
 * 未读角标：侧栏「我的消息」+ 顶栏铃铛，30s 轮询 + 路由切换刷新。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ArrowRight } from "@element-plus/icons-vue"
import { useUserStore } from "@/stores/user"
import { useMessageStore } from "@/stores/message"

interface MenuLeaf {
  label: string
  to: string
  /** 是否显示未读角标 */
  badge?: boolean
}
interface MenuEntry {
  label: string
  /** 无 children 时是直接项，必须有 to */
  to?: string
  /** 有 children 时是可展开组 */
  children?: MenuLeaf[]
  badge?: boolean
}
interface MenuSection {
  group: string
  adminOnly?: boolean
  entries: MenuEntry[]
}

// 侧栏菜单树。分组标题不可点；无 children 的 entry 渲染为直接链接。
const MENU: MenuSection[] = [
  {
    group: "日常工作",
    entries: [
      { label: "首页", to: "/" },
      {
        label: "录音采集",
        children: [
          { label: "开始录音", to: "/record/work" },
          { label: "历史录音", to: "/record/history" },
        ],
      },
      {
        label: "录音标注",
        children: [
          { label: "开始标注", to: "/annotation/work" },
          { label: "历史标注", to: "/annotation/history" },
        ],
      },
      {
        label: "语音转译",
        children: [
          { label: "工作台", to: "/trans/work" },
          { label: "历史记录", to: "/trans/history" },
        ],
      },
    ],
  },
  {
    group: "消息",
    entries: [{ label: "我的消息", to: "/messages", badge: true }],
  },
  {
    group: "管理工作",
    adminOnly: true,
    entries: [
      {
        label: "语料管理",
        children: [
          { label: "语料浏览", to: "/admin/texts/browse" },
          { label: "批量导入", to: "/admin/texts/import" },
          { label: "导入台账", to: "/admin/texts/ledger" },
        ],
      },
      {
        label: "音频素材",
        children: [
          { label: "上传入库", to: "/admin/audio/upload" },
          { label: "扫盘导入", to: "/admin/audio/scan" },
        ],
      },
      {
        label: "采集记录",
        children: [
          { label: "录音记录", to: "/admin/records/recording" },
          { label: "标注记录", to: "/admin/records/annotation" },
          { label: "转译记录", to: "/admin/records/transcription" },
        ],
      },
      {
        label: "人员与任务",
        children: [
          { label: "人员管理", to: "/admin/users/people" },
          { label: "任务管理", to: "/admin/users/tasks" },
        ],
      },
      { label: "消息发送", to: "/admin/message-send" },
      { label: "数据集导出", to: "/admin/export" },
    ],
  },
]

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const messageStore = useMessageStore()

const visibleMenu = computed(() =>
  MENU.filter((g) => !g.adminOnly || userStore.isAdmin),
)

const crumb = computed(() => {
  const m = route.meta
  const title = (m.title as string) || ""
  return {
    group: (m.group as string) || "",
    parent: (m.parent as string) || "",
    // 首页对管理员而言就是数据总览，面包屑跟随实际内容
    title: route.name === "home" && userStore.isAdmin ? "数据总览" : title,
  }
})
const avatarChar = computed(() => userStore.user?.real_name?.charAt(0) || "警")

/**
 * 展开状态。用 ref<Set> 而非 reactive Set，配合整体替换保证触发更新
 * （与 OverviewView 三级展开同一写法）。
 */
const expanded = ref<Set<string>>(new Set())

/** 所有可展开组的一级项 */
const allGroups = computed(() =>
  visibleMenu.value.flatMap((s) => s.entries.filter((e) => e.children?.length)),
)

/**
 * 当前路由落在哪个可展开组下（按其子项 to 精确匹配）。
 * 用 meta.parent 兜底，避免 path 大小写/尾斜杠差异导致匹配不到。
 */
const activeGroup = computed<string | null>(() => {
  const parent = crumb.value.parent
  if (parent) return parent
  for (const g of allGroups.value) {
    if (g.children?.some((c) => c.to === route.path)) return g.label
  }
  return null
})

function isGroupOpen(entry: MenuEntry): boolean {
  return expanded.value.has(entry.label)
}

function toggleGroup(entry: MenuEntry) {
  const next = new Set(expanded.value)
  if (next.has(entry.label)) next.delete(entry.label)
  else next.add(entry.label)
  expanded.value = next
}

/** 当前路由所在组自动展开（只增不减，避免收起用户手动展开的组） */
watch(
  activeGroup,
  (label) => {
    if (!label || expanded.value.has(label)) return
    expanded.value = new Set([...expanded.value, label])
  },
  { immediate: true },
)

onMounted(() => messageStore.startPolling())
onUnmounted(() => messageStore.stopPolling())

function goMessages() {
  if (route.path !== "/messages") router.push("/messages")
}

/** 退出：记录审计登出后清会话回登录页（保留历史写法：登出即跳转） */
async function onLogout() {
  await userStore.logout()
  window.location.href = import.meta.env.BASE_URL + "login"
}
</script>

<template>
  <div class="zp-app">
    <aside class="zp-side">
      <div class="zp-brand">
        <svg viewBox="0 0 48 56" fill="none" aria-hidden="true">
          <path
            d="M24 2 44 8v18c0 14-9 23-20 28C13 49 4 40 4 26V8L24 2z"
            stroke="currentColor"
            stroke-width="2.5"
            stroke-linejoin="round" />
          <path
            d="M24 17l2.5 5.1 5.6.8-4 4 .9 5.6L24 29.9l-5 2.6.9-5.6-4-4 5.6-.8L24 17z"
            fill="currentColor" />
        </svg>
        <div class="zp-brand-name"><b>浙江公安</b><span>方言语料采集平台</span></div>
      </div>

      <nav class="zp-menu">
        <div v-for="s in visibleMenu" :key="s.group" class="zp-menu-group">
          <div class="zp-menu-title">{{ s.group }}</div>

          <template v-for="entry in s.entries" :key="entry.to || entry.label">
            <!-- 可展开组：组头 + 缩进二级项 -->
            <template v-if="entry.children?.length">
              <button
                class="zp-menu-group-btn"
                :class="{ 'is-open': isGroupOpen(entry) }"
                type="button"
                :aria-expanded="isGroupOpen(entry)"
                @click="toggleGroup(entry)"
              >
                {{ entry.label }}
                <ArrowRight class="zp-menu-caret" />
              </button>
              <div v-show="isGroupOpen(entry)" class="zp-menu-sub">
                <router-link v-for="leaf in entry.children" :key="leaf.to" :to="leaf.to">
                  {{ leaf.label }}
                  <span v-if="leaf.badge && messageStore.unread > 0" class="zp-dot-badge">
                    {{ messageStore.unread > 99 ? "99+" : messageStore.unread }}
                  </span>
                </router-link>
              </div>
            </template>

            <!-- 直接项 -->
            <router-link v-else-if="entry.to" :to="entry.to">
              {{ entry.label }}
              <span v-if="entry.badge && messageStore.unread > 0" class="zp-dot-badge">
                {{ messageStore.unread > 99 ? "99+" : messageStore.unread }}
              </span>
            </router-link>
          </template>
        </div>
      </nav>
    </aside>

    <div class="zp-main">
      <header class="zp-topbar">
        <nav class="zp-crumb">
          <span v-if="crumb.group">{{ crumb.group }}</span>
          <span v-if="crumb.group" class="sep">/</span>
          <span v-if="crumb.parent">{{ crumb.parent }}</span>
          <span v-if="crumb.parent" class="sep">/</span>
          <b>{{ crumb.title }}</b>
        </nav>
        <div class="zp-topbar-right">
          <button class="zp-bell" type="button" aria-label="未读消息" @click="goMessages">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.7 21a2 2 0 01-3.4 0" />
            </svg>
            <span v-if="messageStore.unread > 0" class="zp-dot-badge">
              {{ messageStore.unread > 99 ? "99+" : messageStore.unread }}
            </span>
          </button>
          <span class="zp-vline"></span>
          <div class="zp-topbar-user">
            <span class="zp-avatar" :class="{ 'zp-avatar--gold': userStore.isAdmin }"
              style="width:30px;height:30px;font-size:12px">{{ avatarChar }}</span>
            {{ userStore.user?.real_name || "" }}
            <button class="zp-exit" type="button" @click="onLogout">退出</button>
          </div>
        </div>
      </header>

      <main class="zp-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

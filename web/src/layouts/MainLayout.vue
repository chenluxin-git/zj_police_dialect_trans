<script setup lang="ts">
/**
 * 主布局（dome/home.html 1:1）：藏青侧栏 + 顶栏
 * 菜单按角色渲染：user=日常工作5+消息1；admin/super_admin 追加管理工作12
 * 未读角标：侧栏「我的消息」+ 顶栏铃铛，30s 轮询 + 路由切换刷新
 */
import { computed, onMounted, onUnmounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useUserStore } from "@/stores/user"
import { useMessageStore } from "@/stores/message"

interface MenuItem {
  label: string
  to: string
  badge?: boolean
}
interface MenuGroup {
  group: string
  adminOnly?: boolean
  items: MenuItem[]
}

// 三级菜单（dome 原文顺序），管理工作组仅 admin/super_admin 渲染
const MENU: MenuGroup[] = [
  {
    group: "日常工作",
    items: [
      { label: "首页", to: "/" },
      { label: "录音采集", to: "/record" },
      { label: "我的录音", to: "/my-recordings" },
      { label: "录音标注", to: "/annotation" },
      { label: "我的标注", to: "/my-annotations" },
    ],
  },
  {
    group: "消息",
    items: [{ label: "我的消息", to: "/messages", badge: true }],
  },
  {
    group: "管理工作",
    adminOnly: true,
    items: [
      { label: "数据总览", to: "/admin/overview" },
      { label: "任务管理", to: "/admin/tasks" },
      { label: "消息发送", to: "/admin/message-send" },
      { label: "用户管理", to: "/admin/users" },
      { label: "文本导入", to: "/admin/text-import" },
      { label: "导入台账", to: "/admin/text-import-manage" },
      { label: "文本管理", to: "/admin/texts" },
      { label: "录音管理", to: "/admin/recordings" },
      { label: "标注管理", to: "/admin/annotations" },
      { label: "音频上传", to: "/admin/audio-upload" },
      { label: "音频导入", to: "/admin/audio-import" },
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
const crumb = computed(() => ({
  group: (route.meta.group as string) || "",
  title: (route.meta.title as string) || "",
}))
const avatarChar = computed(() => userStore.user?.real_name?.charAt(0) || "警")

onMounted(() => messageStore.startPolling())
onUnmounted(() => messageStore.stopPolling())

function goMessages() {
  if (route.path !== "/messages") router.push("/messages")
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
        <div v-for="g in visibleMenu" :key="g.group" class="zp-menu-group">
          <div class="zp-menu-title">{{ g.group }}</div>
          <router-link v-for="item in g.items" :key="item.to" :to="item.to">
            {{ item.label }}
            <span v-if="item.badge && messageStore.unread > 0" class="zp-dot-badge">
              {{ messageStore.unread > 99 ? "99+" : messageStore.unread }}
            </span>
          </router-link>
        </div>
      </nav>
    </aside>

    <div class="zp-main">
      <header class="zp-topbar">
        <nav class="zp-crumb">
          <span v-if="crumb.group">{{ crumb.group }}</span>
          <span v-if="crumb.group && crumb.title" class="sep">/</span>
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
            <button class="zp-exit" type="button" @click="userStore.logout()">退出</button>
          </div>
        </div>
      </header>

      <main class="zp-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

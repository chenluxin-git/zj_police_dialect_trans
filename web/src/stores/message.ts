/**
 * 未读消息 store：unread 计数 + refresh()
 * 刷新时机：路由切换（router afterEach）+ 30s 轮询（MainLayout 挂载时启动，Spec §6.5）
 */
import { defineStore } from "pinia"
import { getUnreadCount } from "@/api/messages"
import { useUserStore } from "./user"

export const useMessageStore = defineStore("message", {
  state: () => ({
    unread: 0,
    timer: null as ReturnType<typeof setInterval> | null,
  }),
  actions: {
    async refresh() {
      const userStore = useUserStore()
      if (!userStore.token) {
        this.unread = 0
        return
      }
      try {
        // 轮询静默失败，不打扰用户（401 已由拦截器统一处理）
        const data = await getUnreadCount()
        this.unread = data.count
      } catch {
        /* noop */
      }
    },
    startPolling() {
      if (this.timer !== null) return
      void this.refresh()
      this.timer = setInterval(() => void this.refresh(), 30_000)
    },
    stopPolling() {
      if (this.timer !== null) {
        clearInterval(this.timer)
        this.timer = null
      }
    },
  },
})

/**
 * 路由与守卫（Spec §8：19 张页面表，登录/注册合并一行计 19 条）
 * 守卫：无 token → /login；非 admin/super_admin 访问 /admin/* → redirect /
 * 刷新后 store 无 user 时先 fetchMe（失败视为过期回登录）
 */
import { createRouter, createWebHistory } from "vue-router"
import { useUserStore } from "@/stores/user"
import { useMessageStore } from "@/stores/message"

declare module "vue-router" {
  interface RouteMeta {
    /** 公开页（登录/注册） */
    public?: boolean
    /** 仅 admin/super_admin */
    requiresAdmin?: boolean
    /** 面包屑：分组名 */
    group?: string
    /** 面包屑：页名 */
    title?: string
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: () => import("@/views/LoginView.vue"), meta: { public: true, title: "登录" } },
    { path: "/register", name: "register", component: () => import("@/views/RegisterView.vue"), meta: { public: true, title: "注册" } },
    {
      path: "/",
      component: () => import("@/layouts/MainLayout.vue"),
      children: [
        { path: "", name: "home", component: () => import("@/views/HomeView.vue"), meta: { group: "日常工作", title: "首页" } },
        { path: "record", name: "record", component: () => import("@/views/RecordView.vue"), meta: { group: "日常工作", title: "录音采集" } },
        { path: "my-recordings", name: "my-recordings", component: () => import("@/views/MyRecordingsView.vue"), meta: { group: "日常工作", title: "我的录音" } },
        { path: "annotation", name: "annotation", component: () => import("@/views/AnnotationView.vue"), meta: { group: "日常工作", title: "录音标注" } },
        { path: "my-annotations", name: "my-annotations", component: () => import("@/views/MyAnnotationsView.vue"), meta: { group: "日常工作", title: "我的标注" } },
        { path: "messages", name: "messages", component: () => import("@/views/MessagesView.vue"), meta: { group: "消息", title: "我的消息" } },
        { path: "admin/overview", name: "admin-overview", component: () => import("@/views/admin/OverviewView.vue"), meta: { group: "管理工作", title: "数据总览", requiresAdmin: true } },
        { path: "admin/tasks", name: "admin-tasks", component: () => import("@/views/admin/TasksView.vue"), meta: { group: "管理工作", title: "任务管理", requiresAdmin: true } },
        { path: "admin/message-send", name: "admin-message-send", component: () => import("@/views/admin/MessageSendView.vue"), meta: { group: "管理工作", title: "消息发送", requiresAdmin: true } },
        { path: "admin/users", name: "admin-users", component: () => import("@/views/admin/UsersView.vue"), meta: { group: "管理工作", title: "用户管理", requiresAdmin: true } },
        { path: "admin/text-import", name: "admin-text-import", component: () => import("@/views/admin/TextImportView.vue"), meta: { group: "管理工作", title: "文本导入", requiresAdmin: true } },
        { path: "admin/text-import-manage", name: "admin-text-import-manage", component: () => import("@/views/admin/TextImportManageView.vue"), meta: { group: "管理工作", title: "导入台账", requiresAdmin: true } },
        { path: "admin/texts", name: "admin-texts", component: () => import("@/views/admin/TextsView.vue"), meta: { group: "管理工作", title: "文本管理", requiresAdmin: true } },
        { path: "admin/recordings", name: "admin-recordings", component: () => import("@/views/admin/RecordingsView.vue"), meta: { group: "管理工作", title: "录音管理", requiresAdmin: true } },
        { path: "admin/annotations", name: "admin-annotations", component: () => import("@/views/admin/AnnotationsView.vue"), meta: { group: "管理工作", title: "标注管理", requiresAdmin: true } },
        { path: "admin/audio-upload", name: "admin-audio-upload", component: () => import("@/views/admin/AudioUploadView.vue"), meta: { group: "管理工作", title: "音频上传", requiresAdmin: true } },
        { path: "admin/audio-import", name: "admin-audio-import", component: () => import("@/views/admin/AudioImportView.vue"), meta: { group: "管理工作", title: "音频导入", requiresAdmin: true } },
        { path: "admin/export", name: "admin-export", component: () => import("@/views/admin/ExportView.vue"), meta: { group: "管理工作", title: "数据集导出", requiresAdmin: true } },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
})

router.beforeEach(async (to) => {
  const userStore = useUserStore()
  if (to.meta.public) {
    return true
  }
  if (!userStore.token) {
    return { path: "/login", query: { redirect: to.fullPath } }
  }
  if (!userStore.user) {
    try {
      await userStore.fetchMe() // 刷新后恢复会话
    } catch {
      return { path: "/login", query: { redirect: to.fullPath } }
    }
  }
  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    return "/"
  }
  return true
})

// 路由切换刷新未读数（配合 30s 轮询，Spec §6.5）
router.afterEach(() => {
  void useMessageStore().refresh()
})

export default router

/**
 * 路由与守卫（Spec §8 页面表；P2 起改为二级菜单对应的嵌套/子路径结构）
 *
 * 守卫：无 token → /login；非 admin/super_admin 访问 /admin/* → redirect /
 * 刷新后 store 无 user 时先 fetchMe（失败视为过期回登录）
 *
 * 约定：
 * - 父路径（/record、/annotation、/admin/texts 等）只做 redirect 落到默认子页，
 *   既让旧链接可用，也避免出现「父路径自身也是一个页面」的重复入口。
 * - meta.group / meta.parent / meta.title 供侧栏与三段面包屑使用。
 * - 旧地址兼容重定向集中在文件末尾。
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
    /** 面包屑第一段：分组名 */
    group?: string
    /** 面包屑第二段：二级菜单组名（无则为两段面包屑） */
    parent?: string
    /** 面包屑末段 / 页名 */
    title?: string
  }
}

const router = createRouter({
  // 子路径部署（如宝塔 /record/）：base 用构建期 BASE_URL，dev 下为 "/"，行为不变
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/login", name: "login", component: () => import("@/views/LoginView.vue"), meta: { public: true, title: "登录" } },
    { path: "/register", name: "register", component: () => import("@/views/RegisterView.vue"), meta: { public: true, title: "注册" } },
    // 浙警智治统一认证落地页：由后端认证回调 302 携带 token，建立会话后进首页
    { path: "/auth", name: "auth-callback", component: () => import("@/views/AuthCallbackView.vue"), meta: { public: true, title: "统一认证登录" } },
    {
      path: "/",
      component: () => import("@/layouts/MainLayout.vue"),
      children: [
        { path: "", name: "home", component: () => import("@/views/HomeView.vue"), meta: { group: "日常工作", title: "首页" } },

        // ---------- 录音采集（二级：开始录音 / 历史录音） ----------
        { path: "record", name: "record", redirect: { name: "record-work" }, meta: { group: "日常工作", parent: "录音采集" } },
        { path: "record/work", name: "record-work", component: () => import("@/views/RecordView.vue"), meta: { group: "日常工作", parent: "录音采集", title: "开始录音" } },
        { path: "record/history", name: "record-history", component: () => import("@/views/MyRecordingsView.vue"), meta: { group: "日常工作", parent: "录音采集", title: "历史录音" } },

        // ---------- 录音标注（二级：开始标注 / 历史标注） ----------
        { path: "annotation", name: "annotation", redirect: { name: "annotation-work" }, meta: { group: "日常工作", parent: "录音标注" } },
        { path: "annotation/work", name: "annotation-work", component: () => import("@/views/AnnotationView.vue"), meta: { group: "日常工作", parent: "录音标注", title: "开始标注" } },
        { path: "annotation/history", name: "annotation-history", component: () => import("@/views/MyAnnotationsView.vue"), meta: { group: "日常工作", parent: "录音标注", title: "历史标注" } },

        { path: "messages", name: "messages", component: () => import("@/views/MessagesView.vue"), meta: { group: "消息", title: "我的消息" } },

        // ---------- 管理工作：直接项 ----------
        // 注：「数据总览」已并入首页（管理员首页即总览），此处只保留旧地址软重定向

        // ---------- 语料管理（二级：语料浏览 / 批量导入 / 导入台账） ----------
        { path: "admin/texts", name: "admin-texts", redirect: { name: "admin-texts-browse" }, meta: { group: "管理工作", parent: "语料管理", requiresAdmin: true } },
        { path: "admin/texts/browse", name: "admin-texts-browse", component: () => import("@/views/admin/TextsView.vue"), meta: { group: "管理工作", parent: "语料管理", title: "语料浏览", requiresAdmin: true } },
        { path: "admin/texts/import", name: "admin-texts-import", component: () => import("@/views/admin/TextImportView.vue"), meta: { group: "管理工作", parent: "语料管理", title: "批量导入", requiresAdmin: true } },
        { path: "admin/texts/ledger", name: "admin-texts-ledger", component: () => import("@/views/admin/TextImportManageView.vue"), meta: { group: "管理工作", parent: "语料管理", title: "导入台账", requiresAdmin: true } },

        // ---------- 音频素材（二级：上传入库 / 扫盘导入） ----------
        { path: "admin/audio", name: "admin-audio", redirect: { name: "admin-audio-upload" }, meta: { group: "管理工作", parent: "音频素材", requiresAdmin: true } },
        { path: "admin/audio/upload", name: "admin-audio-upload", component: () => import("@/views/admin/AudioUploadView.vue"), meta: { group: "管理工作", parent: "音频素材", title: "上传入库", requiresAdmin: true } },
        { path: "admin/audio/scan", name: "admin-audio-scan", component: () => import("@/views/admin/AudioImportView.vue"), meta: { group: "管理工作", parent: "音频素材", title: "扫盘导入", requiresAdmin: true } },

        // ---------- 采集记录（二级：录音记录 / 标注记录） ----------
        { path: "admin/records", name: "admin-records", redirect: { name: "admin-records-recording" }, meta: { group: "管理工作", parent: "采集记录", requiresAdmin: true } },
        { path: "admin/records/recording", name: "admin-records-recording", component: () => import("@/views/admin/RecordingsView.vue"), meta: { group: "管理工作", parent: "采集记录", title: "录音记录", requiresAdmin: true } },
        { path: "admin/records/annotation", name: "admin-records-annotation", component: () => import("@/views/admin/AnnotationsView.vue"), meta: { group: "管理工作", parent: "采集记录", title: "标注记录", requiresAdmin: true } },

        // ---------- 人员与任务（二级：人员管理 / 任务管理） ----------
        { path: "admin/users", name: "admin-users", redirect: { name: "admin-users-people" }, meta: { group: "管理工作", parent: "人员与任务", requiresAdmin: true } },
        { path: "admin/users/people", name: "admin-users-people", component: () => import("@/views/admin/UsersView.vue"), meta: { group: "管理工作", parent: "人员与任务", title: "人员管理", requiresAdmin: true } },
        { path: "admin/users/tasks", name: "admin-users-tasks", component: () => import("@/views/admin/TasksView.vue"), meta: { group: "管理工作", parent: "人员与任务", title: "任务管理", requiresAdmin: true } },

        // ---------- 管理工作：直接项 ----------
        { path: "admin/message-send", name: "admin-message-send", component: () => import("@/views/admin/MessageSendView.vue"), meta: { group: "管理工作", title: "消息发送", requiresAdmin: true } },
        { path: "admin/export", name: "admin-export", component: () => import("@/views/admin/ExportView.vue"), meta: { group: "管理工作", title: "数据集导出", requiresAdmin: true } },

        // ---------- 旧地址兼容（P2）：软重定向到新位置，保留书签与已发出的链接 ----------
        // 「数据总览」已并入首页：管理员首页即总览，旧地址回首页即可
        { path: "admin/overview", redirect: { name: "home" } },
        { path: "my-recordings", redirect: { name: "record-history" } },
        { path: "my-annotations", redirect: { name: "annotation-history" } },
        { path: "admin/text-import", redirect: { name: "admin-texts-import" } },
        { path: "admin/text-import-manage", redirect: { name: "admin-texts-ledger" } },
        { path: "admin/audio-upload", redirect: { name: "admin-audio-upload" } },
        { path: "admin/audio-import", redirect: { name: "admin-audio-scan" } },
        { path: "admin/recordings", redirect: { name: "admin-records-recording" } },
        { path: "admin/annotations", redirect: { name: "admin-records-annotation" } },
        { path: "admin/tasks", redirect: { name: "admin-users-tasks" } },
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

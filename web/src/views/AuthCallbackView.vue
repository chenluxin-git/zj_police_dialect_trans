<script setup lang="ts">
/**
 * 浙警智治统一认证落地页（/auth）
 *
 * 由后端认证回调 302 而来：`{BASE_URL}#/auth?token=<本地会话token>`
 * 逻辑：取 token → fetchMe 复核 → 进首页；失败回登录页并提示。
 * 也支持 `#/auth?ticket=xxx`（动态秘钥模式下一次性票据换会话）。
 */
import { onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import { useUserStore } from "@/stores/user"

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const failed = ref("")
const retry = ref(0)

async function settle() {
  const token = (route.query.token as string) || ""
  const ticket = (route.query.ticket as string) || ""
  if (!token && !ticket) {
    failed.value = "未收到平台登录凭证，请从浙警智治终端重新进入本应用。"
    return
  }
  try {
    if (token) userStore.setSession(token)
    else await userStore.redeemTicket(ticket)
    await userStore.fetchMe()
    router.replace("/")
  } catch {
    userStore.clear()
    failed.value = "登录凭证校验失败或已过期，请从浙警智治终端重新进入本应用。"
  }
}

onMounted(() => {
  // 首次地址栏 token 可能尚未就绪（平台重定向竞态）：最多重试 20 次
  const run = async () => {
    await settle()
    if (failed.value && retry.value < 20 && !route.query.token && !route.query.ticket) {
      retry.value += 1
      setTimeout(run, 200)
    } else if (failed.value) {
      ElMessage.error(failed.value)
    }
  }
  void run()
})

function backToLogin() {
  router.replace({ path: "/login", query: { error: "zhijing" } })
}
</script>

<template>
  <main class="zp-auth">
    <section class="zp-auth-panel">
      <svg class="zp-emblem" viewBox="0 0 48 56" fill="none" aria-hidden="true">
        <path d="M24 2 44 8v18c0 14-9 23-20 28C13 49 4 40 4 26V8L24 2z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" />
        <path d="M24 17l2.5 5.1 5.6.8-4 4 .9 5.6L24 29.9l-5 2.6.9-5.6-4-4 5.6-.8L24 17z" fill="currentColor" />
      </svg>
      <h1>浙江公安<br />方言语料采集平台</h1>
      <p class="org">浙江省公安厅 · 方言转译大模型语料建设</p>
      <div class="foot">
        <span>公安内网系统 · 注意保密</span>
        <span>浙江省公安厅</span>
      </div>
    </section>

    <section class="zp-auth-form">
      <h2>正在通过浙警智治统一认证登录</h2>
      <p class="lead">已使用数字证书完成平台认证，正在建立应用会话…</p>
      <div v-if="!failed" class="zp-alert zp-alert--info zp-mt-24">请稍候，无需再次输入账号密码。</div>
      <div v-else class="zp-alert zp-alert--warn zp-mt-24">
        {{ failed }}
        <div class="zp-mt-16">
          <button class="zp-btn zp-btn--primary" type="button" @click="backToLogin">返回登录页</button>
        </div>
      </div>
    </section>
  </main>
</template>

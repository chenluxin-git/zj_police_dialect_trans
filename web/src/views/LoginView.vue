<script setup lang="ts">
import { onMounted, reactive, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import { useUserStore } from "@/stores/user"

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const form = reactive({ phone: "", password: "" })
const loading = ref(false)
/** 是否展示演示账号提示：仅开发环境展示（内网上架版本会被构建期剔除） */
const showDemo = import.meta.env.DEV

onMounted(() => {
  // 从浙警智治进入但认证失败时，后端会带错误信息回到这里
  if (route.query.error === "zhijing") {
    const msg = (route.query.msg as string) || ""
    ElMessage.warning(msg ? `平台认证未通过：${msg}` : "平台认证未通过，请从浙警智治终端重新进入本应用")
  }
})

async function submit() {
  if (!/^\d{11}$/.test(form.phone)) {
    ElMessage.error("请输入 11 位手机号")
    return
  }
  if (!form.password) {
    ElMessage.error("请输入密码")
    return
  }
  loading.value = true
  try {
    await userStore.login(form.phone, form.password)
    const redirect = (route.query.redirect as string) || "/"
    router.push(redirect)
  } catch {
    /* 错误已由 http 拦截器提示 */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="zp-auth">
    <!-- 左：身份面板 -->
    <section class="zp-auth-panel">
      <svg class="zp-emblem" viewBox="0 0 48 56" fill="none" aria-hidden="true">
        <path d="M24 2 44 8v18c0 14-9 23-20 28C13 49 4 40 4 26V8L24 2z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" />
        <path d="M24 17l2.5 5.1 5.6.8-4 4 .9 5.6L24 29.9l-5 2.6.9-5.6-4-4 5.6-.8L24 17z" fill="currentColor" />
      </svg>
      <h1>浙江公安<br />方言语料采集平台</h1>
      <p class="org">浙江省公安厅 · 方言转译大模型语料建设</p>

      <svg class="wave-svg" viewBox="0 0 520 72" fill="none" aria-hidden="true">
        <polyline
          points="0,36 40,36 55,20 70,50 85,28 100,44 115,36 150,36 165,10 180,60 195,22 210,48 225,34 260,36 275,16 290,54 305,26 320,46 335,36 370,36 385,18 400,56 415,24 430,44 445,36 520,36"
          stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      </svg>

      <div class="sample">
        <p class="d">「饭吃过了伐？」</p>
        <p class="m">吴语 · 释义：吃饭了吗</p>
      </div>

      <div class="foot">
        <span>公安内网系统 · 注意保密</span>
        <span>浙江省公安厅</span>
      </div>
    </section>

    <!-- 右：登录表单 -->
    <section class="zp-auth-form">
      <h2>账号登录</h2>
      <p class="lead">正式环境请从浙警智治终端点击本应用进入（数字证书免二次登录）</p>

      <form @submit.prevent="submit">
        <div class="zp-field">
          <label for="phone">手机号/警号<span class="req">*</span></label>
          <input class="zp-input" id="phone" v-model="form.phone" type="tel" maxlength="11"
            placeholder="请输入 11 位手机号" />
        </div>
        <div class="zp-field">
          <label for="pwd">密码<span class="req">*</span></label>
          <input class="zp-input" id="pwd" v-model="form.password" type="password" placeholder="请输入密码" />
          <p class="zp-hint">忘记密码请联系本级管理员重置</p>
        </div>

        <button class="zp-btn zp-btn--primary zp-btn--lg zp-btn--block" type="submit" :disabled="loading">
          登 录
        </button>
      </form>

      <p class="zp-center zp-mt-16 zp-text-3">还没有账号？<router-link to="/register">注册新账号</router-link></p>

      <div v-if="showDemo" class="zp-alert zp-alert--info zp-mt-24" style="font-size:12px; line-height: 1.9">
        <span>
          演示账号（密码均为 123456，仅本地开发环境展示）：<br />
          33000000001 超级管理员 ／ 33100000001 市级管理员（台州）／ 33010000001 市级管理员（杭州）<br />
          33100400001 区县管理员（路桥）／ 33100400002 民警（路桥）
        </span>
      </div>
    </section>
  </main>
</template>
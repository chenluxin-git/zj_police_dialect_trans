<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import { api } from "@/api/http"
import { register } from "@/api/auth"

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

const router = useRouter()
const form = reactive({
  phone: "",
  password: "",
  confirm: "",
  real_name: "",
  region_path: [] as string[],
  station: "",
})

const regionTree = ref<RegionNode[]>([])
const stations = ref<Station[]>([])
const submitting = ref(false)
const cascaderProps = { value: "code", label: "name", children: "children" }

async function loadRegions() {
  try {
    regionTree.value = await api.get<RegionNode[]>("/regions/tree")
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
}

// 区域级联变更 → 按区县 code 拉派出所联动
watch(
  () => form.region_path,
  async (path) => {
    form.station = ""
    stations.value = []
    if (!path.length) return
    const code = path[path.length - 1]
    try {
      stations.value = await api.get<Station[]>(`/police_stations/by-region/${code}`)
    } catch {
      /* 错误已由 http 拦截器提示 */
    }
  },
)

async function submit() {
  if (!/^\d{11}$/.test(form.phone)) {
    ElMessage.error("手机号必须为 11 位数字")
    return
  }
  if (form.password.length < 8 || form.password.length > 20) {
    ElMessage.error("密码需 8-20 位")
    return
  }
  if (form.password !== form.confirm) {
    ElMessage.error("两次输入的密码不一致")
    return
  }
  if (!form.real_name.trim()) {
    ElMessage.error("请填写真实姓名")
    return
  }
  if (form.region_path.length === 0) {
    ElMessage.error("请选择所属区域")
    return
  }
  if (!form.station) {
    ElMessage.error("请选择所属派出所")
    return
  }
  submitting.value = true
  try {
    await register({
      phone: form.phone,
      password: form.password,
      real_name: form.real_name.trim(),
      police_station: form.station,
      region_code: form.region_path[form.region_path.length - 1],
    })
    ElMessage.success("注册成功，请登录")
    router.push("/login")
  } catch {
    /* 错误已由 http 拦截器提示 */
  } finally {
    submitting.value = false
  }
}

onMounted(loadRegions)
</script>

<template>
  <main class="zp-auth">
    <!-- 左：身份面板（与登录一致） -->
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
        <p class="d">「侬是啥地方人？」</p>
        <p class="m">吴语 · 释义：你是哪里人</p>
      </div>
      <div class="foot">
        <span>公安内网系统 · 注意保密</span>
        <span>浙江省公安厅</span>
      </div>
    </section>

    <!-- 右：注册表单 -->
    <section class="zp-auth-form">
      <h2>注册账号</h2>
      <p class="lead">请如实填写姓名与所属单位，便于任务统计</p>

      <form @submit.prevent="submit">
        <div class="zp-field">
          <label for="phone">手机号<span class="req">*</span></label>
          <input class="zp-input" id="phone" v-model="form.phone" type="tel" maxlength="11"
            placeholder="用于登录与联系" />
          <p class="zp-hint zp-hint--warn">手机号一旦注册不可更改</p>
        </div>

        <div class="zp-form-row">
          <div class="zp-field">
            <label for="pwd">设置密码<span class="req">*</span></label>
            <input class="zp-input" id="pwd" v-model="form.password" type="password" placeholder="8-20 位" />
          </div>
          <div class="zp-field">
            <label for="pwd2">确认密码<span class="req">*</span></label>
            <input class="zp-input" id="pwd2" v-model="form.confirm" type="password" placeholder="再次输入" />
          </div>
        </div>

        <div class="zp-field">
          <label for="name">真实姓名<span class="req">*</span></label>
          <input class="zp-input" id="name" v-model="form.real_name" type="text" placeholder="如不便透露可填写「匿名」" />
        </div>

        <div class="zp-field">
          <label>所属区域<span class="req">*</span></label>
          <el-cascader v-model="form.region_path" :options="regionTree" :props="cascaderProps"
            placeholder="请选择省 / 市 / 区县" clearable style="width:100%" />
        </div>

        <div class="zp-field">
          <label for="station">所属派出所<span class="req">*</span></label>
          <el-select v-model="form.station" id="station" placeholder="请选择" clearable style="width:100%">
            <el-option v-for="s in stations" :key="s.code" :label="s.name" :value="s.name" />
          </el-select>
        </div>

        <button class="zp-btn zp-btn--primary zp-btn--lg zp-btn--block" type="submit" :disabled="submitting">
          注 册
        </button>
      </form>

      <p class="zp-center zp-mt-16 zp-text-3">已有账号？<router-link to="/login">返回登录</router-link></p>
    </section>
  </main>
</template>
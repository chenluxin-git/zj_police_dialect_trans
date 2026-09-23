/**
 * 用户会话 store：登录（token+user 持久化 localStorage）、fetchMe、登出
 * 登录响应 data: {token, user: {id, real_name, role, region_code}}
 * 浙警智治接入后，用户从平台进入（认证回调 → /auth 页），由 setSession/redeemTicket 建立会话
 */
import { defineStore } from "pinia"
import { api, TOKEN_KEY } from "@/api/http"

export interface UserInfo {
  id: number
  real_name: string
  role: string // user / admin / super_admin
  region_code: string
  phone?: string | null
  /** 身份证号/数字证书主体标识（平台登录后有值；零信任 role-update 用它定位用户） */
  cert_id?: string
  police_no?: string
  dept_name?: string
  org_code?: string
  source?: string // local / zhijing
}

export const useUserStore = defineStore("user", {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || "",
    user: null as UserInfo | null,
  }),
  getters: {
    isAdmin: (s) => s.user?.role === "admin" || s.user?.role === "super_admin",
    roleLabel: (s) =>
      s.user?.role === "super_admin" ? "超级管理员" : s.user?.role === "admin" ? "管理员" : "民警",
    /** 顶栏展示用：企微平台用户显示警号，本地账号显示手机号 */
    accountLabel: (s) => s.user?.police_no || s.user?.phone || "",
  },
  actions: {
    async login(phone: string, password: string) {
      const data = await api.post<{ token: string; user: UserInfo }>("/auth/login", {
        phone,
        password,
      })
      this.setSession(data.token, data.user)
    },
    /** 平台回调携带的 token：只保存，不信任其中的用户信息（随后 fetchMe 复核） */
    setSession(token: string, user?: UserInfo | null) {
      this.token = token
      this.user = user ?? null
      localStorage.setItem(TOKEN_KEY, token)
    },
    /** 一次性票据换会话（动态秘钥模式） */
    async redeemTicket(ticket: string) {
      const data = await api.post<{ token: string; user: UserInfo }>("/auth/zhijing/exchange", { ticket })
      this.setSession(data.token, data.user)
    },
    async fetchMe() {
      this.user = await api.get<UserInfo>("/auth/me")
    },
    async logout() {
      try {
        await api.post("/auth/logout")
      } catch {
        /* 记录失败不阻塞退出 */
      }
      this.clear()
    },
    clear() {
      this.token = ""
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
    },
  },
})

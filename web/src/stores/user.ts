/**
 * 用户会话 store：登录（token+user 持久化 localStorage）、fetchMe、登出
 * 登录响应 data: {token, user: {id, real_name, role, region_code}}
 */
import { defineStore } from "pinia"
import { api, TOKEN_KEY } from "@/api/http"

export interface UserInfo {
  id: number
  real_name: string
  role: string // user / admin / super_admin
  region_code: string
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
  },
  actions: {
    async login(phone: string, password: string) {
      const data = await api.post<{ token: string; user: UserInfo }>("/auth/login", {
        phone,
        password,
      })
      this.token = data.token
      this.user = data.user
      localStorage.setItem(TOKEN_KEY, data.token)
    },
    async fetchMe() {
      this.user = await api.get<UserInfo>("/auth/me")
    },
    logout() {
      this.token = ""
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      window.location.href = "/login"
    },
  },
})

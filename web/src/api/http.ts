/**
 * axios 封装（全局唯一出口）
 * - baseURL 取 VITE_API_BASE（默认 /api）
 * - 请求头自动带 Authorization: Bearer <token>
 * - 后端信封 {code, msg, data}：code!==0 → ElMessage 报错并 reject；成功直接返回 data
 * - 401 → 清 token 跳 /login；非 2xx 透出后端 detail/msg
 */
import axios from "axios"
import type { AxiosRequestConfig } from "axios"
import { ElMessage } from "element-plus"

export const TOKEN_KEY = "zp_token"

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || "/api",
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === "object" && "code" in body && !(body instanceof Blob)) {
      if (body.code !== 0) {
        const msg = body.msg || "请求失败"
        ElMessage.error(msg)
        return Promise.reject(new Error(msg))
      }
      return body.data // 解信封：调用方拿到的就是 data
    }
    return body // 非信封响应（文件流等）原样返回
  },
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      const loginPath = import.meta.env.BASE_URL + "login"
      if (window.location.pathname !== loginPath) {
        window.location.href = loginPath
      }
    }
    const data = err.response?.data
    const msg =
      (data && (typeof data.detail === "string" ? data.detail : data.msg)) ||
      err.message ||
      "网络错误"
    ElMessage.error(msg)
    return Promise.reject(err)
  },
)

/** 信封已解包的便捷方法（返回值即后端 data） */
export const api = {
  get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return http.get(url, config) as Promise<T>
  },
  post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return http.post(url, data, config) as Promise<T>
  },
  put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return http.put(url, data, config) as Promise<T>
  },
  delete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return http.delete(url, config) as Promise<T>
  },
}

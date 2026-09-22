/**
 * 认证 API（对应后端 T5：POST /auth/register；登录/me 复用 stores/user.ts）
 */
import { api } from "./http"

export interface AuthUser {
  id: number
  phone: string
  real_name: string
  police_station: string
  region_code: string
  role: string
}

export interface RegisterPayload {
  phone: string
  password: string
  real_name: string
  police_station: string
  region_code: string
}

export function register(payload: RegisterPayload) {
  return api.post<{ token: string; user: AuthUser }>("/auth/register", payload)
}
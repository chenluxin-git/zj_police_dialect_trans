/**
 * 前端错误与行为日志上报
 *
 * 为什么需要：后端日志再全，也看不到「浏览器里发生了什么」。
 * 用户说「点进去白屏」「点了没反应」时，后端可能一行日志都没有——
 * 因为请求根本没发出去（JS 崩了 / 路由挂了 / 静态资源 404）。
 *
 * 采集内容：
 * - Vue 组件渲染/生命周期异常（app.config.errorHandler）
 * - 未捕获的 Promise rejection
 * - window.onerror（语法错误、第三方脚本异常）
 * - 接口失败（由 http 拦截器调用 reportApiError，带 trace_id 与后端对齐）
 * - 路由跳转失败、静态资源加载失败
 * - 页面崩溃前的一次性快照（可选环境信息）
 *
 * 传输：批量 + 节流，`navigator.sendBeacon` 优先（页面卸载也能发出去），
 * 失败落 localStorage 下次补发，避免内网抖动丢日志。
 *
 * 隐私：**不上报任何业务数据**。只报错误信息、堆栈、路由、trace_id 与环境。
 * 身份证号/警号等不会出现在这里；URL 里的 query 会被截断到 path（防泄漏）。
 */
import { TOKEN_KEY } from "@/api/http"

const ENDPOINT = "/api/client-logs"
const FLUSH_INTERVAL = 10_000      // 常态 10s 一批
const MAX_BUFFER = 50              // 缓冲区上限，超了立刻发
const MAX_STACK = 4000             // 单条堆栈截断
const STORAGE_KEY = "zp_client_log_backlog"
const MAX_BACKLOG = 10             // 落盘补发上限，防占满 localStorage

export interface ClientLogItem {
  level: "error" | "warn" | "info"
  /** 来源：vue / window / promise / api / router / resource */
  source: string
  message: string
  /** 堆栈（已截断） */
  stack?: string
  /** 路由 path（**不含 query**，防泄漏） */
  route?: string
  /** 后端 trace_id，用于与 app.request.log 对齐 */
  traceId?: string
  /** 接口相关信息 */
  url?: string
  status?: number
  at: string
}

let buffer: ClientLogItem[] = []
let timer: ReturnType<typeof setInterval> | null = null
let installed = false

function nowIso() {
  return new Date().toISOString()
}

function clip(s: string | undefined, n = MAX_STACK) {
  if (!s) return undefined
  return s.length > n ? s.slice(0, n) + `…<截断 共${s.length}字符>` : s
}

/** 只保留 path：query 里可能有平台回传的人员参数，不能上报 */
function safePath(full: string): string {
  try {
    const u = new URL(full, window.location.origin)
    return u.pathname
  } catch {
    return String(full).split("?")[0]
  }
}

function currentRoute(): string {
  try {
    // 不用 useRoute()：logger 在 app 之外也可能被调用，读 location 最稳
    return safePath(window.location.pathname + window.location.search)
  } catch {
    return ""
  }
}

export function pushLog(item: Omit<ClientLogItem, "at">) {
  buffer.push({ ...item, stack: clip(item.stack), at: nowIso() })
  if (buffer.length >= MAX_BUFFER) void flush()
}

function readBacklog(): ClientLogItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as ClientLogItem[]) : []
  } catch {
    return []
  }
}

function writeBacklog(items: ClientLogItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(-MAX_BACKLOG)))
  } catch {
    /* 配额满/隐私模式：忽略，不能因为记日志把业务搞挂 */
  }
}

async function flush() {
  if (!buffer.length) return
  const items = buffer
  buffer = []

  const payload = JSON.stringify({ items })
  // 优先 sendBeacon：页面卸载时也能发出去，且不阻塞
  try {
    if (navigator.sendBeacon) {
      const ok = navigator.sendBeacon(
        ENDPOINT,
        new Blob([payload], { type: "application/json" }),
      )
      if (ok) return
    }
  } catch {
    /* 落到 fetch */
  }

  try {
    const token = localStorage.getItem(TOKEN_KEY)
    const resp = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: payload,
      keepalive: true,
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  } catch {
    // 发不出去就暂存，下次启动补发 —— 内网抖动时不能把线索丢了
    writeBacklog([...readBacklog(), ...items])
  }
}

/** 补发上次没送出去的（页面加载后调用一次） */
export async function flushBacklog() {
  const backlog = readBacklog()
  if (!backlog.length) return
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    const resp = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ items: backlog }),
    })
    if (resp.ok) localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* 留着下次再试 */
  }
}

/** 接口失败上报（由 http.ts 拦截器调用），带 trace_id 与后端对齐 */
export function reportApiError(info: {
  method?: string
  url: string
  status?: number
  message: string
  traceId?: string
}) {
  pushLog({
    level: info.status && info.status >= 500 ? "error" : "warn",
    source: "api",
    message: `${info.method || "REQ"} ${info.url} -> ${info.status ?? "-"} ${info.message}`,
    route: currentRoute(),
    url: safePath(info.url),
    status: info.status,
    traceId: info.traceId,
  })
}

/** 静态资源加载失败（白屏常见原因：产物没上传全 / 子路径 base 配错） */
function watchResourceErrors() {
  window.addEventListener(
    "error",
    (e) => {
      const t = e.target as HTMLElement | null
      if (!t || !(t instanceof HTMLScriptElement || t instanceof HTMLLinkElement || t instanceof HTMLImageElement)) {
        return
      }
      const src = (t as HTMLScriptElement).src || (t as HTMLLinkElement).href || ""
      pushLog({
        level: "error",
        source: "resource",
        message: `静态资源加载失败：${t.tagName} ${src}`,
        route: currentRoute(),
        url: safePath(src),
      })
    },
    true, // 捕获阶段：资源错误不冒泡
  )
}

/** 安装全局捕获。应在 main.ts 里尽早调用。 */
export function installClientLogger() {
  if (installed) return
  installed = true

  // 1) window.onerror：语法错误、未捕获同步异常
  window.addEventListener("error", (e) => {
    // 资源错误由 watchResourceErrors 处理，这里跳过避免重复
    if (e.target && !(e instanceof ErrorEvent)) return
    pushLog({
      level: "error",
      source: "window",
      message: e.message || "未知脚本错误",
      stack: e.error?.stack,
      route: currentRoute(),
    })
  })

  // 2) 未捕获 Promise rejection：接口/异步逻辑最常见的静默失败
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason
    pushLog({
      level: "error",
      source: "promise",
      message: `未处理的 Promise 异常：${r?.message || String(r)}`,
      stack: r?.stack,
      route: currentRoute(),
    })
  })

  watchResourceErrors()

  // 3) 定时批量发送
  timer = setInterval(() => void flush(), FLUSH_INTERVAL)

  // 4) 页面卸载前尽量发出去
  window.addEventListener("pagehide", () => void flush())
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flush()
  })

  // 5) 补发上次没送出去的
  void flushBacklog()

  pushLog({
    level: "info",
    source: "boot",
    message: `前端日志已启用；UA=${navigator.userAgent}`,
    route: currentRoute(),
  })
}

/** 给 Vue 的 app.config.errorHandler 用 */
export function reportVueError(err: unknown, info: string) {
  const e = err as Error
  pushLog({
    level: "error",
    source: "vue",
    message: `Vue 异常（${info}）：${e?.message || String(err)}`,
    stack: e?.stack,
    route: currentRoute(),
  })
}

export function stopClientLogger() {
  if (timer) clearInterval(timer)
  timer = null
}

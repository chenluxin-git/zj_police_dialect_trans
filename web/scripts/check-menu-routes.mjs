/**
 * 菜单 / 路由一致性自检（P2）
 *
 * 为什么需要：MainLayout 的侧栏菜单和 router/index.ts 各硬编码一份路径。改了路由忘了
 * 改菜单（或反之）会静默产生「点了没反应 / 落到首页」这类 bug，类型检查与构建都发现不了。
 *
 * 做法：逐行解析两个源文件，不启动 Vite、不建 router 实例。
 * （曾尝试 vite createServer + ssrLoadModule + router.resolve：会拉起完整 element-plus
 *  依赖图且进程不退出，作为每次构建都跑的检查太重，已实测会挂住。）
 *
 * 用法：node scripts/check-menu-routes.mjs（npm run check:menu）
 */
import { readFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import path from "node:path"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.join(HERE, "..", "src")

// ---------- 期望的菜单结构（改菜单时同步改这里，就是本检查的意义所在） ----------
const EXPECTED_MENU = {
  "日常工作": ["首页", "录音采集", "录音标注", "语音转译"],
  "消息": ["我的消息"],
  "管理工作": [
    "语料管理",
    "音频素材",
    "采集记录",
    "人员与任务",
    "消息发送",
    "数据集导出",
  ],
}

/** 旧地址兼容重定向：必须仍存在于路由表且带 redirect */
const LEGACY_PATHS = [
  "/admin/overview",
  "/my-recordings",
  "/my-annotations",
  "/record",
  "/annotation",
  "/admin/texts",
  "/admin/audio",
  "/admin/records",
  "/admin/users",
  "/admin/text-import",
  "/admin/text-import-manage",
  "/admin/audio-upload",
  "/admin/audio-import",
  "/admin/recordings",
  "/admin/annotations",
  "/admin/tasks",
]

const failures = []
let checks = 0
function check(cond, message) {
  checks += 1
  if (!cond) failures.push(message)
}

const routerSrc = await readFile(path.join(SRC, "router", "index.ts"), "utf8")
const layoutSrc = await readFile(path.join(SRC, "layouts", "MainLayout.vue"), "utf8")

// ---------- 解析路由（逐行；支持 path 独占一行的情况） ----------
/** @type {{path:string,name:string,line:string}[]} */
const routes = []
const routerLines = routerSrc.split(/\r?\n/)
for (let i = 0; i < routerLines.length; i++) {
  const line = routerLines[i]
  const m = line.match(/^\s*\{?\s*path:\s*"([^"]*)"/)
  if (!m) continue
  const nameM = line.match(/name:\s*"([^"]+)"/)
  // 兜底：name 可能换行写在下一行
  const name = nameM ? nameM[1] : i + 1 < routerLines.length ? (routerLines[i + 1].match(/name:\s*"([^"]+)"/)?.[1] ?? "") : ""
  routes.push({ path: m[1], name, line })
}
check(routes.length > 0, "未能从 router/index.ts 解析出任何路由")

/** 子路由路径不带前导斜杠，顶层路由自带；统一成绝对路径 */
const fullPath = (p) => (p === "" ? "/" : p.startsWith("/") ? p : "/" + p)
const routePaths = new Set(routes.map((r) => fullPath(r.path)))
/** 带 redirect 的路径（父路径 + 旧地址兼容） */
const redirectPaths = new Set(
  routes.filter((r) => /redirect:/.test(r.line)).map((r) => fullPath(r.path)),
)

check(routePaths.has("/"), "路由表缺少根路径 /")

// ---------- 1. 管理端路由必须 requiresAdmin ----------
for (const r of routes) {
  const p = fullPath(r.path)
  if (!p.startsWith("/admin")) continue
  if (redirectPaths.has(p)) continue // 纯重定向父路径无需 meta
  check(/requiresAdmin:\s*true/.test(r.line), `管理端路由 ${p} 缺少 requiresAdmin`)
}

// ---------- 2. 业务路由必须有 group + title（公开页与纯重定向除外） ----------
for (const r of routes) {
  const p = fullPath(r.path)
  if (p === "/" || p.startsWith("/login") || p.startsWith("/register") || p.startsWith("/auth")) continue
  if (p.includes(":pathMatch")) continue
  if (redirectPaths.has(p)) continue
  check(/group:\s*"/.test(r.line), `路由 ${p} 缺少 meta.group`)
  check(/title:\s*"/.test(r.line), `路由 ${p} 缺少 meta.title`)
}

// ---------- 3. 解析菜单（取 MENU 定义段，逐行按缩进识别直接项 / 二级项） ----------
const menuStart = layoutSrc.indexOf("const MENU")
const menuEnd = layoutSrc.indexOf("const route = useRoute()")
check(menuStart >= 0 && menuEnd > menuStart, "未能定位 MainLayout.vue 的 MENU 定义")
const menuBlock = layoutSrc.slice(menuStart, menuEnd)

/** 菜单直接项（缩进 6 空格的 { label, to }） */
const directTos = [...menuBlock.matchAll(/^ {6}\{ label: "([^"]+)", to: "([^"]+)"[^}]*\}/gm)].map(
  (m) => ({ label: m[1], to: m[2] }),
)
/** 可展开组（缩进 6 空格的 { 换行后 label + children） */
const groupLabels = [...menuBlock.matchAll(/^ {6}\{\s*\n {8}label: "([^"]+)",\s*\n {8}children: \[/gm)].map(
  (m) => m[1],
)
/** 二级项（缩进 10 空格） */
const leafTos = [...menuBlock.matchAll(/^ {10}\{ label: "([^"]+)", to: "([^"]+)"[^}]*\}/gm)].map(
  (m) => ({ label: m[1], to: m[2] }),
)
/**
 * 单行分组的直接项（形如 entries: [{ label, to }]，缩进 4 空格）。
 * 「消息」分组就是这种写法，不单独处理会漏掉「我的消息」。
 */
const inlineTos = [...menuBlock.matchAll(/^ {4}entries: \[\{ label: "([^"]+)", to: "([^"]+)"[^}]*\}/gm)].map(
  (m) => ({ label: m[1], to: m[2] }),
)
/** 三个分组标题 */
const sectionLabels = [...menuBlock.matchAll(/^ {4}group: "([^"]+)"/gm)].map((m) => m[1])

/** 侧栏全部有 to 的项（直接项 + 单行项 + 二级项），用于反向覆盖检查 */
const allMenuTos = [...directTos, ...inlineTos, ...leafTos]

check(directTos.length > 0, "未能解析出菜单直接项")
check(leafTos.length > 0, "未能解析出菜单二级项")
check(groupLabels.length > 0, "未能解析出菜单可展开组")

// 3a. 规模与结构断言
check(
  sectionLabels.length === Object.keys(EXPECTED_MENU).length,
  `侧栏分组数为 ${sectionLabels.length}，预期 ${Object.keys(EXPECTED_MENU).length}`,
)
for (const [group, entries] of Object.entries(EXPECTED_MENU)) {
  check(sectionLabels.includes(group), `侧栏缺少分组「${group}」`)
  const found = [...directTos.map((d) => d.label), ...inlineTos.map((d) => d.label), ...groupLabels]
  for (const label of entries) {
    check(found.includes(label), `分组「${group}」下缺少菜单项「${label}」`)
  }
}

// 3b. 每个菜单 to 必须命中真实路由，且不能指向纯重定向父路径
check(allMenuTos.length > 0, "菜单 to 总数为 0")
for (const item of allMenuTos) {
  check(routePaths.has(item.to), `菜单项「${item.label}」(${item.to}) 在路由表中不存在`)
  check(
    !redirectPaths.has(item.to),
    `菜单项「${item.label}」(${item.to}) 指向重定向父路径，应直接指向子页`,
  )
}

// 3c. 反向检查：每个非重定向的业务页面都应有菜单入口（防止新增页面忘了挂菜单）
const menuToSet = new Set(allMenuTos.map((d) => d.to))
for (const r of routes) {
  const p = fullPath(r.path)
  if (p === "/" || p.startsWith("/login") || p.startsWith("/register") || p.startsWith("/auth")) continue
  if (p.includes(":pathMatch")) continue
  if (redirectPaths.has(p)) continue
  check(menuToSet.has(p), `路由 ${p} 没有任何侧栏菜单入口（新增页面忘了挂菜单？）`)
}

// ---------- 4. 旧地址兼容重定向仍在 ----------
for (const legacy of LEGACY_PATHS) {
  check(routePaths.has(legacy), `旧地址 ${legacy} 已不在路由表中（兼容重定向被删？）`)
  check(redirectPaths.has(legacy), `旧地址 ${legacy} 未配置 redirect，兼容跳转会失效`)
}

if (failures.length) {
  console.error(`\n✗ 菜单/路由一致性自检失败：${failures.length} 项不通过（共 ${checks} 项检查）\n`)
  for (const f of failures) console.error(`  - ${f}`)
  console.error("")
  process.exit(1)
}
console.log(
  `✓ 菜单/路由一致性自检通过（${checks} 项检查：${sectionLabels.length} 分组 / ${groupLabels.length} 个二级组 / ${directTos.length} 个直接项 / ${leafTos.length} 个二级项）`,
)

// 必须最先导入：补齐 Chrome80 缺失的运行时 API（Array.prototype.at / Object.hasOwn）
import "./polyfills"
import { createApp } from "vue"
import { createPinia } from "pinia"
import ElementPlus from "element-plus"
import * as ElementPlusIconsVue from "@element-plus/icons-vue"
import "element-plus/dist/index.css"
import App from "./App.vue"
import router from "./router"
import { installClientLogger, reportVueError } from "./utils/clientLogger"
import "./styles/theme.css"

// 前端错误捕获要**尽早安装**（在 polyfills 之后、createApp 之前）：
// 晚于 mount 就抓不到挂载期的异常，而内网首次部署的白屏多半发生在挂载期
installClientLogger()

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus) // 全量引入
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

// Vue 组件内的渲染/生命周期异常：默认只打 console，内网排障拿不到，这里上报
app.config.errorHandler = (err, _instance, info) => {
  reportVueError(err, String(info))
  console.error(err) // 保留控制台输出，便于现场 F12 直接看
}

// 路由跳转/懒加载失败：发版后旧 chunk 被清会导致白屏，这条日志是唯一线索
router.onError((err, to) => {
  reportVueError(err, `router -> ${to?.fullPath || "?"}`)
})

app.mount("#app")

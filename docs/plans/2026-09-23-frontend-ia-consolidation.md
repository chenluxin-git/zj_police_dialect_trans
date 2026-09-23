# 前端信息架构整治方案（侧边栏二级菜单 + 同源页面合并）

- 日期：2026-09-23（v2：侧边栏改为二级菜单）
- 范围：`web/`（Vue 3 + Element Plus）。`dome/` 静态设计稿本次不动，保持存档一致。
- 状态：**待确认**（确认后按 §9 阶段实施）

---

## 1. 诊断：现状为什么「不清爽」

| 现象 | 证据 |
|---|---|
| 侧边栏 19 项平铺、无层级 | `MainLayout.vue:24-57`：日常工作 5 + 消息 1 + 管理工作 12，全部是同级 `<router-link>` |
| 同一实体被拆成多页 | 文本语料拆 3 页、音频素材拆 2 页、录音/标注各拆「作业页 + 历史页」 |
| 页面之间靠文案互相指路 | `TextImportView.vue:274,279` 写着「可在「导入台账」查看与撤销」；`AudioUploadView.vue:230` 写着「建议使用「音频导入」的扫盘方式」——两页本是一件事的两个入口 |
| 历史列表在侧边栏与作业页平级 | 「录音采集」与「我的录音」是同一实体的两种视图，却被并列成两个菜单项 |
| 管理工作 12 项无任何子分组 | `MainLayout.vue:43-54` 直接 `v-for` 出 12 个同级项 |

结论：**页面数 > 实体数**。19 个页面实际只覆盖约 7 个实体（用户、文本、音频素材、录音、标注、消息、任务 + 一个只读总览）。合并边界应由实体决定，而不是由「读」和「写」决定。

---

## 2. 目标结构

### 2.1 侧边栏：19 项 → 11 项（4 个可展开组 + 7 个直接项）

```
┌──────────────────────────┐
│ 🛡 浙江公安               │
│    方言语料采集平台        │
├──────────────────────────┤
│ 日常工作                  │   ← 分组标题（不可点）
│   首页                    │   ← 直接项
│ ▸ 录音采集                │   ← 可展开组（默认收起）
│     开始录音              │   ← 二级项
│     历史录音              │
│ ▸ 录音标注                │
│     开始标注              │
│     历史标注              │
├──────────────────────────┤
│ 消息                      │
│   我的消息          ③     │   ← 直接项（未读角标）
├──────────────────────────┤
│ 管理工作                  │
│   数据总览                │   ← 直接项
│ ▾ 语料管理                │   ← 可展开组（当前路由所在组自动展开）
│     语料浏览              │
│     批量导入              │
│     导入台账              │
│ ▾ 音频素材                │
│     上传入库              │
│     扫盘导入              │
│ ▾ 采集记录                │
│     录音                  │
│     标注                  │
│ ▸ 人员与任务              │
│     人员管理              │
│     任务管理              │
│   消息发送                │   ← 直接项
│   数据集导出              │   ← 直接项
└──────────────────────────┘
```

| 指标 | 现在 | 改后 |
|---|---|---|
| 侧边栏可见行 | 19 | 11（4 组 + 7 直接项） |
| 展开全部组后 | — | 24 行，但用户可以只展开要看的那一组 |
| 管理工作同级项 | 12 | 7 |
| 一级分组 | 3 | 3（不变） |

**为什么保留「消息」独立**：顶栏铃铛与它构成跨页入口，且它不属于任何作业流。

### 2.2 层级分工：侧栏负责切换，页面不再套 Tab

- **侧边栏二级菜单 = 页面内部的各个面**（浏览 / 导入 / 台账 / 上传 / 扫盘 / 录音 / 标注 / 人员 / 任务）。
- **合并后的页面不再重复渲染一层 Tab 条**，直接渲染当前二级路由对应的面板。面包屑承担"我在哪一层"的表达。
- 好处：同一功能只有一个入口，不会出现"侧栏点了『批量导入』进去又要点一次 Tab"的双层导航。

---

## 3. 路由改造：改为嵌套路由

`web/src/router/index.ts` 调整（只列变化部分）：

```ts
{
  path: "/",
  component: MainLayout,
  children: [
    { path: "", name: "home", component: HomeView, meta: { group: "日常工作", title: "首页" } },

    // ---- 录音采集（二级）----
    { path: "record", name: "record",
      redirect: { name: "record-work" },
      meta: { group: "日常工作", parent: "录音采集" } },
    { path: "record/work", name: "record-work", component: RecordView,
      meta: { group: "日常工作", parent: "录音采集", title: "开始录音" } },
    { path: "record/history", name: "record-history", component: MyRecordingsView,
      meta: { group: "日常工作", parent: "录音采集", title: "历史录音" } },

    // ---- 录音标注（二级）----
    { path: "annotation", name: "annotation",
      redirect: { name: "annotation-work" },
      meta: { group: "日常工作", parent: "录音标注" } },
    { path: "annotation/work", name: "annotation-work", component: AnnotationView,
      meta: { group: "日常工作", parent: "录音标注", title: "开始标注" } },
    { path: "annotation/history", name: "annotation-history", component: MyAnnotationsView,
      meta: { group: "日常工作", parent: "录音标注", title: "历史标注" } },

    { path: "messages", name: "messages", component: MessagesView,
      meta: { group: "消息", title: "我的消息" } },

    // ---- 管理工作：直接项 ----
    { path: "admin/overview", name: "admin-overview", component: OverviewView,
      meta: { group: "管理工作", title: "数据总览", requiresAdmin: true } },

    // ---- 语料管理（二级）----
    { path: "admin/texts", name: "admin-texts", redirect: { name: "admin-texts-browse" },
      meta: { group: "管理工作", parent: "语料管理", requiresAdmin: true } },
    { path: "admin/texts/browse", name: "admin-texts-browse", component: TextBrowsePanel,
      meta: { group: "管理工作", parent: "语料管理", title: "语料浏览", requiresAdmin: true } },
    { path: "admin/texts/import", name: "admin-texts-import", component: TextImportPanel,
      meta: { group: "管理工作", parent: "语料管理", title: "批量导入", requiresAdmin: true } },
    { path: "admin/texts/ledger", name: "admin-texts-ledger", component: TextLedgerPanel,
      meta: { group: "管理工作", parent: "语料管理", title: "导入台账", requiresAdmin: true } },

    // ---- 音频素材（二级）----
    { path: "admin/audio", name: "admin-audio", redirect: { name: "admin-audio-upload" },
      meta: { group: "管理工作", parent: "音频素材", requiresAdmin: true } },
    { path: "admin/audio/upload", name: "admin-audio-upload", component: AudioUploadPanel,
      meta: { group: "管理工作", parent: "音频素材", title: "上传入库", requiresAdmin: true } },
    { path: "admin/audio/scan", name: "admin-audio-scan", component: AudioScanPanel,
      meta: { group: "管理工作", parent: "音频素材", title: "扫盘导入", requiresAdmin: true } },

    // ---- 采集记录（二级）----
    { path: "admin/records", name: "admin-records", redirect: { name: "admin-records-recording" },
      meta: { group: "管理工作", parent: "采集记录", requiresAdmin: true } },
    { path: "admin/records/recording", name: "admin-records-recording", component: RecordingsPanel,
      meta: { group: "管理工作", parent: "采集记录", title: "录音", requiresAdmin: true } },
    { path: "admin/records/annotation", name: "admin-records-annotation", component: AnnotationsPanel,
      meta: { group: "管理工作", parent: "采集记录", title: "标注", requiresAdmin: true } },

    // ---- 人员与任务（二级）----
    { path: "admin/users", name: "admin-users", redirect: { name: "admin-users-people" },
      meta: { group: "管理工作", parent: "人员与任务", requiresAdmin: true } },
    { path: "admin/users/people", name: "admin-users-people", component: UsersPanel,
      meta: { group: "管理工作", parent: "人员与任务", title: "人员管理", requiresAdmin: true } },
    { path: "admin/users/tasks", name: "admin-users-tasks", component: TasksPanel,
      meta: { group: "管理工作", parent: "人员与任务", title: "任务管理", requiresAdmin: true } },

    // ---- 管理工作：直接项 ----
    { path: "admin/message-send", name: "admin-message-send", component: MessageSendView,
      meta: { group: "管理工作", title: "消息发送", requiresAdmin: true } },
    { path: "admin/export", name: "admin-export", component: ExportView,
      meta: { group: "管理工作", title: "数据集导出", requiresAdmin: true } },
  ],
}
```

**新增 `meta.parent`**（面包屑第二层）与 **`meta.title`** 组合出三级面包屑：`管理工作 / 语料管理 / 批量导入`。

**为什么用嵌套子路由而不是页内 Tab**：URL 直接表达层级，侧栏高亮天然正确，浏览器前进/后退可用，链接可分享。页内 Tab 会与侧栏二层重复。

**为什么 `admin/users`、`admin/texts` 等父路径保留 `redirect`**：旧链接与外部引用打到父路径时能落到默认子页，不会白屏。

---

## 4. 侧边栏二级菜单实现

### 4.1 `MainLayout.vue` 数据结构

把现在的扁平数组改成可含 `children` 的树：

```ts
interface MenuLeaf { label: string; to: string; badge?: boolean }
interface MenuEntry {
  label: string
  to?: string          // 无 children 时是直接项
  children?: MenuLeaf[] // 有 children 时是可展开组
}
interface MenuSection { group: string; adminOnly?: boolean; entries: MenuEntry[] }
```

### 4.2 需要新增的行为

| 行为 | 说明 |
|---|---|
| 展开/收起 | 组头点击切换；`expanded` 用 `ref<Set<string>>` 持有（复用 `OverviewView.vue:105-107` 已在本项目用过的 `Set` 模式） |
| 当前路由所在组自动展开 | `watch(() => route.path, ...)`：若命中某组的 `children`，把该组加入 `expanded`（只增不减，避免用户手动展开的组被收起） |
| 父组高亮 | 当前路由属于该组时，组头加 `is-open` 类（金色左边框 + 白字），让「我在这一组」可见 |
| 二级项高亮 | 沿用现有 `.router-link-exact-active`；二级项用 `exact-active` 而非 `active`，避免父路径的宽松匹配误亮 |
| 二级项缩进与连接线 | 新增 CSS |
| 无子项的组/项 | 「消息」「我的消息」「数据总览」「消息发送」「数据集导出」保持现在的单行链接样式，不加箭头 |

### 4.3 需要新增的 CSS（`web/src/styles/theme.css`）

现有体系里**没有**二级菜单样式，需要补约 25 行（`dome/assets/theme.css` 是静态稿副本，不改）：

```css
/* 侧栏二级菜单 */
.zp-menu-group-btn{                    /* 组头：复用 .zp-menu a 的外观基础上加箭头 */
  display:flex;align-items:center;justify-content:space-between;
  width:100%;background:none;border:none;border-left:3px solid transparent;
  color:#9FB3CE;font-size:14px;padding:9px 10px;margin:1px 0;
  border-radius:var(--radius);cursor:pointer;font-family:inherit;
  transition:background .15s,color .15s;
}
.zp-menu-group-btn:hover{background:rgba(255,255,255,.06);color:#fff}
.zp-menu-group-btn.is-open{background:var(--navy-800);color:#fff;border-left-color:var(--gold-500)}
.zp-menu-group-btn .zp-caret{transition:transform .15s ease;font-size:12px;color:#5F7699}
.zp-menu-group-btn.is-open .zp-caret{transform:rotate(90deg)}
.zp-menu-sub{padding-left:9px;margin-left:10px;border-left:1px solid rgba(255,255,255,.1)}
.zp-menu-sub a{
  font-size:13px;color:#8AA0C0;padding:7px 10px;border-left:3px solid transparent;
}
.zp-menu-sub a:hover{background:rgba(255,255,255,.06);color:#fff}
.zp-menu-sub a.router-link-exact-active{
  background:var(--navy-800);color:#fff;border-left-color:var(--gold-500);
}
```

箭头图标直接用已全局注册的 `@element-plus/icons-vue`（`main.ts:15-17` 已全量注册），例如 `<ArrowRight />`，不需要新增依赖。

面包屑模板同步：`管理工作 / 语料管理 / 批量导入`（`group / parent / title`）。

---

## 5. 页面规格

### 5.1 开始录音 `/record/work`（原 RecordView）

保留现有 5 张卡：我的任务进度、四步步骤条、本次文本（120s 倒计时）、录音/上传、上传后质检说明 + 底部提示。

**新增第 6 张只读卡「历史录音」**：

```
┌ 历史录音 ────────────────────────── 共 37 条  查看全部 → ┐
│ [警情] 你们不要吵了，都先坐下来，有话好好讲。              │
│        03-12 14:20 · 00:08 · 142 KB · 已通过   播放 删除 │
│ [生活] 我是社区民警，麻烦开下门。                          │
│        03-12 14:05 · 00:11 · 198 KB · 待质检   播放 删除 │
│ …（最近 5 条）                                            │
└──────────────────────────────────────────────────────────┘
```

- 数据：`GET /api/recordings?page=1&page_size=5`（复用 `listMyRecordings`，**不新增后端接口**）；`total` 字段直接用于「共 N 条」。
- 交互：`播放` 走现有 `fetchRecordingBlob` + `audioStore`；`删除` 走现有 `deleteRecording` 并复用「进度将扣减」二次确认；`查看全部 →` 跳 `/record/history`。
- 上传成功后自动刷新本卡与「我的任务」。
- **不做**：不在卡内嵌完整表格、不加筛选/分页——完整能力在 `/record/history`。
- 侧栏已有「历史录音」二级项，本卡保留「查看全部」属于**同页内容外跳**，不是重复导航入口。

### 5.2 开始标注 `/annotation/work`（原 AnnotationView）

保留现有 4 张卡（我的任务进度、当前音频 + 180s 倒计时 + 续期、标注结果表单、底部提示）。

**新增「我的标注」预览卡**（卡名保留「我的标注」，侧栏二级项名为「历史标注」，均指向同一历史页）：最近 5 条，展示 音频文件名 / 普通话翻译 / 标注时间，操作 `重听`（复用现 `MyAnnotationsView` 的修改弹窗：`AudioPlayer` + 可改译文）/ `删除`；`查看全部 →` 跳 `/annotation/history`。

### 5.3 历史录音 `/record/history`

原 `MyRecordingsView` 原样迁移：类别 / 质检状态 / 关键词筛选 + 表格 + 分页 + 播放 / 下载 / 删除全部保留。页头加「← 返回开始录音」。

### 5.4 历史标注 `/annotation/history`

原 `MyAnnotationsView` 原样迁移。页头加「← 返回开始标注」。

**已知后端短板**：`GET /api/annotations/my` 只接受 `page`/`page_size`，**不支持任何筛选**（`server/app/api/annotations.py:101-109`）。现页面用 `page_size=10000` 拉全量再前端过滤 + 前端分页——本次**不修**（属后端改造，见 §8）。预览卡只取 `page_size=5`，不触发该问题。

### 5.5 语料管理（3 页 → 3 个二级面板）

| 二级路由 | 面板来源 | 内容 |
|---|---|---|
| `/admin/texts/browse` 语料浏览 | TextsView | 类别 / 日期区间 / 关键词筛选 + checkbox 表 + 批量删除（回显 skipped 明细）+ 分页 |
| `/admin/texts/import` 批量导入 | TextImportView | txt/docx 模板下载 + 类别 + 归属区域 + 拖拽上传 + 导入进度轮询 |
| `/admin/texts/ledger` 导入台账 | TextImportManageView | 批次表 + 详情弹窗（样本文本）+ 撤销（409「被录音引用」透传） |

面板文件落 `web/src/views/admin/texts/`：`TextBrowsePanel.vue` / `TextImportPanel.vue` / `TextLedgerPanel.vue`。

**顺带修掉的重复与不一致**
- 三页各有一份 `CATEGORIES` / `CAT_TAG` / `catLabel`，且 `TextImportView.vue:68-73` 的类别数组**漏了 `custom`（自定义）**，与「语料浏览」的 6 项列表不一致 → 合并为 `web/src/constants/category.ts` 单一来源。
- 两页各有一份 `STATUS_TAG`（内容相同）→ 合并。
- 删掉「可在「导入台账」查看与撤销」的跨页指路文案，改为侧栏二级项切换。
- 「导入台账」原为手动「刷新」按钮 → 改为统一的 `usePollingJob`，任务进行中自动轮询。

### 5.6 音频素材（2 页 → 2 个二级面板）

| 二级路由 | 面板来源 | 内容 |
|---|---|---|
| `/admin/audio/upload` 上传入库 | AudioUploadView | 归属区域 + 多文件拖拽 + 逐个状态回显表 + 开始上传（同步接口，无轮询） |
| `/admin/audio/scan` 扫盘导入 | AudioImportView | 服务器路径 + 递归开关 + 归属区域 + 扫描进度 4 统计格（异步轮询） |

面板文件落 `web/src/views/admin/audio/`。

**顺带修掉的重复**：两页的「归属区域」选择器（`needDistrictPick` / `findNode` / `cityOptions` / `districtOptions` / `onCityChange` / `ownRegionName` + `api.get("/regions/tree")`）是**近乎逐字复制**的两份（`AudioUploadView.vue:14-102` vs `AudioImportView.vue:18-101`）→ 抽成 `RegionPicker.vue`（见 §6）。原两页互指的提示文案改为侧栏二级项存在本身。

### 5.7 采集记录（2 页 → 2 个二级面板）

| 二级路由 | 面板来源 | 内容 |
|---|---|---|
| `/admin/records/recording` 录音 | RecordingsView | 类别 / 质检状态 / 关键词筛选 + 表（录制人、文本、时长、大小、质检）+ 播放 / 下载 |
| `/admin/records/annotation` 标注 | AnnotationsView | 译文关键词筛选 + 表（标注人、音频文件、译文）+ 播放 / 删除 |

面板文件落 `web/src/views/admin/records/`。

### 5.8 人员与任务（2 页 → 2 个二级面板）

| 二级路由 | 面板来源 | 内容 |
|---|---|---|
| `/admin/users/people` 人员管理 | UsersView（609 行，原样迁移） | 列表 + 新增/编辑 + 重置密码 + 删除 + 导出 Excel + 批量导入向导弹窗 |
| `/admin/users/tasks` 任务管理 | TasksView | 列表 + 单人下达 / 批量下达 / 调整 / 取消 四弹窗 |

面板文件落 `web/src/views/admin/users/`。

依据：两页共用 `GET /api/admin/users`（`UsersView` 列表用、`TasksView.vue:99,140` 选人用）；`UsersView` 列表已内嵌「任务进度」列，即 `TasksView` 所管理的同一实体。**`UsersView` 的批量导入是 2 步向导（下载模板 → 上传 → 轮询明细），必须保持弹窗形态**，不摊平成二级项。

### 5.9 保持不变

`/`、`/messages`、`/admin/overview`、`/admin/message-send`、`/admin/export`、`/login`、`/register`、`/auth`。

`/admin/export` 独立的原因：它是「POST → 轮询 → 下载即焚」的异步任务生命周期，且已把录音与音频素材两源合并成一张表（`ExportListItem.source: "recording" | "audio_file"`），本身就是完成的合并形态。

---

## 6. 共享基础设施（合并的前置条件）

现状里**区域选择器复制 6 份、轮询器 5 份、Blob 下载 5 份、分类枚举 4 份**。若直接合并页面，这些副本会挤进同一组件树，出现同页多套 `setInterval` 与 `onUnmounted` 清理竞争，因此**先抽公用件，再合并页面**。

| 新增文件 | 替代 | 要点 |
|---|---|---|
| `web/src/composables/usePollingJob.ts` | 5 处独立 `setInterval`：AudioImportView(1200ms) / TextImportView(1200ms) / ExportView(1500ms) / UsersView(1000ms) / ImportManage 手动刷新 | `start(pollFn, {interval, onDone, onFail})` + `stop()`；`onUnmounted` 自动 `stop()`；路由离开时显式 `stop()` |
| `web/src/composables/useBlobDownload.ts` | 5 处 `URL.createObjectURL` + 合成 `<a>`：ExportView / RecordingsView / TextImportView(模板) / UsersView / AnnotationsView | `download(blob, filename)` 与 `playBlob(blob)`；内部统一 `revokeObjectURL` |
| `web/src/components/RegionPicker.vue` | 6 处复制：AudioUpload / AudioImport / TextImport / Export / UsersView(筛选+弹窗) / MessageSend / Overview | props：`modelValue`（到区县）、`mode: "filter" \| "required-district"`；内部自己拉 `/regions` 与 `/regions/tree`，并按 `userStore.region_code` 推导可见范围（市管锁本市、省管/超管全省、区县管理员只读本辖区） |
| `web/src/constants/category.ts` | 4 处 `CATEGORIES` / `CAT_TAG` / `catLabel` | 含 `custom`（修掉导入页漏项）；导出 `CATEGORY_OPTIONS`、`categoryLabel()`、`categoryTagClass()` |
| `web/src/constants/qc.ts` | 2 处 `QC` / `qcLabel` / `qcCls` | 录音质检状态标签与类名 |

---

## 7. 旧地址兼容

全部用 vue-router 的 `redirect`（**客户端跳转，非 HTTP 301**）：

| 旧 | 新 |
|---|---|
| `/my-recordings` | `/record/history` |
| `/my-annotations` | `/annotation/history` |
| `/record` | `/record/work` |
| `/annotation` | `/annotation/work` |
| `/admin/text-import` | `/admin/texts/import` |
| `/admin/text-import-manage` | `/admin/texts/ledger` |
| `/admin/texts`（旧文本管理） | `/admin/texts/browse` |
| `/admin/audio-upload` | `/admin/audio/upload` |
| `/admin/audio-import` | `/admin/audio/scan` |
| `/admin/recordings` | `/admin/records/recording` |
| `/admin/annotations` | `/admin/records/annotation` |
| `/admin/tasks` | `/admin/users/tasks` |
| `/admin/users`（旧用户管理） | `/admin/users/people` |

若需要真 301，须在 `nginx.conf` 增加 `location` 段——本次不做，除非另行确认。

**`?tab=` 兼容**：合并页读一次 `route.query.tab`，若命中已知取值则 `replace` 到对应二级路由，保证此前若有带 `?tab=` 的链接仍可用。

---

## 8. 风险与对策

| 风险 | 说明 | 对策 |
|---|---|---|
| 侧栏组展开状态丢失 | 刷新后所有组回到收起，用户看不到自己在哪 | `watch(route)` 命中即自动展开该组；展开状态只增不减；不做 localStorage 持久化（避免状态陈旧） |
| 父路径宽松匹配误亮 | 若二级项用 `router-link-active`，`/admin/texts/browse` 与 `/admin/texts/import` 可能同时亮 | 二级项一律依赖 `router-link-exact-active`；父组高亮由 JS 判定 `route.meta.parent` |
| 轮询器泄漏 | 合并后同页可能出现多个 `setInterval`；路由复用组件时不卸载 | `usePollingJob` 统一持有句柄；路由离开与 `onUnmounted` 都显式 `stop()`；每个页面同一时刻最多一个活动任务轮询器 |
| 分配锁被重复占用 | `RecordView.onMounted` 会 `claimText()`（占文本锁 120s），`AnnotationView.onMounted` 会 `loadNext()`（占音频锁 180s） | 预览卡**不做成 Tab**，直接作为同页卡片（本方案已如此）；`/record/work` 与 `/annotation/work` 不共享组件实例，切走即卸载并停轮询 |
| 面板文件过大 | 人员管理面板仍是 609 行 | 面板作为独立文件而非内联在父页；`UsersView` 的 4 个弹窗后续可再拆，本次不拆以控制改动面 |
| 面包屑层级 | 新增三级面包屑需要 `meta.parent` | 逐条补齐 `meta.parent` / `meta.title`；`MainLayout` 的面包屑模板从 2 段改 3 段 |
| 路由守卫与角色 | 合并页一律继承 `requiresAdmin: true`；民警端页不加 admin 限制 | 逐条核对 `meta`；加自检：遍历 `router.getRoutes()`，断言每个管理路由 `requiresAdmin === true` |
| 菜单与路由不同步 | `MainLayout.MENU` 是硬编码数组，改了路由忘了改菜单会 404 或漏显 | 同一次提交内改；加自检：菜单里每个 `to` 都必须被 `router.resolve` 命中（非 `undefined` 的 `matched`） |
| vue-tsc 零错误门槛 | 抽公用件与嵌套路由会改动大量类型签名 | 每阶段结束跑 `npm run build`（含 `vue-tsc -b`），不允许累积到最后 |

---

## 9. 实施阶段（每阶段可独立验收）

| 阶段 | 内容 | 验收 | 状态 |
|---|---|---|---|
| **P0** | 抽公用件：`usePollingJob` / `useBlobDownload` / `RegionPicker` / `category.ts` / `qc.ts`，**只做替换不做合并**（5 个轮询点、5 个下载点、6 个区域选择器、4 个分类枚举） | `npm run build` 通过；逐页手测轮询 / 下载 / 区域选择行为与改造前一致 | **已完成**（build 通过；区域选择三档权限已用真实种子账号验过，见 §9.1） |
| **P1** | **侧栏二级菜单骨架**：`theme.css` 补二级样式、`MainLayout.vue` 改树形 `MENU` + 展开逻辑 + 三级面包屑 | 侧栏层级正确、当前路由所在组自动展开、二级项高亮唯一、面包屑三段正确 | **已完成** |
| **P2** | 路由改嵌套 + 旧地址重定向 + 菜单/路由一致性自检 | 15 条旧地址全部正确落点；`npm run build` 零错误 | **已完成**（新增 `scripts/check-menu-routes.mjs`，151 项断言随 build 跑） |
| **P3** | 民警端：`/record/work` 加「历史录音」预览卡 + `/record/history`；`/annotation/work` 加「我的标注」预览卡 + `/annotation/history`（侧栏二级项名为「历史标注」） | 录制→上传→预览卡即时刷新；历史页筛选 / 播放 / 下载 / 删除全通 | 待开始 |
| **P4** | 语料管理 3 → 3 面板（含类别枚举统一、台账改自动轮询） | 三面板功能与合并前逐项对齐；批量删除 skipped 明细、撤销 409 提示均正常 | 待开始 |
| **P5** | 音频素材 2 → 2 面板 + 采集记录 2 → 2 面板 | 上传（同步）与扫盘（异步）互不干扰；切走再回来无残留定时器 | 待开始 |
| **P6** | 人员与任务 2 → 2 面板 | 批量导入向导弹窗仍为 2 步；任务四弹窗全部可用 | 待开始 |
| **P7** | 全站冒烟 + 清理 | 冒烟：登录 → 领文本录音上传 → 看质检两条路径 → 领音频标注 → 下达任务看进度 → 发消息看角标 → 批量导入开户 → 导出 ZIP | 待开始 |

**关于顺序**：P1（侧栏骨架）与 P2（嵌套路由）实际上无法拆开验收——侧栏一旦指向 `/record/work` 这类新路径，路由必须同步存在，否则点击会落到 catch-all。因此这两阶段在同一轮内完成。

### 9.1 已验证 vs 未验证（截至 P2）

**已用命令实测通过：**
- `vue-tsc -b` / `vite build` / `check-es-target.cjs` / `check-menu-routes.mjs` 全部 exit 0
- `/api/regions/tree` 根节点是 `330000 level=province`、市 `level=city`、区县 `level=district`——确认 `RegionPicker` 的 `cityOptions` 取 `province.children` 的写法与后端数据一致
- `/api/regions` 共 102 条，含 `level` / `parent_code`——确认 `ownRegion` 推导可用
- 种子账号三档权限实测：`33000000001` super_admin/province、`33100000001` admin/city、`33100400001` admin/district → 对应 `RegionPicker` 的三个分支（全省可选 / 锁本市 / 只读本辖区）
- dev server 下 16 个改动模块全部 200（SFC + TS 均能被 vite 转译）
- SPA 深链 `/admin/texts/import` 返回 200（history fallback 正常）

**尚未验证（需人工在浏览器点）：**
- 侧栏二级菜单的实际展开/收起动画、当前组自动展开与高亮、三段面包屑渲染
- 各页轮询 / 下载 / 拖拽上传的交互行为
- 响应式断点（`theme.css` 里 232px 侧栏在窄屏的表现）

（说明：本会话环境无法驱动浏览器点击，上述交互项只能由人工确认。）


---

## 10. 明确不在本次范围

1. `dome/` 静态设计稿及其 `assets/theme.css` 副本。
2. `GET /api/annotations/my` 增加服务端筛选，以及把 `page_size=10000` 改为服务端分页（后端改造，建议另开一项；预览卡只取 5 条不受影响）。
3. `/admin/text-import-manage` 与 `/admin/export/audio-list` 的**内存分页**（`text_import.py:191-204`、`export.py:132-135` 全量载入再切片）——API 兼容但不可扩展，属后端性能项。
4. 侧边栏折叠为纯图标模式（rail）——二级菜单与纯图标模式冲突，本次不做。
5. nginx 真 301 重定向。

---

## 11. 已确认决策（原待确认项）

| 议题 | 决策 |
|---|---|
| 侧边栏形态 | **二级菜单**：分组标题 + 可展开组 + 二级项；页面内部**不再套 Tab**（由侧栏二层切换） |
| 民警端层级 | **二级**：录音采集 → 开始录音 / 历史录音；录音标注 → 开始标注 / 历史标注 |
| 二级项命名 | 已定：`开始录音` / `历史录音`、`开始标注` / `历史标注`（两组下首项不同名，避免看错组） |
| 合并力度 | 管理工作 12 项 → 7 项；全站侧栏可见行 19 → **11**（4 组 + 7 直接项） |
| 历史记录呈现 | 作业页底部**最近 5 条只读预览卡** + 「查看全部 →」跳独立历史页 |
| **P0 是否先行** | **先行**。理由见下方 §11.1 |
| dome/ 静态稿 | 不动，保持存档一致 |
| 旧地址 | 客户端重定向（非 HTTP 301） |

### 11.1 P0 到底在做什么（白话版）

**问题**：现在有 6 个页面各自抄了一份「选地市 + 选区县」的下拉框代码，5 个页面各自抄了一份「定时轮询后台任务进度」的代码，5 个页面各自抄了一份「把文件下载到本地」的代码，4 个页面各自抄了一份「警情/生活/俚语/地名/自定义」这张对照表。

抄 6 遍的坏处是：改一处要改 6 处（现在「文本导入」页的类别表就漏了「自定义」，跟别的页不一致），而且合并页面时这些副本会挤进同一个文件里。

**P0 做的事**：把这 4 类东西各抽成**一份**公用件，然后让原来抄的那 19 个地方改成调用公用件。

**P0 明确不做**：不合并页面、不改路由、不动侧边栏、不改任何界面长相。界面看起来跟改之前**完全一样**，只是代码里少了一堆重复。

**为什么值得单独一轮**：改完之后界面必须和之前一模一样，所以验收很简单——把有轮询/下载/选区域的页面点一遍，行为没变就算过。如果把它和页面合并混在一轮做，出了问题分不清是「抽公用件抽错了」还是「页面合并合错了」。

**P0 抽完的 5 个公用件**：

| 公用件 | 抽掉的是哪几份重复 |
|---|---|
| `usePollingJob.ts` | 音频扫盘进度、文本导入进度、导出打包进度、用户批量导入进度，4 个各自的 `setInterval` |
| `useBlobDownload.ts` | 导出 ZIP 下载、录音下载、模板下载、用户 Excel 导出、标注音频播放，5 份 `URL.createObjectURL` + 造 `<a>` 标签 |
| `RegionPicker.vue` | 音频上传、音频扫盘、文本导入、数据集导出、用户管理（筛选 + 弹窗各一处）、消息发送、数据总览，6~7 份拷贝 |
| `constants/category.ts` | 录音管理、文本管理、导入台账、数据集导出，4 份类别对照表（含修掉导入页漏「自定义」） |
| `constants/qc.ts` | 录音管理、我的录音，2 份质检状态对照表 |

### 11.2 仍需你确认的两点

1. **合并页 URL 命名**：`/admin/texts/{browse,import,ledger}`、`/admin/audio/{upload,scan}`、`/admin/records/{recording,annotation}`、`/admin/users/{people,tasks}` 是否合适？
2. **侧栏二级项命名**（管理工作）：`语料浏览 / 批量导入 / 导入台账`、`上传入库 / 扫盘导入`、`录音 / 标注`、`人员管理 / 任务管理` —— 有没有更贴合你们日常叫法的词？（例如「录音 / 标注」是否该叫「录音记录 / 标注记录」）

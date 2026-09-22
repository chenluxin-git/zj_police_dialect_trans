# 浙江公安方言语料采集平台（zj_police_dialect_trans）设计文档

- 日期：2026-09-21
- 状态：已与需求方逐节确认
- 前身：台州/省方言语料收集平台（`audio-server-test` + `recorder-ui/my-app`），本文档所述为新独立项目

## 1. 背景与目标

现有省方言语料平台功能多线（采集/标注/修正/学习/词典），本次立项将其裁剪重写为**面向浙江公安全体民警**的语料采集平台：

- 只保留两条核心作业线：**录音采集、录音标注**
- 新增**任务管理**：管理员给民警个人下达录音/标注数量指标，用户可见进度
- 新增**站内消息**：管理员可发消息通知对应用户，任务下达自动通知
- 用户规模从演示级升至万人级（全省 11 地市）
- 空库起步，不迁移现有省平台数据；现有省平台继续独立运行

## 2. 需求决策记录

| 决策点 | 结论 |
|---|---|
| 功能范围 | 保留录音采集、录音标注；保留文本管理、音频导入、注册登录、数据集导出、数据总览（加任务维度）；砍转译修正、方言学习、方言词典、便捷版匿名登录 |
| 层级划分 | 管理权限层级：省→市→区县三级管理员 + 超级管理员（看所有、操作所有） |
| 任务指标 | 录音数 + 标注数两类独立下达；直接下达到个人（可批量）；一次性总任务 |
| 开户方式 | 自注册 + 管理员 Excel 批量导入 |
| 实施路径 | 新项目重写，沿用 FastAPI + Vue3 技术栈 |
| 数据策略 | 空库起步，预置 seed 账号 |
| 录音质检 | 上传后**异步**送方言转译接口比对：相似度 ≥ 50% 通过；< 50% 判不合格，删除录音与音频文件并站内消息通知重录；全程留质检日志 |
| 项目目录 | `E:\project\record-web-test\zj_police_dialect_trans\` |

## 3. 总体架构与目录

```
zj_police_dialect_trans/
├── server/                     # FastAPI 后端
│   ├── app/
│   │   ├── main.py             # 入口：CORS、路由注册、日志、startup 建表+seed
│   │   ├── api/                # 用户侧路由
│   │   │   ├── auth.py         # 注册/登录/me
│   │   │   ├── texts.py        # 文本分配（2分钟锁）
│   │   │   ├── recordings.py   # 录音上传（ffmpeg 转 WAV）
│   │   │   ├── annotations.py  # 标注作业（3分钟锁）
│   │   │   ├── audio_files.py  # 标注音频流
│   │   │   ├── base.py         # 基础数据（regions/dialects/police_stations）
│   │   │   ├── tasks.py        # 我的任务与进度
│   │   │   └── messages.py     # 站内消息（列表/未读/已读）
│   │   ├── api/admin/          # 管理端路由
│   │   │   ├── users.py        # 用户管理 + 批量导入 + Excel 导出
│   │   │   ├── texts.py        # 文本管理
│   │   │   ├── text_import.py  # 文本导入（后台任务）
│   │   │   ├── recordings.py   # 录音管理
│   │   │   ├── annotations.py  # 标注管理
│   │   │   ├── audio_upload.py # 音频上传
│   │   │   ├── audio_import.py # 音频扫盘导入
│   │   │   ├── stats.py        # 数据总览（含任务维度）
│   │   │   ├── tasks.py        # 任务下达/调整/取消/批量
│   │   │   ├── messages.py     # 消息发送
│   │   │   └── export.py       # 数据集导出
│   │   ├── core/               # config / database / security
│   │   ├── services/
│   │   │   └── qc.py           # 录音异步质检：调转译接口、算相似度、剔除+通知
│   │   ├── models/             # ORM 模型
│   │   ├── schemas/            # Pydantic 模型
│   │   ├── utils/              # file_scanner / seed
│   │   └── deps.py             # 认证与 resolve_scope
│   ├── Dockerfile              # python3.10 + ffmpeg
│   ├── requirements.txt
│   └── .env / .env.docker
├── web/                        # Vue3 前端
│   ├── src/
│   │   ├── views/              # 页面（见 §8）
│   │   ├── api/                # API 封装
│   │   ├── router/             # 路由与守卫
│   │   ├── stores/             # Pinia（user + message 未读数）
│   │   └── components/         # Recorder / AudioPlayer
│   ├── Dockerfile / nginx.conf # node20 构建 → nginx 443 反代
│   └── package.json / vite.config.ts
├── deploy/                     # 部署脚本（后续阶段补充）
└── docs/                       # 本文档等
```

- 后端：Python 3.10 + FastAPI + SQLAlchemy 2.0 + JWT（python-jose）+ passlib/bcrypt
- 音频：浏览器 MediaRecorder（webm/opus）→ 服务端 ffmpeg 转 pcm_s16le/16kHz/单声道 WAV，asyncio.Semaphore(2) 限流；ffprobe 取时长
- 前端：Vue 3.5 + TypeScript + Element Plus + Vite + Pinia + axios
- 数据库：ORM 层双兼容，**默认 SQLite**（两容器形态，沿用省平台气隙部署经验），MySQL 8 可配
- 部署：docker-compose 两容器 = nginx(前端 443 自签 HTTPS、反代 /api/ → backend:8000) + backend(含 ffmpeg、SQLite)。浏览器麦克风要求安全上下文，HTTPS 必须保留
- 日志：TimedRotatingFileHandler，logs/app.log（INFO）+ logs/error.log（ERROR），每日轮转留 30 天

## 4. 角色与层级权限模型

### 4.1 角色

| role | 说明 | 管辖范围 |
|---|---|---|
| `user` | 民警 | 仅本人数据（录音、标注、任务、消息） |
| `admin`（归属省节点） | 省级管理员 | 全省 |
| `admin`（归属地市） | 市级管理员 | 本市 + 下属区县 |
| `admin`（归属区县） | 区县管理员 | 本区县 |
| `super_admin` | 超级管理员 | 不受区域限制，看所有、操作所有 |

- 管理员三级**不新增角色枚举**，由 admin 归属的 `region_code` 层级推导
- super_admin 为内置高权限角色：跨区域查看与编辑/删除、管理各级管理员账号、给任意辖区用户下达任务

### 4.2 resolve_scope

`deps.resolve_scope(user) -> list[str] | None`，统一数据权限入口：

- `super_admin` → `None`（不过滤）
- `admin` 归属 level=province → `None`（不过滤，与超管等效全省）
- `admin` 归属 level=city → [市码] + 全部下属 district 码
- `admin` 归属 level=district → [本县码]
- `user` → 不按区域，按 user_id 过滤

所有管理端列表/删除/导出/任务/消息群发均以 scope 过滤，替代旧项目的 if-else 权限分支。

## 5. 数据模型

### 5.1 表清单（17 张）

**沿用改造（字段与旧项目一致或裁剪）**

| 表 | 关键字段 | 说明 |
|---|---|---|
| users | phone(唯一)、password_hash、real_name、police_station、region_code、role(user/admin/super_admin)、import_batch_id(可空)、created_at | |
| regions | code(PK)、name、level(province/city/district)、parent_code、sort_order | 新增 province 级根节点 330000 |
| dialects | code、name、region_code、parent_code、description | |
| police_stations | code、name、region_code、sort_order | |
| texts | content、dialect、category(police/life/dirty/place/custom)、region_code、dialect_code、created_at | |
| text_assignments | text_id(唯一)、user_id、assigned_at | 2 分钟超时，惰性回收 |
| recordings | user_id、text_id、file_path、file_size、duration、region_code、dialect_code、qc_status(pending/passed)、created_at、unique(user_id,text_id) | 上传即入库 pending，质检通过置 passed；不合格记录被删除（unique 解除，同文本可重录） |
| audio_files | file_path(唯一)、file_name、duration、region_code、dialect_code、created_at | |
| file_assignments | file_id(唯一)、user_id、assigned_at | 3 分钟超时，惰性回收 |
| annotations | file_id(唯一)、annotator_id、is_dialect、translation、region_code、created_at、updated_at | 一条音频一条标注 |
| export_tasks | status、total_count、processed_count、file_path、created_by、created_at | ZIP 导出台账 |
| import_tasks | status、error_message、created_at | 文本导入后台任务台账，前端轮询 |

**新增**

| 表 | 关键字段 | 说明 |
|---|---|---|
| tasks | user_id、type(recording/annotation)、target_count、base_count、status(active/cancelled)、note、created_by、created_at、updated_at | 一次性总任务 |
| messages | title、content、sender_id、created_at | 站内消息 |
| message_recipients | message_id、user_id、read_at(空=未读)、unique(message_id,user_id) | 收件与已读 |
| user_import_batches | file_name、total、success、fail、detail(文本)、created_by、created_at | 批量开户台账 |
| qc_logs | recording_id、user_id、text_id、text_content、asr_text、similarity、result(passed/failed/error)、error_message、created_at | 质检留痕：录音删除后仍可追溯，不存音频 |

**不迁移/不建**：correction_segments、correction_assignments、user_learned_audios、text_import_tasks（文本导入统一走 import_tasks 台账）、SIMPLE_ 便捷版相关。

### 5.2 任务进度口径

- 进度 = 当前有效数 − base_count，**实时统计不记流水**：
  - recording：`COUNT(recordings WHERE user_id=X AND qc_status='passed')` − base_count（**待质检不计入**，质检剔除自动回退，无需额外处理）
  - annotation：`COUNT(annotations WHERE annotator_id=X)` − base_count
- base_count 为**下达时刻的存量快照**：防止重下达时"瞬间完成"，删除录音/标注自动回退
- 进度下限显示 0，超额如实显示（如 102/100），达线即视为完成
- 一人一类型只允许一条 `status=active` 任务；重复下达 = 调整 target_count 与 note，base_count 不变

### 5.3 seed 预置数据

- 基础数据：regions（1 省 + 11 市 + 90 区县）、dialects、police_stations（从旧省库导出净化生成 seed 脚本）
- **预置账号，密码统一 `123456`**，账号规则 = 6 位区域码 + 5 位序号（11 位，兼容手机号格式）：

| 预置 | 数量 | 账号示例 | 归属/角色 |
|---|---|---|---|
| 超级管理员 | 1 | 33000000001 | 省节点 / super_admin |
| 市级管理员 | 11（每市 1 个） | 33010000001 | 市节点 / admin |
| 区县管理员 | 90（每县 1 个） | 33100400001 | 县节点 / admin |
| 普通民警 | 180（每县 2 个） | 33100400002、33100400003 | 县节点 / user |

合计 282 个，姓名规则如"省超管""杭州管理员""临海管理员""临海民警01"。startup 时幂等 seed（存在即跳过）。

## 6. 核心功能设计

### 6.1 录音采集（沿用旧逻辑）
领文本（本区/空区匹配、2 分钟分配锁、过期物理删除、可续期/放弃/自定义）→ 浏览器 MediaRecorder 录音 → 上传 → ffmpeg 转 WAV → 落盘 `AUDIO_STORAGE_PATH/{姓名}_{手机尾4}/{recording_id}.wav` → 删分配 → 入库 `qc_status=pending`，进入异步质检（见 6.2）。页面顶部叠加**我的录音任务进度条**。

### 6.2 录音质检（新增）
- **触发**：录音上传入库后，后台任务在一段时间内（如 5 分钟内）将 WAV 提交**方言转译接口**（外部 HTTP 服务，同步返回转写文本）
- **比对**：接口返回文本与 `texts.content` 计算**字符级相似度** = 1 − Levenshtein 编辑距离 / 较长者长度；阈值 **50%**（配置项）
- **结果处理**：
  - 相似度 ≥ 50%：`qc_status→passed`，正式生效并计入任务进度
  - 相似度 < 50%：判不合格 → **删除录音记录与音频文件**（unique 解除，同文本可重录）→ 站内消息通知本人（含文本、相似度，要求重录）
  - 接口超时/异常：`qc_status` 保持 pending，qc_logs 记 `error`，按退避重试；累计失败进 error.log 告警人工处理，**不因接口故障误删录音**
- **留痕**：qc_logs 全量记录 passed/failed/error（文本、转写结果、相似度），录音删除后仍可追溯
- **配置**（.env）：`ASR_API_URL`、`ASR_TIMEOUT`、`QC_SIMILARITY_THRESHOLD=0.5`、`QC_MAX_RETRY`；接口不可用时可通过配置整体停用质检（pending 直接置 passed，保证采集不中断）
- 前端表现：录音采集页上传后提示「已提交质检」；我的录音列表加质检状态列（待质检/已通过，不合格记录已删除不在列表）

### 6.3 录音标注（沿用旧逻辑）
随机领取未标注音频（区域隔离、3 分钟锁）→ 判定是否方言 + 普通话翻译（方言必填译文）→ 提交。我的标注可改可删。页面顶部叠加**我的标注任务进度条**。

### 6.4 任务管理（新增）
- 管理端：
  - 辖区任务列表：姓名/单位/类型/状态筛选，行内显示 目标/完成/进度条（scope 过滤）
  - 单人下达：选用户 + 类型（录音/标注）+ 数量 + 备注；可同时下两类
  - 批量下达：多选用户 + 类型 + 数量
  - 调整：改 target_count/note；取消：status→cancelled
  - 下达与批量下达**自动发站内消息**通知每个被下达人
- 用户端：`GET /api/tasks/my` 返回两类任务及进度；首页任务卡 + 两个作业页顶部进度条
- 权限：admin 只能给 scope 内用户下达；super_admin 任意

### 6.5 站内消息（新增）
- 管理员发送：收件人 = 单人（scope 内搜索选择）/ 按区域群发（scope 内某区域全部用户）/ 按单位群发（选派出所）
- 用户端：消息列表（标题、时间、已读态）、详情（打开即标已读）、未读数
- 未读数获取：路由切换时刷新 + 每 30 秒轮询 `GET /api/messages/unread-count`，菜单/顶栏角标显示；**不上 WebSocket**
- 自动消息：任务下达、批量任务下达触发（title=「新任务」，content 含类型与数量）；**录音质检未通过触发**（title=「录音质检未通过」，content 含文本、相似度与重录指引）

### 6.6 用户管理与批量开户
- 列表：姓名/手机号/角色/区域/单位筛选 + 录音数/标注数/任务进度列，Excel 导出（沿用旧 openpyxl 报表模式）
- 增删改：创建用户、编辑（姓名/区域/单位/角色/重置密码）、删除（有录音禁删）；super_admin 可管理管理员账号，admin 仅 scope 内且不可创建/修改 super_admin
- **批量导入**：Excel 模板（手机号/姓名/区域码/单位/角色）→ 逐行校验（手机号查重与格式、区域/单位/角色合法性）→ 有效行入库（初始密码=手机号后 6 位）→ 返回成功/失败明细并记台账；后台任务 + 轮询

### 6.7 数据总览（改造）
沿用旧地市→区县两级聚合（用户数/录音数/时长/容量/文本数/音频数/已标注数/方言判定数），**录音数仅计质检通过**；**新增任务维度**：辖区任务完成率、已启动/未启动人数。super_admin 可选省/市/县，admin 固定 scope。

### 6.8 数据集导出（沿用）
两源合并清单（recordings（仅质检通过）+ 已判方言 audio_files）→ 按条件全量或勾选 → 后台 ZIP（音频 + dataset.txt 清单）→ 下载后即焚。逐条区域权限校验。

### 6.9 文本管理与音频导入（沿用）
- 文本：txt/docx 导入（按句号切分、后台任务、模板下载）、导入台账与撤销、列表筛选、批量删除（被录音引用禁删）
- 音频：单文件上传（UUID 重命名 + ffprobe 时长）+ 服务器文件夹扫盘（7 种扩展名、file_path 去重）；区域随管理员归属，super_admin 可指定

## 7. API 端点清单

**用户侧（/api）**
- POST /auth/register、POST /auth/login、GET /auth/me
- POST /texts/assign、POST /texts/assign/{id}/refresh、DELETE /texts/assign/{id}、DELETE /texts/assign/expired、POST /texts/custom
- GET/POST /recordings、GET /recordings/{id}/file、DELETE /recordings/{id}
- GET /annotations/next、POST /annotations、GET /annotations/my、GET /annotations/my/dialect-count、PUT/DELETE /annotations/{id}、POST /annotations/assign/{fid}/refresh、DELETE /annotations/assign/expired
- GET /audio/files/{id}/file
- GET /regions、GET /regions/tree、GET /dialects、GET /dialects/by-region/{code}、GET /police_stations、GET /police_stations/by-region/{code}
- GET /tasks/my
- GET /messages、GET /messages/unread-count、GET /messages/{id}（详情并标已读）

**管理侧（/api/admin）**
- GET/POST /users、PUT/DELETE /users/{id}、GET /users/export、POST /users/import、GET /users/import/{batch_id}、GET /users/import-template
- GET /texts、DELETE /texts/batch；POST /texts/import、GET /texts/import/{task_id}、GET /texts/template/{fmt}；GET/DELETE /text-import-manage/{id}
- GET /recordings；GET /annotations、DELETE /annotations/{id}
- POST /audio/upload、POST /audio/import
- GET /stats/overview
- GET /tasks、POST /tasks、POST /tasks/batch、PUT /tasks/{id}
- POST /messages、GET /messages（已发列表）
- GET /export/audio-list、POST /export/audio、POST /export/audio-all、GET /export/task/{id}、GET /export/download/{id}

## 8. 前端页面与路由

| 路由 | 页面 | 角色 |
|---|---|---|
| /login、/register | 登录、注册 | 公开 |
| / | 首页：任务卡 + 功能入口 | user+ |
| /record | 录音采集（含任务进度条、上传后质检提示） | user+ |
| /my-recordings | 我的录音（含质检状态列） | user+ |
| /annotation | 录音标注（含任务进度条） | user+ |
| /my-annotations | 我的标注 | user+ |
| /messages | 我的消息（未读角标） | user+ |
| /admin/overview | 数据总览（含任务维度） | admin+ |
| /admin/tasks | 任务管理 | admin+ |
| /admin/users | 用户管理（批量导入/导出） | admin+ |
| /admin/message-send | 消息发送 | admin+ |
| /admin/text-import | 文本导入 | admin+ |
| /admin/text-import-manage | 导入台账 | admin+ |
| /admin/texts | 文本管理 | admin+ |
| /admin/recordings | 录音管理 | admin+ |
| /admin/annotations | 标注管理 | admin+ |
| /admin/audio-upload | 音频上传 | admin+ |
| /admin/audio-import | 音频扫盘 | admin+ |
| /admin/export | 数据集导出 | admin+ |

菜单按角色渲染：普通民警仅显示「日常工作」（首页/录音采集/我的录音/录音标注/我的标注）与「消息」（我的消息）；admin/super_admin 追加「管理工作」分组（12 项），数据权限由后端 scope 控制。路由守卫：未登录跳 /login，非 admin 访问 /admin/* 拦截。

## 9. 沿用旧项目的成熟机制

分配锁（文本 2 分钟/音频 3 分钟惰性回收）；ffmpeg 并发信号量(2)；后台任务 + 台账轮询；导出 ZIP（ZIP_STORED）下载后即焚；删除录音/标注联动删盘上文件；被录音引用文本禁删；删除用户前校验有无录音；全站单声道播放（audioManager，新播放自动停上一个）；JWT Bearer；自签 HTTPS；CORS 白名单。

## 10. 测试策略

- pytest 覆盖纯逻辑核心：`resolve_scope` 四类推导、任务进度口径（base_count 快照/删除回退/超额/重复下达调整/**待质检不计入**）、分配锁超时回收、消息已读与未读计数、**质检相似度计算与阈值边界、接口异常容错（error 不剔除不误删、停用质检直通）**
- 前端：vue-tsc 零错误构建
- 人工冒烟清单：注册登录 → 领文本录音上传 → **看质检通过/未通过两条路径（未通过收到重录消息、同文本可重录）** → 领音频标注 → 下达任务看进度 → 发消息看角标 → 批量导入开户 → 导出 ZIP

## 11. 明确不做（Out of Scope）

转译修正整线、方言学习、方言词典、便捷版匿名登录、WebSocket 实时推送、周期性循环任务、任务截止日期、首次登录强制改密、方言转译接口本身的建设（外部系统提供，本项目仅调用并比对）、现有省平台数据迁移（如未来需要另立项）。
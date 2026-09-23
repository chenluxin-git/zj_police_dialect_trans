# L2 分发指令（8 包，2026-09-22）

- 用途：每段整块复制，粘贴给一个**新的 AI 会话**（一包一会话）。
- 埍线状态（L1 已全部合并）：
  - 后端 `feature/zj-police-dialect-trans` @ c1d2eca —— 已含 auth/base/texts/recordings/tasks/messages/annotations/audio_files/admin-export 全部路由 + seed 282 账号 + 冒烟通过（79+1 用例绿）
  - 前端 `feature/zj-police-dialect-web` @ 482209e —— 已含骨架/路由守卫/stores/MainLayout/全部占位页，build 绿
- 合并回基线由主会话/用户执行，各包 AI 只在自己分支提交。

## 后端四包公共事实（写进各自指令，勿重复造）

- 基线已有可直接导入（只导入不修改）：
  - `from app.schemas import ok`——统一信封 `{code:0,msg:"",data}`，端点 `return ok(x)`
  - `from app.api.deps import get_current_user, require_admin, resolve_scope, scope_filter`
  - `from app.services.task_progress import progress_map`（`progress_map(db, user_ids)->dict[int,dict[str,int]]`，recording 只计 passed）
  - `from app.services.messaging import send_message`（`send_message(db, user_ids, title, content, sender_id=None)`）
  - `from .api.recordings import convert_to_wav, _ffmpeg_sem`（P-admin-content 用）
- `app/api/admin/__init__.py` 已存在（P-export 建）——只追加 import 行，不重构
- `app/services/__init__.py` 已存在（P-social 建）
- conftest `auth_header` fixture 硬编码用户 id=1：**多用户测试必须显式 `create_token(str(user.id))`**
- seed（run_seed） bcrypt 282 账号约 70 秒：测试优先自造 region/user 数据，勿随意 run_seed
- main.py 冲突经验：路由注册位各家追加自己的行，保留既有全部行

---

## 1. P-qc（T9）——前置 P-social 已合并 ✓

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-qc（计划任务 T9）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T9 全文（含 qc.py 完整参考实现）
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md §6.2
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-qc 一节
2. 建工作区（在 e:\project\record-web-test 根执行）：git worktree add .worktrees/p-qc -b feature/zjpdt-p-qc feature/zj-police-dialect-trans（目录已存在则直接进入）
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 则用任意 Python 3.10–3.12，禁 3.13）
4. TDD 实现任务 T9：7 个用例照计划 T9 Step 1，先失败再实现；既有 80 用例保持全绿（.venv/Scripts/python -m pytest tests -v）
5. 硬边界：只创建/修改本包独占文件：server/app/services/qc.py、server/tests/test_qc.py；server/app/main.py 仅允许两处改动——路由注册位追加（如有）、startup 钩子改为 async def 并追加 asyncio.create_task(qc_loop())；不改 conftest.py 与他人文件；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点（裁定与集成提醒）：
- 依赖已就位：from .messaging import send_message（基线已有，签名勿偏）
- 停用直通用例：monkeypatch.setattr("app.core.config.settings.asr_api_url", "")（settings 导入时已实例化，改 os.environ 无效）
- ⚠️ 已知坑：qc.process_pending 内部用 app.core.database.SessionLocal，与 conftest 的 db fixture 不是同一 engine（数据不互通）。测试需 monkeypatch app.services.qc.SessionLocal 指向测试 Session（如 monkeypatch.setattr("app.services.qc.SessionLocal", TestingSession)，从 tests.conftest import TestingSession），确保用例真实走数据
- 相似度：normalize 去标点小写 → Levenshtein/max(len) ；≥0.5 passed、<0.5 删录音+删文件+send_message、接口异常记 error 留 pending 不误删、error 计数≥QC_MAX_RETRY(3) 跳过、ASR_API_URL 空=直通 passed 且不写 qc_logs
```

## 2. P-admin-users（T14+T15）——前置 P-social 已合并 ✓

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-admin-users（计划任务 T14+T15）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T14、T15 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md §6.6
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-admin-users 一节
2. 建工作区：git worktree add .worktrees/p-admin-users -b feature/zjpdt-p-admin-users feature/zj-police-dialect-trans
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests
4. TDD 实现任务 T14+T15：先失败测试再实现；既有 80 用例保持全绿
5. 硬边界：只创建/修改本包独占文件：server/app/api/admin/{users,user_import}.py、server/app/schemas/admin.py、server/tests/{test_admin_users,test_admin_user_import}.py；server/app/api/admin/__init__.py 只追加 import；server/app/main.py 仅追加 include_router 行；不改 conftest.py 与他人文件；禁止 git add -A / push / rebase
6. 按任务内示例提交。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点：
- 依赖已就位：from app.services.task_progress import progress_map（列表任务进度列）
- 权限规则（Spec §6.6）：admin 仅 scope 内用户可操作；admin 不可创建/修改/删除 super_admin（403）；有录音用户禁删（400）；创建/导入初始密码=手机号后 6 位
- 导入：xlsx 模板下载 + 后台 threading.Thread 逐行校验（手机号 ^\d{11}$ 且查重/区域码存在/角色 ∈ user,admin）+ UserImportBatch 台账轮询；detail 存 JSON 文本
- 信封：from app.schemas import ok
```

## 3. P-admin-content（T16+T17+T19）——前置 P-media 已合并 ✓

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-admin-content（计划任务 T16+T17+T19）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T16、T17、T19 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md 对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-admin-content 一节
2. 建工作区：git worktree add .worktrees/p-admin-content -b feature/zjpdt-p-admin-content feature/zj-police-dialect-trans
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests
4. TDD 实现任务 T16+T17+T19：先失败测试再实现；既有 80 用例保持全绿。涉 ffmpeg 用例在宿主机可用（勿 skip）
5. 硬边界：只创建/修改本包独占文件：server/app/api/admin/{texts,text_import,audio_upload,audio_import}.py、server/app/utils/file_scanner.py、server/tests/{test_admin_texts,test_admin_text_import,test_admin_audio}.py；server/app/api/admin/__init__.py 只追加 import；server/app/main.py 仅追加 include_router 行；不改 conftest.py 与他人文件；禁止 git add -A / push / rebase
6. 按任务内示例提交。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点：
- 依赖已就位：from ..api.recordings import convert_to_wav, _ffmpeg_sem（复用转码与信号量）
- 文本管理：scope 列表 + 批量删除跳过被 recordings 引用项并回显 {deleted, skipped}
- 文本导入：txt 按行 / docx 按段落，句号切分去空白去重；ImportTask 台账轮询；撤销删本批次未引用文本、被引用 409 拒撤
- 音频双通道：多文件上传（UUID 重命名 + convert_to_wav + ffprobe 时长）；扫盘（7 扩展名 wav/mp3/m4a/wma/amr/aac/ogg、绝对路径去重跳过、递归）；region_code=管理员归属，super_admin 可传参指定
- 信封：from app.schemas import ok
```

## 4. P-admin-data（T18+T20+T21+T22）——前置 P-social 已合并 ✓

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-admin-data（计划任务 T18+T20+T21+T22）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T18、T20、T21、T22 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md §6.7 与对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-admin-data 一节
2. 建工作区：git worktree add .worktrees/p-admin-data -b feature/zjpdt-p-admin-data feature/zj-police-dialect-trans
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests
4. TDD 实现任务 T18+T20+T21+T22：先失败测试再实现；既有 80 用例保持全绿
5. 硬边界：只创建/修改本包独占文件：server/app/api/admin/{recordings,annotations,stats,tasks,messages}.py、server/tests/test_admin_manage.py、server/tests/{test_admin_stats,test_admin_tasks,test_admin_messages}.py；server/app/api/admin/__init__.py 只追加 import；server/app/main.py 仅追加 include_router 行；**不改 server/app/api/recordings.py**（admin 听录音已由该端点放行：本人或 require_admin 且 region ∈ scope）；不改 conftest.py 与他人文件；禁止 git add -A / push / rebase
6. 按任务内示例提交。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点：
- 依赖已就位：progress_map（列表进度列与 T20 任务维度）、send_message（T21 下达自动消息、T22 由基线 messaging 承载）
- T20 数据总览：省→市→县下钻两级聚合，每区域一次 GROUP BY region_code 查询再分桶（勿逐区域循环查库）；录音数/时长/容量仅 qc_status='passed'；响应额外带 category_counts（scope 内 texts 按 category 聚合的 {category: count}，FE-4 类别分布条形图需要——集成裁定：本字段由本包一次做齐，FE 包不再改后端）
- T21 任务管理：下达规则（scope 校验 403/重复下达调 target 保 base/取消后重下重拍快照）、每次成功下达 send_message(uid,"新任务",...)
- T22 消息发送：单人/区域/单位三口径一律 ∩ scope，越界忽略回 sent/skipped
- 信封：from app.schemas import ok
```

---

## 前端四包公共事实（FE-2..5）

- 基线 `feature/zj-police-dialect-web` @ 482209e（worktree .worktrees/web）已含：src/api/{http,messages}.ts、router 19 路由+守卫、stores/{user,message,audio}.ts、layouts/MainLayout.vue、styles/theme.css、全部 views 占位页
- **api 文件归属**（一包一文件，避免冲突）：auth.ts→FE-2；texts/recordings/annotations/tasks.ts→FE-3；admin/{stats,tasks,users,messages}.ts→FE-4；admin/{texts,export}.ts→FE-5。messages.ts 已存在（FE-1 产）——需要时只追加函数不改既有
- views 只替换自己的占位文件；不改 router/http.ts/stores/MainLayout（FE-1 产出）
- 视觉规格：zj_police_dialect_trans/dome/*.html 1:1 还原到 Element Plus（theme.css 设计 token 已建）
- 每个工作区自装依赖：cd zj_police_dialect_trans/web && npm install（失败重试 --registry=https://registry.npmmirror.com）
- 验证：npm run build（vue-tsc 零错误）

## 5. FE-2（T26+T27+T31）登录/注册/首页/我的消息

```
你是"浙江公安方言语料采集平台"的前端开发，独立完成任务包 FE-2（计划任务 T26+T27+T31）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T26、T27、T31 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md §8
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md §4 的 FE-2 一节
   - 视觉规格 dome/login.html、register.html、home.html、messages.html（只读，1:1 还原）
2. 建工作区：git worktree add .worktrees/web-2 -b feature/zjpdt-fe2 feature/zj-police-dialect-web
3. 依赖：cd zj_police_dialect_trans/web && npm install（失败重试 --registry=https://registry.npmmirror.com）
4. 实现（独占=替换占位）：src/views/{LoginView,RegisterView,HomeView,MessagesView}.vue、src/api/auth.ts（messages.ts 已存在只追加函数）
   - 登录 55/45 藏青品牌分栏（dome/login.html），POST /auth/login 存 token → fetchMe → 按角色跳 /
   - 注册三级区域级联（GET /regions/tree el-cascader）+ 派出所联动（/police_stations/by-region/{code}）+ POST /auth/register 成功回登录页
   - 首页任务双卡（GET /tasks/my，录音卡副注「质检通过后计入」）+ 5 快捷入口 + 最近录音/最新消息双卡 + admin 管理入口卡
   - 消息三 tab（全部/未读/已读）、四类 tag 按 title 前缀映射（「新任务」navy/「录音质检未通过」danger/「公告」gold/其余 blue）、详情打开即已读联动角标、「全部已读」调 POST /messages/read-all（后端已就位）
5. 验证与硬边界：npm run build 零错误；只改本包文件；不改 router/http.ts/stores/MainLayout；dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息）。完成后输出简报：文件清单 / build 输出 / 偏差说明
```

## 6. FE-3（T28+T29+T30）录音采集/我的录音/标注两页

```
你是"浙江公安方言语料采集平台"的前端开发，独立完成任务包 FE-3（计划任务 T28+T29+T30）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T28、T29、T30 全文
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md §4 的 FE-3 一节
   - 视觉规格 dome/record.html、my-recordings.html、annotation.html、my-annotations.html（只读，1:1 还原）
2. 建工作区：git worktree add .worktrees/web-3 -b feature/zjpdt-fe3 feature/zj-police-dialect-web
3. 依赖：cd zj_police_dialect_trans/web && npm install（失败重试 --registry=https://registry.npmmirror.com）
4. 实现（独占=替换占位）：
   - src/views/{RecordView,MyRecordingsView,AnnotationView,MyAnnotationsView}.vue、src/components/{Recorder,AudioPlayer}.vue、src/api/{texts,recordings,annotations,tasks}.ts（4 个文件归本包）
   - Recorder：MediaRecorder，mimeType 择优 "audio/webm;codecs=opus"→"audio/webm"→"audio/mp4"；props {disabled} emits start/stop(blob,seconds)；计时 setInterval；波形纯 CSS（照抄 dome .zp-wave.is-live）；getUserMedia 失败 ElMessage 指引（非 HTTPS/拒权）
   - 录音页：120s 分配倒计时（remaining_seconds）超时自动释放、「换一条」、自定义文本 dialog（POST /texts/custom）、上传 POST /recordings FormData 成功提示「已提交质检，通过后计入任务进度」自动领下一条
   - 我的录音：类别/质检状态/搜索筛选，质检列 待质检 warn/已通过 success 双色 tag，试听走 useAudioStore、下载 blob、删除确认文案含「任务进度将相应扣减」
   - 标注页：GET /annotations/next 领音频、AudioPlayer（useAudioStore.play 单声道）+ 180s 锁倒计时 + 续期按钮、方言判定分段控件 + 方言必填译文校验、提交自动 next；我的标注：表格 + 修改 dialog + 删除确认
5. 验证与硬边界：npm run build 零错误；只改本包文件；不改 router/http.ts/stores/MainLayout；dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交。完成后输出简报：文件清单 / build 输出 / 偏差说明
```

## 7. FE-4（T32+T33）总览/任务管理/用户管理/消息发送

```
你是"浙江公安方言语料采集平台"的前端开发，独立完成任务包 FE-4（计划任务 T32+T33）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T32、T33 全文
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md §4 的 FE-4 一节
   - 视觉规格 dome/admin-overview.html、admin-tasks.html、admin-users.html、admin-message-send.html（只读，1:1 还原）
2. 建工作区：git worktree add .worktrees/web-4 -b feature/zjpdt-fe4 feature/zj-police-dialect-web
3. 依赖：cd zj_police_dialect_trans/web && npm install（失败重试 --registry=https://registry.npmmirror.com）
4. 实现（独占=替换占位）：src/views/admin/{OverviewView,TasksView,UsersView,MessageSendView}.vue、src/api/admin/{stats,tasks,users,messages}.ts
   - 总览：6 统计卡（total）+ 任务进度卡（完成率/已启动/未启动，未启动>0 warn）+ 类别分布条形（后端 /stats/overview 响应已含 category_counts——集成裁定已由 P-admin-data 承载，前端直接消费）+ 区域表（rows+total，本辖区金色高亮，super_admin/省管区域级联下钻）
   - 任务管理：筛选表单 + 行内进度条（超额金色、未启动 warn、cancelled 置灰）+ 4 dialog（单人/批量选人/调整/取消）+ 规则说明 alert
   - 用户管理：筛选 + 表格（角色 tag/录音数/有效标注数/任务进度）+ 新建编辑 dialog（角色选项按 /auth/me role：super_admin 可选 super_admin，admin 仅 user/admin）+ 重置密码 + 删除（400 有录音禁删透传）+ 批量导入 dialog（模板下载/el-upload/轮询明细）+ 导出 blob
   - 消息发送：收件口径 el-segmented（按人员远程搜索/按区域级联含市=全市/按单位派出所下拉）+ 右侧已发记录（收件数/已读数），发送成功显示 发送 N 人/越界跳过 M
5. 验证与硬边界：npm run build 零错误；只改本包文件；不改 router/http.ts/stores/MainLayout；dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交。完成后输出简报：文件清单 / build 输出 / 偏差说明
```

## 8. FE-5（T34+T35）文本线/音频/录音标注管理/导出

```
你是"浙江公安方言语料采集平台"的前端开发，独立完成任务包 FE-5（计划任务 T34+T35）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T34、T35 全文
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md §4 的 FE-5 一节
   - 视觉规格 dome/admin-text-import.html、admin-text-import-manage.html、admin-texts.html、admin-audio-upload.html、admin-audio-import.html、admin-recordings.html、admin-annotations.html、admin-export.html（只读，1:1 还原）
2. 建工作区：git worktree add .worktrees/web-5 -b feature/zjpdt-fe5 feature/zj-police-dialect-web
3. 依赖：cd zj_police_dialect_trans/web && npm install（失败重试 --registry=https://registry.npmmirror.com）
4. 实现（独占=替换占位）：src/views/admin/{TextImportView,TextImportManageView,TextsView,AudioUploadView,AudioImportView,RecordingsView,AnnotationsView,ExportView}.vue、src/api/admin/{texts,export}.ts
   - 文本导入：类别+区域（super_admin 可改）+ el-upload txt/docx + 轮询进度 + 句号切分示例文案；台账：批次表+详情+撤销（409 被引用拒撤提示）
   - 文本管理：checkbox 表 + 日期区间 + 批量删除显示 skipped 明细
   - 音频上传：多文件 dropzone + 状态表（已入库/上传中/等待/失败）；扫盘：服务器路径+递归开关+轮询+4 统计格
   - 录音管理：质检状态筛选、试听 audioManager、文件名 formatter 只显文件名
   - 标注管理：筛选+表格+删除确认+底部统计「是方言 N/不是 M」
   - 导出：两源合并清单（source 标签：录音/音频库）+ 筛选 + 导出所选/全部 → 任务卡轮询 → 下载（blob）后提示「文件已删除，如需再次请重新打包」+ 即焚警示
5. 验证与硬边界：npm run build 零错误；只改本包文件；不改 router/http.ts/stores/MainLayout；复用 FE-4 的 admin api 文件时只追加函数（若该文件尚不存在则自建，集成时保留双方函数）；dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交。完成后输出简报：文件清单 / build 输出 / 偏差说明
```

---

## 分发顺序提醒

1. 上面 8 包**现在全部可同时发**（前置均已合并）。
2. 全部完成后：后端四包 → 主会话做 P-integrate-backend（合并+全量测试+uvicorn 冒烟）；FE-2..5 → FE-integrate（合并+npm build）。
3. 最后 P-deploy（T36，等 L3 齐）。

# 多 AI 并行分发手册（zj_police_dialect_trans）

- 日期：2026-09-22
- 用途：把《2026-09-22-implementation-plan.md》的 36 个任务重组为 **16 个可独立分发的任务包**，每包附一段可直接粘贴给新 AI 会话的指令。分发者：用户本人。集成与终审：主会话（Claude Code 控制端）。
- 共同需求基线（每个包的 AI 检出里都有）：
  - `zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md` —— 规格权威
  - `zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md` —— 36 任务实施计划（各包按任务号取用，含 Global Constraints 与完整代码）
  - `zj_police_dialect_trans/dome/` —— 20 页已确认前端视觉规格（只读）

## 0. 当前进度基线

| 已完成 | 内容 | 提交 |
|---|---|---|
| T1 | 后端骨架（config/database/security/main/conftest+测试基建） | 0a5ea4e |
| T2 | 17 张 ORM 表 | bcc0f71 |
| T3 | deps（get_current_user/require_admin/resolve_scope/scope_filter） | 61ccc86 |
| 基线 | 规格+计划+dome 入库（分发共同基线） | 01c4be3 |

- 后端主线分支：`feature/zj-police-dialect-trans`（本仓库主工作区）
- 前端骨架分支：`feature/zj-police-dialect-web`（worktree `.worktrees/web`，尚未动工）

## 1. 依赖总览（谁能同时开）

```
L1（7 路立即可开，互不依赖）:
  P-seed        P-auth-base    P-media        P-social      P-annotate     P-export      FE-1
L2（前置包合并回基线后开）:
  P-qc ←P-social          P-admin-users ←P-social
  P-admin-content ←P-media
  P-admin-data ←P-social
  FE-2 / FE-3 / FE-4 / FE-5 ←FE-1（四路并行）
L3（集成，各一）:
  P-integrate-backend ←全部后端包      FE-integrate ←FE-2..5
L4:
  P-deploy+冒烟 ←L3 全部
```

| 包 | 计划任务号 | 前置 | 基线分支 |
|---|---|---|---|
| P-seed | T4 | 无 | feature/zj-police-dialect-trans |
| P-auth-base | T5+T6 | 无 | 同上 |
| P-media | T7+T8 | 无 | 同上 |
| P-social | T12+T13 | 无 | 同上 |
| P-annotate | T10+T11 | 无 | 同上 |
| P-export | T23 | 无 | 同上 |
| P-qc | T9 | P-social 已合并 | 合并后基线 |
| P-admin-users | T14+T15 | P-social 已合并 | 同上 |
| P-admin-content | T16+T17+T19 | P-media 已合并 | 同上 |
| P-admin-data | T18+T20+T21+T22 | P-social 已合并 | 同上 |
| P-integrate-backend | 集成 | 上述全部 | 同上 |
| FE-1 | T24+T25 | 无 | feature/zj-police-dialect-web（worktree 已建） |
| FE-2 | T26+T27+T31 | FE-1 已合并 | 合并后 web 分支 |
| FE-3 | T28+T29+T30 | 同上 | 同上 |
| FE-4 | T32+T33 | 同上 | 同上 |
| FE-5 | T34+T35 | 同上 | 同上 |
| FE-integrate | 集成 | FE-2..5 | 同上 |
| P-deploy | T36 | P-integrate-backend + FE-integrate | feature/zj-police-dialect-trans |

## 2. 全局规则（写进每个包的指令，AI 必须遵守）

1. **工作区**：在 `e:\project\record-web-test` 根执行 `git worktree add .worktrees/<包名> -b feature/zjpdt-<包名> <基线分支>`（目录已存在则直接进入）。所有工作只在 worktree 内。
2. **提交纪律**：只 `git add <自己的独占路径>`；**禁止 git add -A**；禁止 push / rebase / 改 git 配置；提交信息用中文描述式（照计划各任务 Step 里的示例）。
3. **文件独占**：只创建/修改本包"独占文件"清单内的文件。唯一例外 `server/app/main.py`：仅允许追加自己的 `include_router` 行与功能所需 startup 行，不得重构。合并冲突由集成包解决。
4. **只读区**：`audio-server-test/`（移植参考源）、`dome/`、其他包的文件、`tests/conftest.py`（骨架已含 db/client/make_user；注意 `auth_header` fixture 硬编码用户 id=1，多用户测试必须显式 `create_token(str(user.id))`）。
5. **响应信封**：所有业务端点统一 `{code:0, msg:"", data:...}`；唯一例外 `GET /api/health` 返回裸 `{"status":"ok"}`。
6. **后端环境**：Python 3.10–3.12（**3.13 会让 sqlalchemy 2.0.23 崩**）。建 venv：`cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests`（无 conda 则用任意 3.10–3.12 解释器）。测试：`.venv/Scripts/python -m pytest tests -v`，既有用例必须保持全绿。宿主机无 ffmpeg 时，涉ffmpeg用例按计划 skip。
7. **前端环境**：node v24/npm 11 可用；npm 失败重试 `--registry=https://registry.npmmirror.com`。验证 = `npm run build`（vue-tsc 零错误）。
8. **TDD**：先写失败测试再实现；完成定义 = 新用例+既有用例全绿 + 已提交 + 输出简报（文件清单/用例数/命令与输出/偏差说明）。

## 3. 后端包详表

### P-seed（T4）
- **独占**：`server/app/utils/{__init__,gen_seed_data,seed_data,seed}.py`、`server/tests/test_seed.py`、main.py（startup 扩展）
- **产出契约**：`run_seed(db)->None` 幂等；`seed_data.REGIONS/DIALECTS/POLICE_STATIONS`
- **本包裁定**：① startup 先 `os.makedirs` 建 data/audio_storage/exports 三目录再 init_db（修 fresh-checkout 崩溃）；② REGIONS 数据源：`local_province.db` 只有 33 区域（演示子集）——用 WebSearch/WebFetch 取权威浙江 11 市 90 县级行政区划代码表，断言总数 102 并抽查 330105/330283/331004；dialects(11)/police_stations(696) 从 `e:\project\record-web-test\audio-server-test\local_province.db`（绝对路径只读）导出；③ `test_seed_account_login` 加 `@pytest.mark.skip(reason="依赖 auth 端点，集成包启用")`。

### P-auth-base（T5+T6）
- **独占**：`server/app/api/auth.py`、`server/app/api/base.py`、`server/app/schemas/{__init__,auth}.py`、`server/tests/{test_auth,test_base}.py`、main.py（注册 2 个 router）
- **要点**：测试自造 region/dialect/station 数据（不依赖 seed）；注册校验 phone `^\d{11}$`、region_code 必须存在、role 固定 user；tree 一次查全表分桶构建。

### P-media（T7+T8）
- **独占**：`server/app/api/{texts,recordings}.py`、`server/app/schemas/{text,recording}.py`、`server/tests/{test_texts,test_recordings}.py`、main.py
- **产出契约**：`convert_to_wav(src_bytes,dst_path)->float`（时长秒）、模块级 `_ffmpeg_sem = asyncio.Semaphore(2)`（供 P-admin-content 复用）
- **契约修订（原 T18 的扩展前移到这里）**：`GET /api/recordings/{id}/file` 一开始就允许"本人 **或** require_admin 且录音 region_code ∈ scope"；P-admin-data 不得再改此文件。

### P-social（T12+T13）
- **独占**：`server/app/services/{__init__,task_progress,messaging}.py`、`server/app/api/{tasks,messages}.py`、`server/tests/{test_task_progress,test_messages}.py`、main.py
- **产出契约（后端最核心，多包消费，签名不得偏离）**：
  - `progress_map(db, user_ids: list[int]) -> dict[int, dict[str, int]]`（值形如 `{"recording_done":36,"annotation_done":24}`；recording 只计 qc_status='passed'）
  - `send_message(db, user_ids, title, content, sender_id=None) -> None`（建 Message + 批量 MessageRecipient，user_ids 去重）

### P-annotate（T10+T11）
- **独占**：`server/app/api/{annotations,audio_files}.py`、`server/app/schemas/annotation.py`、`server/tests/{test_annotations,test_audio_files}.py`、main.py
- **要点**：3 分钟锁惰性回收；is_dialect=true 时 translation 必填 400；一条音频一条标注。

### P-qc（T9）——前置：P-social 已合并
- **独占**：`server/app/services/qc.py`、`server/tests/test_qc.py`、main.py（startup 加 qc_loop）
- **依赖接口**：`from .messaging import send_message`（P-social 产出，签名见上）
- **本包裁定**：停用直通用例用 `monkeypatch.setattr("app.core.config.settings.asr_api_url","")`（settings 导入时已实例化，改 os.environ 无效）；7 个用例照计划 T9 Step 1。

### P-admin-users（T14+T15）——前置：P-social
- **独占**：`server/app/api/admin/{__init__,users,user_import}.py`、`server/app/schemas/admin.py`、`server/tests/{test_admin_users,test_admin_user_import}.py`、main.py
- **依赖接口**：`progress_map`（列表进度列）

### P-admin-content（T16+T17+T19）——前置：P-media
- **独占**：`server/app/api/admin/{texts,text_import,audio_upload,audio_import}.py`、`server/app/utils/file_scanner.py`、`server/tests/{test_admin_texts,test_admin_text_import,test_admin_audio}.py`、main.py
- **依赖接口**：`from ..api.recordings import convert_to_wav, _ffmpeg_sem`

### P-admin-data（T18+T20+T21+T22）——前置：P-social
- **独占**：`server/app/api/admin/{recordings,annotations,stats,tasks,messages}.py`、`server/tests/test_admin_manage.py`、`server/tests/{test_admin_stats,test_admin_tasks,test_admin_messages}.py`、main.py
- **依赖接口**：`progress_map`、`send_message`；录音文件下载直接用 P-media 已建端点（见契约修订），**不改 api/recordings.py**。
- **注意**：T18 原文"扩展 T8 端点放行 admin"已在 P-media 前移实现——本包只做列表/删除。

### P-export（T23）
- **独占**：`server/app/api/admin/export.py`、`server/app/schemas/export.py`、`server/tests/test_admin_export.py`、main.py
- **要点**：两源清单（recordings 仅 passed + audio_files 已判方言）；ZIP_STORED；下载即焚；逐条 scope 校验。admin/__init__.py 若已被 P-admin-users 创建，只追加 import。

### P-integrate-backend（L3 集成）
- 职责：按拓扑序 `git merge` 各 feature/zjpdt-* 后端分支 → feature/zj-police-dialect-trans；解决 main.py 冲突（各包 include_router/startup 行全部保留）；解除 test_seed 的 skip；全量 pytest 绿；`uvicorn app.main:app` 起 /api/health 冒烟；输出合并记录。

## 4. 前端包详表（基线分支 feature/zj-police-dialect-web；视觉规格=zj_police_dialect_trans/dome/，1:1 还原到 Element Plus）

**API 契约（FE 全部包遵守）**：base `/api`；信封 `{code,msg,data}`，code!==0 报错，401 清 token 跳 /login；头 `Authorization: Bearer <token>`；登录返回 `data:{token,user:{id,real_name,role,region_code}}`。路由 19 条与守卫按计划 §8。**api 模块按域一包一文件**（避免共享文件冲突）：auth.ts/base.ts/texts.ts/recordings.ts/annotations.ts/tasks.ts/messages.ts + admin/{users,texts,stats,tasks,messages,export}.ts。**views 由 FE-1 建占位，后续包只替换自己的占位文件**。

### FE-1（T24+T25）——worktree `.worktrees/web` 已建好，直接在里面做
- **独占**：`web/` 整个目录（脚手架起步）：src/{main.ts,App.vue,styles/theme.css,api/http.ts,router/index.ts,stores/{user,message,audio}.ts,layouts/MainLayout.vue,views/**占位**}
- **产出契约**：http.ts（拦截器）、useUserStore、useMessageStore（unread+refresh，路由切换+30s 轮询）、useAudioStore（单声道 play/stop）、MainLayout（按角色菜单：user=日常工作5+消息1；admin/super_admin 追加管理工作12）、theme.css 设计 token（--zp-navy #0E2440 等，取自 dome/assets/theme.css）
- 脚手架：`npm create vite@latest web -- --template vue-ts`（在 zj_police_dialect_trans/ 下）+ element-plus/@element-plus/icons-vue/pinia/vue-router/axios，Element Plus 全量引入。

### FE-2（T26+T27+T31）登录/注册/首页/我的消息 ——前置 FE-1 合并
- **独占**：views/{LoginView,RegisterView,HomeView,MessagesView}.vue、api/{auth,messages}.ts（首页用 tasks.ts 时只建不改他人文件——tasks.ts 归 FE-3，本包如需先用可在自己分支建，集成时保留其一）
- **要点**：注册三级区域级联 `/regions/tree` + 派出所联动；消息四类 tag 按 title 前缀映射（「新任务」navy/「录音质检未通过」danger/「公告」gold/其余 blue）；后端补 `POST /api/messages/read-all` 已由 P-social 计划任务承载，若无则 FE 先循环调详情。

### FE-3（T28+T29+T30）录音采集/我的录音/标注两页 ——前置 FE-1
- **独占**：views/{RecordView,MyRecordingsView,AnnotationView,MyAnnotationsView}.vue、components/{Recorder,AudioPlayer}.vue、api/{texts,recordings,annotations,tasks}.ts
- **要点**：Recorder=MediaRecorder（mimeType 择优 webm;codecs=opus→webm→mp4）；120s 分配倒计时；上传成功提示"已提交质检"；AudioPlayer 走 useAudioStore 单声道。

### FE-4（T32+T33）总览/任务管理/用户管理/消息发送 ——前置 FE-1
- **独占**：views/admin/{OverviewView,TasksView,UsersView,MessageSendView}.vue、api/admin/{stats,tasks,users,messages}.ts

### FE-5（T34+T35）文本线/音频/录音标注管理/导出 ——前置 FE-1
- **独占**：views/admin/{TextImportView,TextImportManageView,TextsView,AudioUploadView,AudioImportView,RecordingsView,AnnotationsView,ExportView}.vue、api/admin/{texts,export}.ts（录音/标注管理复用 FE-4 的 admin api 文件时只追加函数，不改他人已有函数）

### FE-integrate（L3）
- 合并 feature/zjpdt-fe2..fe5 → feature/zj-police-dialect-web；api 模块冲突按"保留双方函数"解决；`npm run build` 零错误。

## 5. 粘贴指令模板（每包一段，直接发给新 AI 会话）

> 把 `<...>` 换成对应包的值；后端包通用模板如下，前端包把第 2/3/5 步换成前端版。

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 <包名>（计划任务 <任务号>）。
1. 通读需求：zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md 的 Global Constraints 与任务 <任务号> 全文；规格 docs/specs/2026-09-21-platform-design.md 对应节；本计划 docs/plans/2026-09-22-parallel-dispatch.md 中 <包名> 一节（含独占文件与裁定）。
2. 建工作区（在 e:\project\record-web-test 下）：git worktree add .worktrees/<包名> -b feature/zjpdt-<包名> <基线分支>；若已存在直接进入。
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 用任意 Python 3.10–3.12，禁 3.13）。
4. TDD 实现任务 <任务号>：先失败测试，再实现，既有用例保持全绿（.venv/Scripts/python -m pytest tests -v）。
5. 硬边界：只创建/修改本包独占文件；main.py 仅追加 include_router/startup 行；不改 conftest.py 与他人文件；audio-server-test 与 dome 只读；禁止 git add -A / push / rebase。
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单/用例数与命令输出/偏差说明。
```

前端版第 3/5 步替换：
```
3. 工作区：FE-1 用已建好的 .worktrees/web（分支 feature/zj-police-dialect-web）；FE-2..5 在基线合并后 git worktree add .worktrees/web-<n> -b feature/zjpdt-fe<n> feature/zj-police-dialect-web。
5. 硬边界：只改本包 views 与 api 文件；不改 router/http/stores/MainLayout（FE-1 产出）；对照 dome/*.html 1:1 还原；验证 npm run build 零错误。
```

## 6. 分发操作顺序（建议）

1. **现在就发**（7 路并行）：P-seed、P-auth-base、P-media、P-social、P-annotate、P-export、FE-1。
2. P-social 合并回基线后 → 发 P-qc、P-admin-users、P-admin-data；P-media 合并后 → 发 P-admin-content；（合并动作可让对应前置包的 AI 完成后由主会话执行，或用户手动 `git merge --no-ff`）。
3. FE-1 合并后 → 发 FE-2/3/4/5。
4. 全部后端包完成 → P-integrate-backend；FE 全部 → FE-integrate。
5. 最后 P-deploy（T36）+ 全链路冒烟（清单在计划 T36 与规格 §10）。
6. 终审（requesting-code-review 全分支评审）与收尾由主会话负责。

## 7. 集成/合并由谁做

默认：各包 AI 只在自己分支提交；**合并回基线分支由主会话或用户执行**（避免多 AI 同时操作基线分支）。前置包合并后，再开 L2 包。

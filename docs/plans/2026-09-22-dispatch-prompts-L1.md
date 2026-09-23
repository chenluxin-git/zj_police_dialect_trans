# L1 分发指令（7 包，2026-09-22）

- 用途：每段整块复制，粘贴给一个**新的 AI 会话**（一包一会话）。
- 基线状态：`feature/zj-police-dialect-trans` @ b4885f6；`feature/zj-police-dialect-web` 已快进至同一提交。
- 合并回基线由主会话/用户执行，各包 AI 只在自己分支提交。

---

## 1. P-seed（T4）

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-seed（计划任务 T4）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T4 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md 对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-seed 一节（独占文件与裁定）
2. 建工作区（在 e:\project\record-web-test 根执行）：git worktree add .worktrees/p-seed -b feature/zjpdt-p-seed feature/zj-police-dialect-trans（目录已存在则直接进入）
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 则用任意 Python 3.10–3.12，禁 3.13）
4. TDD 实现任务 T4：先写失败测试再实现；既有用例保持全绿（.venv/Scripts/python -m pytest tests -v）
5. 硬边界：只创建/修改本包独占文件：server/app/utils/{__init__,gen_seed_data,seed_data,seed}.py、server/tests/test_seed.py；server/app/main.py 仅追加 startup 行；不改 tests/conftest.py 与他人文件；audio-server-test/ 与 dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点（裁定）：
- 产出契约：run_seed(db)->None 幂等；seed_data.REGIONS/DIALECTS/POLICE_STATIONS
- startup 先 os.makedirs 建 data/audio_storage/exports 三目录再 init_db（修 fresh-checkout 崩溃）
- REGIONS 数据源：用 WebSearch/WebFetch 取权威浙江 11 市 90 县级行政区划代码表，断言总数 102 并抽查 330105/330283/331004
- dialects(11)/police_stations(696) 从 e:\project\record-web-test\audio-server-test\local_province.db（绝对路径、只读）导出
- test_seed_account_login 加 @pytest.mark.skip(reason="依赖 auth 端点，集成包启用")
```

## 2. P-auth-base（T5+T6）

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-auth-base（计划任务 T5+T6）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T5、T6 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md 对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-auth-base 一节
2. 建工作区（在 e:\project\record-web-test 根执行）：git worktree add .worktrees/p-auth-base -b feature/zjpdt-p-auth-base feature/zj-police-dialect-trans（目录已存在则直接进入）
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 则用任意 Python 3.10–3.12，禁 3.13）
4. TDD 实现任务 T5+T6：先写失败测试再实现；既有用例保持全绿（.venv/Scripts/python -m pytest tests -v）
5. 硬边界：只创建/修改本包独占文件：server/app/api/{auth,base}.py、server/app/schemas/{__init__,auth}.py、server/tests/{test_auth,test_base}.py；server/app/main.py 仅追加 include_router 行（注册 2 个 router）；不改 tests/conftest.py 与他人文件；audio-server-test/ 与 dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点：
- 测试自造 region/dialect/station 数据（不依赖 seed）
- 注册校验 phone ^\d{11}$、region_code 必须存在、role 固定 user
- /regions/tree 一次查全表分桶构建
```

## 3. P-media（T7+T8）

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-media（计划任务 T7+T8）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T7、T8 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md 对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-media 一节
2. 建工作区（在 e:\project\record-web-test 根执行）：git worktree add .worktrees/p-media -b feature/zjpdt-p-media feature/zj-police-dialect-trans（目录已存在则直接进入）
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 则用任意 Python 3.10–3.12，禁 3.13）
4. TDD 实现任务 T7+T8：先写失败测试再实现；既有用例保持全绿（.venv/Scripts/python -m pytest tests -v）。宿主机无 ffmpeg 时涉 ffmpeg 用例按计划 skip
5. 硬边界：只创建/修改本包独占文件：server/app/api/{texts,recordings}.py、server/app/schemas/{text,recording}.py、server/tests/{test_texts,test_recordings}.py；server/app/main.py 仅追加 include_router 行；不改 tests/conftest.py 与他人文件；audio-server-test/ 与 dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点（产出契约，签名不得偏离）：
- convert_to_wav(src_bytes, dst_path) -> float（返回时长秒）；模块级 _ffmpeg_sem = asyncio.Semaphore(2)（供 P-admin-content 复用）
- 契约修订：GET /api/recordings/{id}/file 一开始就允许"本人 或 require_admin 且录音 region_code ∈ scope"
```

## 4. P-social（T12+T13）

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-social（计划任务 T12+T13）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T12、T13 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md 对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-social 一节
2. 建工作区（在 e:\project\record-web-test 根执行）：git worktree add .worktrees/p-social -b feature/zjpdt-p-social feature/zj-police-dialect-trans（目录已存在则直接进入）
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 则用任意 Python 3.10–3.12，禁 3.13）
4. TDD 实现任务 T12+T13：先写失败测试再实现；既有用例保持全绿（.venv/Scripts/python -m pytest tests -v）
5. 硬边界：只创建/修改本包独占文件：server/app/services/{__init__,task_progress,messaging}.py、server/app/api/{tasks,messages}.py、server/tests/{test_task_progress,test_messages}.py；server/app/main.py 仅追加 include_router 行；不改 tests/conftest.py 与他人文件；audio-server-test/ 与 dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点（后端最核心契约，多包消费，签名不得偏离）：
- progress_map(db, user_ids: list[int]) -> dict[int, dict[str, int]]，值形如 {"recording_done":36,"annotation_done":24}；recording 只计 qc_status='passed'
- send_message(db, user_ids, title, content, sender_id=None) -> None，建 Message + 批量 MessageRecipient，user_ids 去重
- 后端需提供 POST /api/messages/read-all（FE-2 依赖）
```

## 5. P-annotate（T10+T11）

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-annotate（计划任务 T10+T11）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T10、T11 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md 对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-annotate 一节
2. 建工作区（在 e:\project\record-web-test 根执行）：git worktree add .worktrees/p-annotate -b feature/zjpdt-p-annotate feature/zj-police-dialect-trans（目录已存在则直接进入）
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 则用任意 Python 3.10–3.12，禁 3.13）
4. TDD 实现任务 T10+T11：先写失败测试再实现；既有用例保持全绿（.venv/Scripts/python -m pytest tests -v）
5. 硬边界：只创建/修改本包独占文件：server/app/api/{annotations,audio_files}.py、server/app/schemas/annotation.py、server/tests/{test_annotations,test_audio_files}.py；server/app/main.py 仅追加 include_router 行；不改 tests/conftest.py 与他人文件；audio-server-test/ 与 dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点：
- 3 分钟锁惰性回收
- is_dialect=true 时 translation 必填 400
- 一条音频一条标注
```

## 6. P-export（T23）

```
你是"浙江公安方言语料采集平台"的后端开发，独立完成任务包 P-export（计划任务 T23）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T23 全文
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md 对应章节
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md 的 P-export 一节
2. 建工作区（在 e:\project\record-web-test 根执行）：git worktree add .worktrees/p-export -b feature/zjpdt-p-export feature/zj-police-dialect-trans（目录已存在则直接进入）
3. 环境：cd zj_police_dialect_trans/server && conda run -n animal python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests（无 conda 则用任意 Python 3.10–3.12，禁 3.13）
4. TDD 实现任务 T23：先写失败测试再实现；既有用例保持全绿（.venv/Scripts/python -m pytest tests -v）
5. 硬边界：只创建/修改本包独占文件：server/app/api/admin/export.py、server/app/schemas/export.py、server/tests/test_admin_export.py；server/app/api/admin/__init__.py 若已被其他包创建则只追加 import；server/app/main.py 仅追加 include_router 行；不改 tests/conftest.py 与他人文件；audio-server-test/ 与 dome/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add 自己路径）。完成后输出简报：文件清单 / 用例数与命令输出 / 偏差说明

本包要点：
- 两源清单（recordings 仅 qc_status=passed + audio_files 已判方言）
- ZIP_STORED 打包；下载即焚
- 逐条 scope 校验
```

## 7. FE-1（T24+T25）

```
你是"浙江公安方言语料采集平台"的前端开发，独立完成任务包 FE-1（计划任务 T24+T25）。仓库根：e:\project\record-web-test。

1. 通读需求（按序）：
   - zj_police_dialect_trans/docs/plans/2026-09-22-implementation-plan.md：Global Constraints 与任务 T24、T25 全文（含路由 19 条与守卫）
   - zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md §8
   - zj_police_dialect_trans/docs/plans/2026-09-22-parallel-dispatch.md §4 前端包详表与 FE-1 一节
   - 视觉规格 zj_police_dialect_trans/dome/（20 页，只读，1:1 还原到 Element Plus）
2. 工作区：worktree 已建好——直接进入 e:\project\record-web-test\.worktrees\web（分支 feature/zj-police-dialect-web，已含全部文档基线），所有工作在此 worktree 内
3. 脚手架：在 worktree 的 zj_police_dialect_trans/ 下 npm create vite@latest web -- --template vue-ts；安装 element-plus / @element-plus/icons-vue / pinia / vue-router / axios，Element Plus 全量引入；npm 失败重试 --registry=https://registry.npmmirror.com
4. 实现（独占=web/ 整个目录）：
   - src/main.ts、src/App.vue、src/styles/theme.css（设计 token --zp-navy #0E2440 等，取自 dome/assets/theme.css）
   - src/api/http.ts：base /api；信封 {code,msg,data}，code!==0 报错，401 清 token 跳 /login；头 Authorization: Bearer <token>
   - src/router/index.ts：19 条路由与守卫按计划 §8
   - src/stores/{user,message,audio}.ts：useUserStore（登录返回 data:{token,user:{id,real_name,role,region_code}}）；useMessageStore（unread+refresh，路由切换+30s 轮询）；useAudioStore（单声道 play/stop）
   - src/layouts/MainLayout.vue：按角色菜单——user=日常工作5+消息1；admin/super_admin 追加管理工作12
   - src/views/ 全部占位页（后续包只替换自己的占位文件）
5. 验证与硬边界：npm run build（vue-tsc 零错误）；只改 web/ 目录；不改其他包文件；audio-server-test/ 只读；禁止 git add -A / push / rebase
6. 按任务内示例提交（中文信息，只 add web/ 路径）。完成后输出简报：文件清单 / build 输出 / 偏差说明
```

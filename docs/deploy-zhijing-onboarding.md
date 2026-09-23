# 浙警智治接入 · 部署与联调清单（用户域 + 省厅零信任）

> 配套代码：`server/app/services/zero_trust.py`（认证）、`audit.py`（审计）、`org_sync.py`（统一用户）、
> `api/rzzx.py`（联动服务）、`region_mapper.py`（机构码映射）、前端 `views/AuthCallbackView.vue`。
> 环境变量模板：`server/.env.zhijing.example`。设计背景见 `docs/plans/2026-09-23-zhijing-onboarding-plan.md`。

---

## 1. 你需要从省厅/平台拿到的 5 样东西

| # | 事项 | 从哪拿 | 用途 |
| --- | --- | --- | --- |
| 1 | **系统标准码 / requestId** | 资源管理器-我的应用 | 审计 `sysId`、数据编目、智慧运维唯一标识 |
| 2 | **AppKey（AK）/ SecretKey（SK）** | 同上（应用系统概览） | 生成应用令牌、审计上报 `appSecret` |
| 3 | **认证回调地址要求 + 上架时"认证参数"类型** | 上架页面/审批人 | 决定走 `dynamic`（动态秘钥）还是 `rzzx`（令牌信息） |
| 4 | **零信任/认证、权限、审计服务地址** | 省厅对接人（地市应用找本地科信） | 填 `ZHIJING_RZ_URL` / `QX_URL` / `AUDIT_URL` |
| 5 | **服务器访问方式**（IP、端口开放、能否出网到上述地址） | 省厅给的服务器 | 部署与连通性验证 |

> 这 5 样到齐前，代码可先以 `ZHIJING_MODE=mock` 完整跑通"免登录 → 进首页 → 审计落台账"链路。

---

## 2. 联调三步走（每步都可独立验证）

### 第 0 步：mock 模式（不等省厅凭据就能做）

```bash
# server/.env
ZHIJING_MODE=mock
ZHIJING_LEGACY_LOGIN=true
```

```bash
# 后端
cd server && python -m uvicorn app.main:app --port 8000
# 前端
cd web && npm run dev
```

验证：
1. 浏览器打开 `http://localhost:5173/#/auth` → 应自动进入首页（无需输账号）。
   想看不同身份可带参数：`http://localhost:5173/api/auth/zhijing/callback?police_no=33100400002&name=张三`（再由前端落地页接管）。
2. `http://localhost:8000/api/auth/zhijing/self-check` → `mode=mock`，审计配置项齐备。
3. 登录后查审计台账（`server/data/app.db` 的 `audit_logs` 表）应有多条记录，
   `operateType=0`（登录）、`operateCondition=通过[数字证书]方式登录了系统。`

### 第 1 步：live 模式 + 认证打通（拿到 1/2/3/4 后）

```bash
ZHIJING_MODE=live
ZHIJING_LOGIN_SOURCE=both        # 不确定平台给哪种参数时用 both
ZHIJING_SYS_ID=...
ZHIJING_APP_KEY=...
ZHIJING_APP_SECRET=...
ZHIJING_RZ_URL=https://...
ZHIJING_QX_URL=https://...
```

验证（**判定标准就是"能从平台直接进首页，不再输账号密码"**）：
1. `GET /api/zhijing/info` 看 `self_check.zero_trust`：`mode=live`、地址可达性不为异常。
2. 从警综平台/浙警智治终端点开本应用 → 应直接进首页。
3. 进不去时按状态码定位：
   - 跳回登录页且提示"平台认证未通过" → 回调地址/参数类型不符（对应审批页面的"认证参数"下拉框）；
   - 提示"令牌无效或不存在" → `1001/1003`：令牌没取到（检查是否被前置代理吞了 Header）；
   - 提示"权限冻结" → `0003`：找平台侧开通应用权限。

### 第 2 步：审计上报 + 用户同步（拿到 1/2 后）

```bash
ZHIJING_AUDIT_ENABLED=true
ZHIJING_ORG_SYNC_ENABLED=true     # 需要先在资源管理器申请"统一用户"组件并拿到服务地址
ZHIJING_ADMIN_POLICE_NUMBERS=33100400001   # 谁当管理员
```

验证：
1. 做几个动作（登录、录音、标注、导出），在 `audit_send` 表看到批次 `result=ok`、`status_code=0000`。
2. 断开审计服务地址再操作几次 → `audit_logs.status` 仍为 `pending`、`retry_count` 递增；
   恢复后自动重推成功（这是规范硬性要求：失败必须本地缓存后重推）。
3. 统一用户同步：`org_sync_cursor` 表 `dept`/`user` 两行游标有值，`users` 表出现平台同步来的账号（`source=zhijing`）。

---

## 2.5 接口路径与令牌注销（联调期可能被平台"改口径"的地方）

**所有平台接口路径都集中在配置里**，若省厅给的组件调用文档与规范默认值不同，改 `.env` 即可，不要改代码：

| 配置项 | 默认值（规范） | 用途 |
| --- | --- | --- |
| `ZHIJING_PATH_GET_LOGIN_USER` | `/jyglb/apis/V2/getLoginUser` | 用户基本信息获取（复合：令牌校验 + 取人） |
| `ZHIJING_PATH_CREATE_APP_TOKEN` | `/jwt/nologin/V2/202307/createAppToken` | 应用令牌生成 |
| `ZHIJING_PATH_RENEW_TOKEN` | `/jwt/nologin/V2/renewOrOfflineToken` | 令牌续期 / 注销（**SM3 签名**） |
| `ZHIJING_PATH_APP_PERMISSION` | `/dzRole/V2/202307/jqfw/yyj` | 应用级鉴权 |
| `ZHIJING_PATH_AUDIT_JSON` | `/commonApi/logApi_v2/transferJsonLog` | 审计 JSON 上报 |

**统一用户/部门同步的地址与路径同样全走配置**（`ZHIJING_ORG_BASE_URL`、`ZHIJING_ORG_*_PATH`、
`ZHIJING_ORG_PAGE_SIZE_*`、`ZHIJING_ORG_HEADERS`），未配基地址时会**显式报错并跳过**，
不会静默不同步；当前配置与游标进度可在 `GET /api/auth/zhijing/self-check` 的 `org_sync` 段看到。

**已实现的平台侧注销**（规范要求，避免平台侧残留有效令牌）：
用户登出时若请求带 `RZZX-USERTOKEN`，会自动调用令牌注销服务（`callerSign = SM3(key 升序的 JSON)`，
`callerSign`、`dqxtbs` 不参与签名；返回 `1004/1005` 视为正常）。
平台调用失败**不影响本地退出**，只记警告日志。

### 2.6 审计字段长度（已按规范对齐，改字段前先看这张表）

| 字段 | 规范上限 | 代码位置 |
| --- | --- | --- |
| `numId` | 32 | `audit._num_id()` |
| `userId` | 40 | `FIELD_LIMITS` |
| `organization` | 100 | 同上 |
| `organizationId` | 18（实际填 12 位机构码） | 同上 |
| `userName` | 30 | 同上 |
| `terminalId` | 50（取 `X-Forwarded-For` 首跳） | 同上 |
| `operateName` | **30** | 同上（曾误写 64，已修并加守卫用例） |
| `operateCondition` / `display` | 5000 | 同上 |
| `errorCode` | 4 | 同上 |
| `dataLevel` | 0-3 | 同上 |

单批裁剪：`audit._fit_batch()` 按**报文字节上限精确裁剪**（不是"超限折半"，
否则单条 `display` 接近 5000 字时该批永远发不出去）；裁剪后剩余记录保持 pending，下批继续。

重推策略：失败日志**永远不丢弃**——重试超限只升级告警级别（`logger.error`）并继续退避重推，
`GET /api/auth/zhijing/self-check` 的 `audit.backlog` 会给出 `pending` / `retry_over_limit` /
`oldest_pending_at`，运维据此发现积压。

### 2.8 审计积压排查

```bash
# 自检接口直接看积压（含最老一条待上报时间）
curl -sk https://<域名>/api/auth/zhijing/self-check | grep -A6 backlog
# 数据库侧
#   SELECT status, count(*) FROM audit_logs GROUP BY status;
#   SELECT send_id, count, result, status_code, message FROM audit_send ORDER BY id DESC LIMIT 10;
```

### 2.7 统一用户 / 部门同步（需先申请组件资源）

**首次接入顺序（先全量、再增量）**：

```bash
# 1) 配置组件地址与路径（见 .env.zhijing.example 的 ZHIJING_ORG_*）
# 2) 全量初始化：先部门（SJLX=1）再警员（SJLX=3）—— 警员要落部门名
curl -sk -X POST -H "Authorization: Bearer <管理员token>" \
  "https://<域名>/api/admin/org-sync/init?kind=dept&token=<触发口令，可选>"
curl -sk -X POST -H "Authorization: Bearer <管理员token>" \
  "https://<域名>/api/admin/org-sync/init?kind=user&token=<触发口令，可选>"
# 3) 打开定时增量
#    .env: ZHIJING_ORG_SYNC_ENABLED=true（频率 ≥60s）
# 4) 看状态（配置/游标/上次结果，不触发同步）
curl -sk -H "Authorization: Bearer <管理员token>" "https://<域名>/api/admin/org-sync/status"
```

- 触发链接即规范要求的"**实时模式同步触发链接**"（`?type=bm` / `?type=yh` 的等价形态，本系统用 `kind`）；
- **初始化幂等但较重，不要放进定时任务**；定时任务只跑增量；
- 增量**分页拉完为止**（返回条数 < 分页上限即认为结束），单次运行最多 50 页防平台侧游标不前进导致死循环；
- 初始化与增量的每次调用都会写**服务日志**（含条数/页数/耗时），联调时按接口名检索即可。

核对要点：`org_sync_cursor` 表 `dept`/`user` 两行游标持续推进；`org_units` 出现机构并带
`region_code`（机构码→区划码映射结果）；同步来的账号 `users.source=zhijing` 且无本地口令。

> ⚠️ **映射是本项目最大风险点**：现有省/市/县数据隔离完全建立在 6 位区划码上。
> 上线前请用真实机构代码样本（省厅/市局/区县分局/派出所各一条）验证
> `services/region_mapper.py::map_region_code` 的落点是否符合预期。

**映射体检接口**（管理员，联调时先用它核对，再决定是否补白名单）：

```bash
# sample 传省厅给的机构代码样本（逗号分隔），返回每条代码落到的区划与层级
curl -sk -H "Authorization: Bearer <管理员token>" \
  "https://<域名>/api/auth/zhijing/mapping-health?sample=330000410000,331000410000,331004410500"
```

返回要点：`match_rate`（命中率）、`unmapped_codes`（未命中清单，会回退省级根=看不到任何区县数据）、
`items[].region_level`（省/市/区县，用来确认三级机构码是否落到对应层级）。

---

## 3. 零信任联动服务（对方要调我们）- 地址：`https://<你的域名>/api/rzzx/linkage`（POST，JSON）
- 指令：`role-update` / `token-offline` / `token-online` / `token-renew`
- 签名：`SM3("action=&msg=&userTokenId=&appTokenId=&pid=&appid=")`，`live` 模式强制校验，签名错返回 `0001`
- 效果：
  - `token-offline` → 写入 `revoked_tokens`，该令牌不可再换会话；
  - `role-update` → 把对应用户 `auth_invalidated_at` 置为"当前秒上界"，
    此前签发的本地会话令牌立即 401（重新从平台进入即恢复），**权限变更即时生效**；
  - `token-online` 解除历史吊销；`token-renew` 登记更新。
- 排查入口：`GET /api/rzzx/revoked`（管理员）。

> 把这个地址连同我方参数一起交给零信任对接人；对方需要能访问到（同域反向代理或放行端口）。

---

## 4. 数据库与迁移

- 正式环境用 **MySQL**：`DATABASE_URL=mysql+pymysql://user:pwd@host:3306/zjpdt?charset=utf8mb4`
- 启动时会自动：
  1. `create_all()` 建缺失的表；
  2. `app/core/migrate.py::ensure_columns()` 为**已存在的表补新增列**（只加列，不改类型/约束）。
- 本地 SQLite 升级同理：直接重启即可，日志会打印实际执行的 `ALTER TABLE ... ADD COLUMN`。
- 需要人工处理的场景：改列类型、改约束、加索引、重命名 —— 这些不在自动迁移范围内。

---

## 5. 部署形态与 nginx 要点

现有 `docker-compose.yml`（backend + web/nginx）可继续用，上架前需改：

1. **证书**：把自签证书换成正式证书（数据域/用户域域名由平台侧提供，或使用本单位正式证书）。
2. **反代请求头**（审计取真实 IP 依赖它，现有配置已透传，勿删）：

```nginx
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

3. **访问日志格式改造**（智慧运维日志接入要求，含耗时与上游信息）：

```nginx
log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                '$status $body_bytes_sent "$http_referer" '
                '"$http_user_agent" "$request_time" "$http_x_forwarded_for" '
                "$upstream_response_time" "$upstream_addr" "$upstream_status";
access_log logs/access.log main;
```

4. **日志留存不少于两年**（规范硬性要求）：为 nginx 与应用日志配置轮转与保留策略。
5. **子路径部署**（如 `/record/`）：构建时带 `--base=/record/`，并设 `FRONTEND_BASE=/record/`，
   否则认证回调 302 会跳错地址。

---

## 6. 浏览器兼容（上架硬性要求）

规范要求：新应用必须支持 Chrome 内核浏览器，最低 Chromium 49，且 49 以上都能正常工作。
我们的交付基线是 **Chrome80**（与"Chrome80 兼容改造"要求一致），已做三件事：

1. **构建目标**：`web/vite.config.ts` 里 `build.target='chrome80'`。
2. **产物语法体检**：`npm run check:es-target`（构建后自动跑，不合规直接让构建失败）。
   - 结论：产物**不含** Chrome80 解析不了的语法（无逻辑赋值 `||=`/`&&=`/`??=`、无类静态块）。
   - **重要澄清**：可选链 `?.` 与空值合并 `??` 是 **Chrome 80 自带的 ES2020 特性**
     （见 [Chrome 80 更新说明](https://developer.chrome.com/blog/new-in-chrome-80/)、
     [InfoQ 报道](https://www.infoq.com/news/2020/02/chrome-80-released/)），
     构建后保留它们是正确的，**不需要也不应该**为 Chrome80 做降级。
3. **运行时 API 补齐**：`web/src/polyfills.ts`（在 `main.ts` 首行导入）。
   依赖里用到了 Chrome80 不存在的运行时 API——Element Plus 的 `arr.at(-1)`（Chrome 92）、
   Pinia 的 `Object.hasOwn`（Chrome 93）。这类不是语法问题，构建期降级无效，必须运行时补齐。
   语义自检：`npm run check:polyfill`。

> ⚠️ 如果客户终端实际低于 Chrome 80（规范下限 Chromium 49），`?.` / `??` 仍需继续降级：
> 把 `vite.config.ts` 的 `build.target` 改成 `chrome49`（或 `es2019`）重跑即可，
> 体检脚本会同时校验新基线的语法缺口。交付前请在目标终端实测：
> **打开页面 → 登录 → 录音 → 上传 → 标注 → 导出** 全链路。

---

## 7. 仍待人工/平台侧完成的事项（代码之外）

| 环节 | 动作 |
| --- | --- |
| 应用注册与上架 | 资源管理器注册系统取标准码 → 上架时填认证回调 URL 与认证参数类型 → 测试版审批 → 正式上架 → 授权权限组 |
| 安全检测 | 一个月内完成：合作企业备案、零信任对接（认证+权限+审计）、三高一弱风险评估、等保测评 |
| 智慧运维 | Matomo 埋点（需 siteId）、日志采集（SLS 或 AIOS-agent）、GAPM-agent（**官方覆盖 Java/.NET/PHP，Python 栈需向智慧运维书面确认免接或替代方案**）、浙警智评悬浮球（`xtbs`=系统标准码） |
| 数据编目归集 | 按公安部标准编目，提供生产库视图或只读账号供抽取 |
| 组件上架共享 | 把方言转译/质检能力封装为标准组件在技术能力中心上架 |
| 材料 | 应用图标 PNG 64×64（圆角 5px）/128×128（圆角 10px）、60 字以内简介、警种/地市/跑道、联系人及备份联系人 |
| 演示数据 | 上架前清理演示账号与示例语料；`ZHIJING_LEGACY_LOGIN=false` 关闭本地口令登录 |

---

## 8. 审计覆盖清单（操作类型 `operateType` 对照）

已接入审计埋点的动作（其余端点按同一 `audit.queue_audit(...)` 方式续接即可）：

| 动作 | 端点 | operateType | 说明 |
| --- | --- | --- | --- |
| 平台证书登录（成功） | `GET/POST /api/auth/zhijing/callback` | 0 | `operateName` 填实际登录方式（数字证书）；`operateCondition=通过[数字证书]方式登录了系统。` |
| 本地口令登录（成功/失败） | `POST /api/auth/login` | 0 | 失败记 `errorCode=3004`，结果 0 |
| 登出 | `POST /api/auth/logout` | 5 | 同时触发平台令牌注销（SM3 签名） |
| 录音上传 | `POST /api/recordings` | 2 | 记文本 ID、时长、字节数 |
| 删除录音 | `DELETE /api/recordings/{id}` | 4 | |
| 提交标注 | `POST /api/annotations` | 2 | 记音频 ID、区域、译文长度 |
| 数据集导出（勾选/全量） | `POST /api/admin/export/audio[-all]` | 6 | 记筛选条件与条数（导出是审计重点） |
| 文本批量删除 | `DELETE /api/admin/texts/batch` | 4 | 记请求/实际删除/跳过条数 |
| 新增/修改/删除用户 | `POST/PUT/DELETE /api/admin/users` | 2/3/4 | 记账号、角色、区域、变更字段 |
| 用户清单导出 | `GET /api/admin/users/export` | 6 | 记筛选条件与条数 |
| 发送站内消息 | `POST /api/admin/messages` | 2 | 记对象类型/对象/实际送达人数 |
| 文本导入 | `POST /api/admin/texts/import` | 2 | 记文件、类别、归属区域 |
| 音频扫盘导入 | `POST /api/admin/audio/import` | 2 | 记服务器路径、是否递归、区域 |
| 用户批量开户 | `POST /api/admin/users/import` | 2 | 记文件与总行数 |

> 守卫用例 `tests/test_audit_coverage_guard.py` 会静态检查上表端点是否仍带 `queue_audit`，
> 重构时漏埋会直接测试失败。

### 8.1 服务日志（logType=2）覆盖清单

规范要求"服务日志"记录**接口服务调用过程**，与应用日志分开上报（子类型 `201`）：

| 被调接口 | 接口中文名（`interfaceName`） | 触发时机 | 失败也记 |
| --- | --- | --- | --- |
| `{SerRzIP}/jyglb/apis/V2/getLoginUser` | 用户基本信息获取服务 | 平台登录/令牌校验 | 是（含服务不可达） |
| `{SerRzIP}/jwt/nologin/V2/202307/createAppToken` | 应用令牌生成服务 | 需生成应用令牌时；**缺 AK/SK 也记一条** | 是 |
| `{SerRzIP}/jwt/nologin/V2/renewOrOfflineToken` | 令牌续期注销服务 | 登出注销/续期 | 是 |
| `{SerQxIP}/dzRole/V2/202307/jqfw/yyj` | 应用级鉴权服务 | 配了 `ZHIJING_AUTH_BUTTON` 时 | 是 |
| 统一用户组件·部门增量 | 获取部门增量信息 | 定时同步（≥60s） | 是 |
| 统一用户组件·警员增量 | 获取警员增量信息 | 定时同步（≥60s） | 是 |

> 字段与零信任审计规范一致（16 字段驼峰），`requester` 填系统标准码。
> 实用价值：联调时"进不去/没数据"先查服务日志——失败原因、错误码、响应摘要都在库里。

---

## 9. 自检与排查命令

```bash
# 配置与地址自检（不产生业务数据）
curl -s http://127.0.0.1:8000/api/zhijing/info
curl -s http://127.0.0.1:8000/api/auth/zhijing/self-check

# 回调是否可达（模拟平台 GET 回调，mock 模式）
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/api/auth/zhijing/callback?police_no=33100400002&name=test"

# 审计积压与批次（SQLite 用 sqlite3；MySQL 用对应客户端）
#   SELECT status, count(*) FROM audit_logs GROUP BY status;
#   SELECT send_id, count, result, status_code, message FROM audit_send ORDER BY id DESC LIMIT 10;
```

### 9.1 一键预检脚本（推荐先跑这个）

```powershell
# 仓库根目录执行；会临时起一个 mock 后端跑通免登录链路，跑完自动关闭
powershell -ExecutionPolicy Bypass -File scripts\zhijing-preflight.ps1
# 需要连前端重新构建一起验时（会与运行中的 npm run dev 抢文件锁，建议先停 dev）：
powershell -ExecutionPolicy Bypass -File scripts\zhijing-preflight.ps1 -WithBuild
```

覆盖 12 项：后端全量测试、前端类型检查、产物 Chrome80 体检、构建产物存在性、polyfill 自检、
接入自检接口、**会话建立（302 → `/#/auth` → `/auth/me`）**、**零信任联动 role-update 致旧会话 401**、
**审计登录留痕**、**服务日志（logType=2）落库**、真机联调凭据是否齐全、docker-compose 语法。

- 退出码 = 失败项数；**"真机联调凭据"** 一项在拿到省厅 AK/SK 前必然失败，属预期；
- 默认**不重新构建前端**：实测 `npm run build` 与运行中的 `npm run dev` 抢文件锁会让 dev server
  因 `EBUSY` 直接崩掉；需要重建时先停 dev 再加 `-WithBuild`；
- 脚本文件必须保持 **UTF-8 with BOM**（Windows PowerShell 5.1 否则按 ANSI 解析中文并报语法错）；
- 脚本会 `Push-Location server` 再跑 pytest（pytest 的 rootdir/conftest 在 server 内）。

本仓库后端完整回归（Windows 下用 venv 解释器）：

```powershell
cd server
& ".venv\Scripts\python.exe" -m pytest -q      # 279 passed
```

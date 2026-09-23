# 浙警智治内网上架改造计划（电子证书登录）

> 状态：**已确认方向并开始实施**（基础层已落地，见 §9；真机联调待平台凭据）。
> 依据：`zhejiang-police-zhijing-integration` Skill 及其 references/01~06。
> 目标：把当前"手机号+密码"的独立网页，改造为经**浙警智治**平台打开、**数字证书免二次登录**、接入零信任（认证+权限+审计）与智慧运维、在公安内网正式上架的应用。

## 0.5 已确认的决策（2026-09-23）

| 项 | 决策 |
| --- | --- |
| 部署域与层级 | **用户域 + 省厅零信任**（行政流程已走通，省厅已给服务器；我方只交付"网页 + 端口"） |
| 登录形态 | **平台免二次登录**（从浙警智治终端/警综平台点开即进首页，不做登录页） |
| 本期范围 | 零信任认证 + 联动服务、审计上报、统一用户/部门同步（**不含**消息中心、智慧运维、数据编目、组件上架） |
| 部署与数据库 | 保持 docker compose，**SQLite → MySQL** |
| 安全合规 | 按**等保二级**、**不强制国密**实现（SM3 已就绪，JWT 仍 HS256，保留可替换点） |
| 浏览器 | **Chrome80 及以上**（已设 `build.target=chrome80`） |
| 过渡期登录 | **保留手机号+密码但默认关闭**，仅 `super_admin` 应急可用（`ZHIJING_LEGACY_LOGIN`） |

---

## 0. 结论先行

当前系统是"**自带账号体系的独立 Web 应用**"（FastAPI + SQLite + Vue3，自签 HTTPS + nginx 反代）。
上架内网后，登录动作**不再由本系统的登录页承担**：

```
现在： 用户 → 本系统 /login → 手机号+密码 → 本系统签发 JWT
之后： 用户 → 浙警智治终端/警综平台（证书登录已完成）
           → 带 RZZX-APPTOKEN / RZZX-USERTOKEN 打开本系统认证回调地址
           → 本系统校验令牌取人员信息 → 建立本地会话 → 进首页（无登录页、无二次登录）
```

所以本次改造的本质是：**认证主体外置**（本系统只做令牌校验与本地用户映射），并补齐**权限、审计、运维、部署**四块合规件。

---

## 1. 现有资产盘点（已阅读代码）

| 位置 | 现状 | 上架影响 |
| --- | --- | --- |
| `server/app/api/auth.py` | 注册/登录/me，手机号+密码，自签 JWT | 需新增令牌认证入口，登录页降级为过渡后门 |
| `server/app/core/security.py` | HS256 JWT（`SECRET_KEY`），bcrypt | 保留作本地会话票据；国密要求下需评估 SM2/SM3 |
| `server/app/api/deps.py` | `get_current_user` / `require_admin` / `resolve_scope`（省-市-区县数据范围） | **数据权限逻辑可完整复用**，只换认证入口 |
| `server/app/models/base_data.py` | `Region.code` 为**行政区划代码**（6 位，省/市/区县/派出所） | ⚠️ 零信任返回的是**12 位机构代码 DM / DEPTNAME**，需要映射表 |
| `server/app/models/social.py` | `User(phone, real_name, police_station, region_code, role)` | 需补 `cert_id/police_no/org_code/dept_name/source` 等字段 |
| `server/app/core/config.py` | `DATABASE_URL`、`SECRET_KEY`、`ASR_API_URL`、`SCAN_ROOT` 等 | 需新增零信任/审计/运维/消息中心一整套配置 |
| `server/app/main.py` | 启动建目录、建表、seed、后台 ASR 质检循环 | 需挂启动即启的审计上报与用户同步后台任务 |
| `web/src/views/LoginView.vue`、`router/index.ts` | 登录页 + `public` 路由 + 守卫 | 需支持"令牌回调自动登录"，守卫改为以平台会话为准 |
| `web/nginx.conf`、`docker-compose.yml` | 自签证书 443、`/api` 反代、单卷 SQLite | 需换正式证书/域名、日志格式改造、数据库换 MySQL |
| `server/.venv`（本机已装） | Python 3.14 + 已升级 SQLAlchemy 2.0.54 / FastAPI 0.141 | 容器内仍按 3.10 基线，不受影响（见 §7 备注） |

**未在代码中实现、必须新增的合规件**：零信任认证/权限/审计、统一认证回调、部门与用户同步、消息中心、Matomo 埋点、SLS/AIOS 日志、GAPM-agent、浙警智评悬浮球、数据编目、组件上架。

---

## 2. 必须先定性的两个问题（决定后面所有分支）

| 定性 | 影响 |
| --- | --- |
| **部署域：用户域 / 数据域** | 决定资源申请类型、认证方式（动态秘钥 vs 令牌信息）、零信任对接目标（省厅/本市）、是否必须走安全访问通道与云桌面/堡垒机 |
| **对接层级：省厅 / 地市** | 决定零信任与审计服务地址（省市地址不同，地市由本地科信提供） |

**本项目特征**：录音+方言文本属于**大量采集/存储/处理数据**的系统，规范中"大数据类应用系统要求统一部署在**公安网数据域**"；且按现计划要取人员/部门信息（统一用户服务），即访问省厅数据 —— 两条都指向**数据域 + 令牌方式 + 数据域零信任**。
若确定走数据域，则**部署前必须先申请云桌面/堡垒机**，用户从用户域过来还要走**用户访问通道（Web 访问代理）**并申请 `xxx.gat.zj` 域名。

---

## 3. 改造工作分解

### A. 后端：零信任认证（P0，核心）

- 新增配置：`SerRzIP`(认证)、`SerQxIP`(权限)、`SJSerIP`(审计)、`APP_KEY/SECRET_KEY_SK`、`DQXTBS`(系统标识/requestId)、`CALLBACK_PATH`。
- 新增 `services/zero_trust.py`：
  1. **取令牌**：先取 Header `RZZX-USERTOKEN`/`RZZX-APPTOKEN`，取不到再回退请求参数（规范明确要求）；
  2. **校验+取人**：POST `{SerRzIP}/jyglb/apis/V2/getLoginUser`（**复合接口**：含用户令牌校验 + 应用令牌校验 + 取人员信息，一次调用即完成认证；其中已含应用级鉴权，可不单独调 `yyj`，但若审批方要求显式鉴权则再调 `{SerQxIP}/dzRole/V2/202307/jqfw/yyj`）；
  3. 处理状态码：`0000` 成功；`0002` 令牌失效 / `1000`~`1003` 解密失败或令牌不存在 → 401 回登录；`0003` 权限冻结 → 403。
  4. **应用令牌**：用 `POST {SerRzIP}/jwt/nologin/V2/202307/createAppToken`（appKey+secureKey+毫秒时间戳）生成并**缓存**，供跨域调用与回调校验用；到期用 `renewOrOfflineToken` 续期（**SM3 签名**）。
- 新增 `GET/POST /api/auth/rzzx/callback`：上架时填报的**认证回调地址**，收令牌 → 校验 → 建立会话 → 302 跳首页。
- **会话策略**：校验通过后仍签发本系统短时 JWT（复用现有 `create_token`），避免每个业务请求都打认证服务；令牌失效/下线由联动服务驱动本地会话失效（见 C）。
- **用户映射**（关键设计点）：以 **身份证号 / 警号 / 机构代码** 为准入键 upsert 本地 `users` 记录，`region_code` 由机构代码映射得到（见 D），`role` 初始 `user`，管理员由管理台或映射规则赋予。
- 过渡期：保留手机号+密码登录（可配置开关），仅用于联调与管理员应急；上架检测时**建议默认关闭**。

### B. 后端：零信任权限（P0）

- 应用级鉴权：`{SerQxIP}/dzRole/V2/202307/jqfw/yyj`（若 A 已用复合接口则作为兜底/双重校验，按审批方要求定）。
- 功能级/服务级/数据级鉴权按需扩展（`gnj` / `fwj` / `sjj`），本项目数据级鉴权可用于"区县只看本区县语料"的二次核验。
- 现有 `resolve_scope`（省→市→区县）保留为**本地数据范围**，与平台鉴权叠加：平台管"能不能进/能不能用这个功能"，本地管"看得到哪些区县数据"。

### C. 后端：零信任联动服务（反向接口，P0）

- 新增 `POST /api/rzzx/linkage`：接收零信任指令，按 `action` 处理 `role-update`（权限更新→强制重新鉴权）、`token-offline`（清本地令牌/会话缓存）、`token-online`、`token-renew`；`sign` 按 `action=&msg=&userTokenId=&appTokenId=&pid=&appid=` 拼接做 **SM3** 校验。
- 返回 `{ "status_code": "0000", "message": "操作成功" }`。

### D. 后端：统一用户 / 部门同步（P0，决定"人从哪来"）

现状是"282 个种子账号 + 手工导入用户"，内网正式环境应改为**从平台同步**：

- 按应用域申请"**初始化接口**"（部门 `SJLX=1`、用户 `SJLX=3`）做全量，再申请"**获取部门增量信息**"、"**获取警员增量信息**"做增量；**定时频率 ≥ 1 分钟**，并持久化增量游标（部门 `BEGINID`、用户 `ZID`）。
- 落地：新增 `org_units` / 同步游标表，把**12 位机构代码 ↔ 行政区划代码**建立映射（这是本项目能否复用现有 `resolve_scope` 数据权限的**最大技术风险点**，需与平台方确认字段口径）。
- 保留现有 Excel 导入作为**兜底**（无平台权限时）。

### E. 后端：审计服务（P0，全部应用必做）

- 新增 `services/audit.py` + 本地待上报表（P1 要求：**推送失败必须本地缓存后重推**）。
- 上报 `POST {SJSerIP}/commonApi/logApi_v2/transferJsonLog`，外层 `sysId`(requestId) / `sendId`(≤32) / `logType` / `subLogType` / `logContents` / `appSecret` / `checkSum`。
- `logContents` 16 字段（`numId/userId/organization/organizationId/userName/operateTime/terminalId/operateType/operateResult/errorCode/operateName/operateCondition/display/dataLevel`），**单次 ≤100 条、≤1M、只含同一类型**。
- `checkSum`= **SM3**(`sysId&sendId&logType&subLogType&logContents&appSecret`)，`logContents` 内 key 按字典升序；**需要引入 SM3 实现**（Python 侧拟用 `gmssl` 或纯 Python SM3 实现，见 §7 依赖变更）。
- `terminalId` 必须取 `X-Forwarded-For` 的**第一跳**（用户域→数据域多次代理，现 nginx 已透传，需在后端解析并记录第一段）。
- 埋点位置：登录/登出（`operateType=0/5`，`operateName` 填实际登录方式如"数字证书"）、各列表查询（1）、文本/音频新增导入（2）、修改（3）、删除（4）、**导出（6，语料包导出必记）**、比对（7，ASR 质检可用）。
- 日志本地留存**不少于两年**：由 nginx + 应用日志滚动策略保证。

### F. 后端：消息中心对接（P1）

- 现有 `messages`/`message_recipients` 站内信与"任务进度提醒"可改为调用**消息中心接收接口**推送（浙政钉 → 失败转短信）；需申请消息中心组件资源，注意默认限制（当天重复禁发、个人 10 条/日、全应用 1000 条/日）。
- 建议：**平台消息与站内信双写**（平台推送失败不影响站内信），并把"消息是否已读/处理"回写状态更新接口。

### G. 前端改造（P0）

- 新增 `views/RzzxCallbackView.vue` 或在路由守卫前拦截：带令牌参数进入时调后端回调接口完成登录，成功后 `router.replace('/')`，**失败才回登录页**。
- 守卫改造：无本地会话时优先尝试平台令牌自动登录；登录页保留（过渡期）并去掉"演示账号"提示（上架材料与截图中出现演示口令属敏感项）。
- **Matomo 埋点**：`main.ts` 用 `vue-matomo`（Vue3 方案）+ 路由 `watch` 打 PV，`setUserId` 用警号/身份证；`host=41.190.22.9:9530`，`siteId` 由智慧运维提供。
- **浙警智评悬浮球**：在**首页（非登录页）**植入规定代码，`xtbs` 填**系统标准码**。
- **Chrome80 兼容改造**：Vite 8 默认构建目标偏新，需显式 `build.target` 降到 `chrome80`（上架硬性要求，最低 Chromium 49），并对 `MediaRecorder`（现在只探 `audio/webm`）增加兼容分支；`demo` 静态稿同步清理。
- 移除 `dome/` 中带演示账号的静态页引用（如仍需保留，放到不影响上架的目录）。

### H. 运维接入（P1）

| 项 | 动作 | 前置 |
| --- | --- | --- |
| 前端埋点 | Matomo（G 已列） | 智慧运维提供 siteId；用户域可访问 `41.190.22.9:9530` |
| 日志采集 | 改造 nginx `log_format`（含 `$request_time`/`$http_x_forwarded_for`/upstream 三项）；选 **SLS**（需德清云 ECS）或 **AIOS-agent** | 需反馈应用名/服务器 IP/日志路径 |
| 稳定性探针 | **GAPM-agent 官方只覆盖 Java/Tomcat/.NET/PHP**，本项目是 Python(FastAPI) → 需与智慧运维确认"不满足条件免接"或改用 AIOS 指标方案 | 规范：条件不满足需向智慧运维反馈理由 |
| 数据库监控 | 装 GAPM-agent 后自动上报（同上，受限于 Python 栈） | 同上 |
| 浙警智评 | 悬浮球植入 + 截图反馈 | 系统标准码 |

### I. 部署与安全（P0）

- **域名与证书**：正式内网域名（数据域应用走用户访问通道后生成 `xxx.gat.zj`，或地市域名）+ 平台签发/正式证书，**弃用自签**；nginx 的 `X-Forwarded-For`/`X-Real-IP` 透传保持并补 `log_format`。
- **数据库**：SQLite（卷）→ **MySQL**（数据域云数据库）；`DATABASE_URL` 已是单一配置项，迁移成本低，但需补迁移脚本与备份策略。
- **部署形态**：现 docker compose 双容器可继续用；数据域需先申请云桌面/堡垒机部署，再申请用户访问通道。
- **安全检测四项必备**：合作企业备案、零信任对接（认证+权限+审计）、三高一弱风险评估、等保测评（**一个月内**完成，逾期下架）。
- **国密要求**：开发同步使用国产密码算法。现状 HS256 + bcrypt 属国际算法；若等保三级/国密测评要求，需评估 JWT 改 SM2、密码/摘要改 SM3、传输与存储加密（**待确认范围，见 §7 问题 7**）。
- **应用图标与材料**：PNG 64×64（圆角 5px）/128×128（圆角 10px）、60 字以内简介、警种/地市/跑道、联系人及备份联系人。
- **测试账号**：安全检测需给警综平台管理员开通**最低权限账户**用于登录测试。

### J. 平台侧流程动作（非代码，但阻塞联调）

1. 资源管理器注册系统 → 取**系统标准码/requestId**（数据编目、智慧运维、零信任三处共用，必须规范）。
2. 提**应用接入工单**（创建工单→系统梳理→组件上架→数据编目→智慧运维→安全中心→应用上架；市/县系统每个节点**两人**审核）。
3. 申请资源：算力（云主机/DB）、安全资源（云桌面/堡垒机）、**用户访问通道**、数据交换通道（如需）、域名。
4. 申请组件资源：统一认证相关服务（数据域为 5 个令牌服务）、统一用户/部门初始化与增量、消息中心、审计。
5. 上架时**认证参数选"令牌信息"/令牌 2.1**，填认证回调 URL；联系审批人完成测试版上架 → 联调（可直接进首页即算对接完成）→ 责任民警**正式上架** → 授权权限组。
6. 数据编目归集：按公安部数据标准编目，提供生产库**视图或只读账号**由技术变革组抽取（省厅系统归省厅平台，市/县归地市平台）。
7. 组件上架共享：把"方言转译/质检"等核心能力封装为标准组件在技术能力中心上架。

---

## 4. 里程碑与顺序

| 阶段 | 内容 | 依赖 |
| --- | --- | --- |
| M0 定性与注册 | 确认域/层级；系统注册取标准码；提工单；申请云桌面/堡垒机与算力 | 责任民警 |
| M1 认证打通 | A + B + C（回调、令牌校验、联动服务）；用责任民警账号测"直接进首页" | M0、认证服务地址与 AK/SK |
| M2 用户与权限 | D 同步 + 机构码↔区划码映射；E 审计上报联调 | M0、统一用户/审计资源 |
| M3 前端与运维 | G + H（Matomo、nginx 日志、探针确认、悬浮球） | siteId、标准码 |
| M4 部署与检测 | I（证书/域名/MySQL/compose）+ 安全检测四项 + 材料准备 | M1~M3 |
| M5 上架发布 | 测试版上架审批 → 正式上架 → 授权 → 数据编目/组件上架收尾 | M4 |

---

## 5. 主要风险

1. **机构代码 ↔ 行政区划代码映射**：现有数据权限完全建立在 6 位区划码上，平台给的是 12 位机构码。若口径对不上，省/市/县三级数据隔离（本项目核心治理逻辑）会失效 —— 必须最早验证。
2. **Python 栈的运维接入**：GAPM-agent 不覆盖 Python，稳定性/数据库监控可能免接，需书面确认，避免验收时被判"未完成对接"。
3. **等保/国密范围**：JWT、bcrypt、SM3、SQLite→MySQL 的改造量取决于等保级别与国密测评要求。
4. **Chrome80 兼容**：Vite 8 产物能否直接跑在 Chrome80 需实测（`build.target` 降级 + 录音兼容分支）。
5. **演示数据与演示账号上架**：现有登录页与 seed 数据含演示口令、示例语料，上架前必须清理。
6. **认证服务不可用时的可用性**：需定义降级策略（令牌校验失败的重试与提示、本地会话有效期），避免认证服务抖动导致全体无法进入。

---

## 6. 交付物

- 代码：`services/zero_trust.py`、`services/audit.py`、`services/org_sync.py`、`api/auth.py`(回调)、`api/rzzx.py`(联动)、前端回调页/埋点/悬浮球、`nginx.conf` 与 `docker-compose.yml` 更新、配置项与迁移脚本。
- 文档：接入参数清单（AK/SK/标准码/服务地址）、审计字段映射表、机构码映射规则、联调与验证清单（含"进首页即通"判定）、上架材料（图标、简介、联系人）、安全自查清单。
- 测试：认证/权限/审计/同步的 pytest 用例（现有 148 例全绿为基线，本机已验证通过）。

---

## 7. 待确认问题（阻塞编码，见对话）

1. 部署**用户域**还是**数据域**？省厅对接还是**地市**（地市需本地科信另给地址）？
2. "电子证书登录"落地形态：点应用免二次登录（令牌回调 / 动态秘钥），还是保留登录页 + 证书/账号口令多因子？
3. M1 联调前置（AK/SK、requestId/系统标准码、认证与审计服务地址、测试环境访问方式）是否已有？
4. 本期范围：只做认证+审计（最小上架），还是含统一用户同步、消息中心、智慧运维、数据编目、组件上架全量？
5. 平台消息是否替换现有站内信（双写 / 替换 / 暂不动）？
6. 数据库是否本期 SQLite → MySQL？部署仍用 docker compose 还是改由平台云主机/容器规范？
7. 等保级别与国密要求（是否要求 SM2/SM3 替换 JWT 与 bcrypt）？
8. 浏览器兼容目标：Chrome80 还是更低（Chromium 49）？录音是否允许降级提示？
9. 过渡期是否保留手机号+密码登录（含超级管理员应急账号）？

---

## 8. 备注（本机环境，不影响内网方案）

本机为 Windows + Python 3.14，`server/.venv` 中已把 `sqlalchemy` 升到 2.0.54、`fastapi`→0.141.1、`starlette`→1.6.0（原 pinned 的 0.104.1/2.0.23 在 3.14 上无法 import）。实测后端 `183 passed`，前端 `http://localhost:5173` 可登录。容器基线仍是 Python 3.10 + 原 pin，无需为此改动内网方案。

---

## 9. 实施进度（代码已落地部分）

| 交付物 | 位置 | 说明与验证 |
| --- | --- | --- |
| 国密 SM3 | `server/app/core/sm3.py` | 纯 Python 实现，标准向量自检（`abc` / `abcd×16`）在 `tests/test_sm3.py` |
| 审计上报 | `server/app/services/audit.py`、`models/audit.py` | 16 字段台账 + `checkSum=SM3(...)` + 批量（≤100/≤1M）+ **失败缓存重推** + `X-Forwarded-For` 首跳取真实 IP；后台循环 `audit_loop()` 随应用启动 |
| 零信任认证 | `server/app/services/zero_trust.py`、`api/auth.py` | 令牌先在 Header、取不到回退参数；`getLoginUser` 复合接口校验取人；应用级鉴权；**动态秘钥**回调参数解析；令牌续期/注销（SM3 签名，登出时同步注销平台令牌）；`off/mock/live` 三模式；接口路径全部走配置项 |
| 认证回调落地 | `GET/POST /api/auth/zhijing/callback`、`web/src/views/AuthCallbackView.vue` | 校验通过 → 建/更新本地用户 → 会话票据 → 302 `#/auth?token=...` → 前端复核后进首页 |
| 零信任联动 | `server/app/api/rzzx.py`、`models/linkage.py` | `role-update`/`token-offline`/`token-online`/`token-renew` + SM3 签名校验；role-update 使旧会话立即失效（`deps.py::_token_superseded`，UTC 秒级比对） |
| 机构码映射 | `server/app/services/region_mapper.py` | 12 位机构代码 → 6 位区划码（前 6 位 → 前 4 位+00 → 回退省根） |
| 统一用户/部门同步 | `server/app/services/org_sync.py`、`models/org.py` | 增量拉取 + 游标持久化（`BEGINID`/`ZID`）+ 定时循环（≥60s）；接口路径集中在 `OrgSyncConfig` 待联调填 |
| 轻量加列迁移 | `server/app/core/migrate.py` | 启动自动为已有表补新增列（SQLite/MySQL 通用），避免升级老库后 500 |
| 联调自检 | `GET /api/auth/zhijing/self-check`、`GET /api/zhijing/info` | 配置齐备性 + 地址可达性，不产生业务数据 |
| 前端改造 | `stores/user.ts`、`router/index.ts`、`views/LoginView.vue`、`vite.config.ts`、`polyfills.ts`、`scripts/check-es-target.cjs` | 会话/票据落地、`/auth` 公开路由、登录页提示平台入口、演示账号仅 DEV 展示、构建目标 chrome80 + 产物语法体检 + **Chrome80 运行时 API 补齐**（Element Plus `arr.at`、Pinia `Object.hasOwn`） |
| 审计埋点 | `recordings.py`、`annotations.py`、`admin/export.py`、`admin/texts.py`、`auth.py` | 已接：登录/登录失败/登出/录音上传与删除/提交标注/两种导出/文本批量删除（覆盖 8 类操作中的登录、新增、删除、登出、导出；查询类按需续接） |
| MySQL 兼容 | `tests/test_token_renew_and_mysql.py` | 新表 DDL 与"自动加列"语句用 MySQL 方言编译校验；加列迁移幂等 |
| 部署交付物 | `deploy/nginx.zhijing.conf`、`server/.env.zhijing.docker.example`、`docker-compose.yml`、`deploy/README.md` | 上架版 nginx（结构化访问日志 + 安全响应头 + 子路径示例）、容器环境模板、MySQL 可选 profile、backend 健康检查、日志外挂卷（`logs/nginx`、`logs/backend`） |
| 交付物自洽校验 | `server/tests/test_deploy_config.py` | 环境模板覆盖全部 `ZHIJING_*` 配置项、compose 挂载路径真实存在、两份 nginx 都保留审计所需转发头与运维日志字段 |

**端到端已验证（mock 模式）**：回调 303 跳转前端 → `audit_logs` 出现 `operateType=0` 登录记录（含机构码、真实 IP、`operateCondition=通过[数字证书]方式登录了系统。`）→ 历史 seed 账号被升级为平台账号（`source=zhijing`）而非插重，`users` 唯一约束未冲突。

### 9.1 第二轮补强（含被测试抓出的 3 个真实缺陷）

| 项 | 说明 |
| --- | --- |
| 审计字段对齐规范 | `operateName` 由 64 收敛到规范的 **30**（并加"字段上限 ≥ 列宽"守卫，防再次漂移）；`FIELD_LIMITS` 成为唯一口径 |
| 单批裁剪改为精确 | 旧实现"超限就折半"在单条 `display` 接近 5000 字时**仍会超限**、导致该批永远发不出去；改为逐条累加到装不下为止，且保证至少发一条 |
| 组织同步游标 Bug | `OrgSyncCursor.total_synced` 在新建行时为 `None`，`+=` 直接 `TypeError`，**增量同步必然崩**；已修并加 `server_default` |
| 组织同步撞唯一约束 | `_upsert_user` 只按 cert_id/警号认人，历史导入账号（phone=警号）会插重撞 `users.phone` 唯一约束；已把手机号纳入认人顺序（与 `zero_trust` 一致） |
| 联动服务定位用户 | `role-update` 的 `pid` 平台可能下发身份证号或警号，改为两者都认，并记"未匹配到本地用户"告警；`UserInfo` 补 `cert_id` 供前端/联调核对 |
| 审计埋点守卫 | 新增 AST 静态用例：关键端点（登录/登出/回调/录音增删/标注/导出/文本批删）必须出现 `queue_audit`，豁免需登记理由——防止后续重构悄悄丢埋点 |
| mock 主链路用例 | 新增 `tests/test_zhijing_e2e_mock.py`：回调免登录 → 会话可用 → 登录审计 → 上报成功（台账 sent + 批次 0000）→ 令牌下线 → 权限更新致旧会话 401 → 重新登录恢复 → 登出审计 |
| dev server 稳定性 | `vite.config.ts` 忽略 `.*.tmpdir` 等临时目录（实测 chokidar 遇到会 EBUSY **直接崩掉 dev server**） |

**测试总量**：204 → **226 passed**（新增 22 例：审计规范一致性、组织同步、审计守卫、mock 端到端）。

### 9.2 第三、四轮补强

| 项 | 说明 |
| --- | --- |
| 部署交付物 | 上架版 nginx（结构化访问日志 + 安全响应头 + 子路径示例）、容器环境模板（46 项）、MySQL 可选 profile、backend 健康检查、日志外挂卷、部署当天三条校验 |
| 交付物自洽校验 | `tests/test_deploy_config.py`：环境模板覆盖全部 `ZHIJING_*`、compose 挂载路径真实存在、两份 nginx 都保留 XFF 与运维日志字段（**当场抓出 4 处缺陷**：模板漏 6 个变量、nginx 日志缺 `$request_time`、两个挂载目录不存在、镜像内 nginx 配置缺运维字段） |
| 组织同步全部走配置 | 组件服务地址/三条接口路径/分页大小/额外请求头全部进 `.env`（`ZHIJING_ORG_*`），未配基地址时**显式报错并跳过**，不静默失败；自检端点新增 `org_sync` 段展示配置与两个游标进度 |
| 审计埋点补齐八类操作 | 新增：用户增/改/删、用户清单导出、消息发送、文本导入、音频扫盘导入、用户批量开户；守卫用例同步扩展（12 个端点） |
| 对接请求文档 | `docs/zhijing-integration-request.md`：可直接发给省厅/对接人的一条消息（需要对方给的 5 项、我方提供的 4 项、联调顺序、异常对照表） |

**测试总量**：226 → **240 passed**。

### 9.3 第五轮补强

| 项 | 说明 |
| --- | --- |
| 一键预检脚本 | `scripts/zhijing-preflight.ps1`：后端测试 + 前端类型/构建/兼容体检 + 免登录链路（临时 mock 后端）+ 联动 role-update + 审计留痕 + 凭据完备性 + compose 语法，共 10 项，退出码=失败项数；需 docker 的三条单独列出留给部署机 |
| 脚本自身踩坑修复 | ① Windows PowerShell 5.1 必须 **UTF-8 with BOM**，否则中文被按 ANSI 解析直接语法错；② 脚本从仓库根调用时 pytest 工作目录不对会 `1 error` 秒退，已固定 `Push-Location $server`；③ `-c` 传 SQL 里 `count(*)` 被当通配符，改为写临时脚本执行；④ 汇总行统计口径写反导致"10/10 通过"假象，已修 |

### 9.4 第六轮补强

| 项 | 说明 |
| --- | --- |
| **服务日志（logType=2）** | 规范要求应用日志与服务日志分开上报。新增 `audit.service_log()`，并埋到全部出站平台调用：`getLoginUser`/`createAppToken`/`renewOrOfflineToken`/应用级鉴权/部门增量/警员增量；**失败路径（业务失败码、服务不可达、缺 AK/SK 配置）同样留痕**，`requester` 填系统标准码，子类型 `201`，一批不与应用日志混发 |
| **机构码映射体检** | 新增 `GET /api/auth/zhijing/mapping-health`（管理员）：按 `org_units` 逐条回显落点（区划码/区划名/层级/是否命中），支持 `?sample=` 传省厅给的样本代码；返回 `match_rate` 与 `unmapped_codes`，直接回答"数据权限会不会被映射带偏"这个最大风险点 |
| 测试 | 新增 `tests/test_service_log.py`（9 例）、`tests/test_region_mapping_health.py`（5 例） |

**测试总量**：240 → **254 passed**。

### 9.5 第七轮补强（统一用户同步补全）

| 项 | 说明 |
| --- | --- |
| 全量初始化（规范 §2.3） | 新增 `org_sync.sync_init(kind)` 与 `POST /api/admin/org-sync/init?kind=dept\|user`：按 `REQUESTID/PAGENO/PAGESIZE/SJLX` 分页拉全量（部门 SJLX=1 / 警员 SJLX=3），并把最后一条游标写入增量游标表；即规范要求的"**实时模式同步触发链接**" |
| 增量改为分页拉完 | 原实现只拉第一页，**超过一页的数据会永久落后**；改为"返回条数 < 分页上限即结束"，单次最多 50 页防平台侧游标不前进死循环 |
| 同步状态端点 | `GET /api/admin/org-sync/status`：开关、组件地址是否配好、两侧游标与上次结果、单次页数上限 |
| 服务日志 | 初始化成功/失败都写服务日志（含条数与耗时）；`sync_status` 拆出只读 `current_status()`，自检端点不再写库 |
| 测试 | `tests/test_org_sync.py` 扩到 22 例（新增分页 3 例、初始化 4 例、管理端端点 4 例） |

**测试总量**：254 → **266 passed**（新增 12 例：分页 3、初始化 4、管理端端点 4、守卫 1）。

### 9.6 第九轮：live 链路自证 + 抓到一个越权入口

| 项 | 说明 |
| --- | --- |
| **安全缺口修复** | `resolve_identity` 里配了 `APPID`（应用级鉴权）时只**调用**了 `check_app_permission` 却**丢弃返回值**——平台返回"无该应用权限"（`sfyqx=false`）时用户照样能进。已改为无权限抛 403 并**禁止建号**；补 2 例正/反用例 |
| **live 全链路自证** | 新增 `tests/test_live_pipeline_mock_platform.py`（8 例）：用一个"模拟平台"按 URL 分发 4 类服务响应，验证 **live 模式**下 ① 令牌登录报文（`appTokenId`/`userTokenId`/`dqxtbs`）② 动态秘钥登录不打认证服务 ③ 审计报文 `checkSum` 可独立复算、应用日志与服务日志**分两批**（`101`/`201`）④ 统一用户初始化 `SJLX=1/3` + 增量 `BEGINID`/`ZID` + 机构码落地 ⑤ 登出 `renewOrOfflineToken` 的 `callerSign` 正确 ⑥ 应用级鉴权拒绝/放行 |

> 意义：真机联调前的"最后一公里"不再是黑盒——除"平台凭据是否有效"外，**报文形状、状态码处置、
> 批次拆分、游标推进**都已在 live 模式下自证。

**测试总量**：266 → **276 passed**。

### 9.7 第十轮：审计上报的两处硬化

| 项 | 说明 |
| --- | --- |
| **失败日志永不丢弃** | 原实现重试达 10 次即把记录标 `dead`（自动重推队列里再也没有它）——与规范 P1"失败必须本地缓存后重推"相冲突。改为**永远保持 pending + 退避重推**，超限只升级为 `logger.error` 告警；`MAX_RETRY` 从"丢弃线"变成"告警线" |
| **积压可观测** | 新增 `audit.backlog_stats()`（pending / sent / total / retry_over_limit / oldest_pending_at），挂到 `GET /api/auth/zhijing/self-check` 的 `audit.backlog`；运维不连库就知道有没有积压 |
| 单批裁剪改为 O(n) | `_fit_batch` 原本对每个候选前缀重新序列化整批（O(n²)）；改为按条累加序列化长度，一次遍历定前沿。另修复 `_contents_json([])` 的边界（原实现空列表会走到未定义分支） |

**测试总量**：276 → **279 passed**（新增 3 例：永不丢弃、积压统计、裁剪线性且守限）。

**待办**：真机联调（认证/审计/统一用户）、消息中心与智慧运维、MySQL 切换与正式证书、上架材料与安全检测。清单见 `docs/deploy-zhijing-onboarding.md`。

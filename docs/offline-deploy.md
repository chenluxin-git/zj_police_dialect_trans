# 内网离线部署操作手册（Linux + Docker）

> 面向：**浙警智治用户域**上架，平台免二次登录。
> 首次部署大概率会遇到问题，本文按"**每一步都能自查**"来写——出错时先看对应步骤的自检命令。
>
> 配套脚本：
> - 联网机：`bash scripts/export-offline.sh`  → 产出 `zjpdt-offline-<时间戳>.tar.gz`
> - 内网机：`bash load-offline.sh`（在解压后的包里）
> - 出问题：`bash scripts/collect-logs.sh --url https://<地址>` → 回传 tar.gz

---

## 0. 为什么必须走离线包

| 事实 | 后果 |
|---|---|
| 内网不能 `docker pull` | 基础镜像（python:3.10-slim / nginx:alpine / mysql:8.0）必须预先导入 |
| 内网不能 `npm install` | 前端镜像是**多阶段构建**，`npm ci` 在构建期执行 → **内网无法 `docker compose build`** |
| 内网不能 `pip install` | 后端镜像依赖同样在构建期安装 |

所以：**全部构建在联网机完成，内网只 `docker load`。**
内网侧执行 `docker compose up -d` 时**不要加 `--build`**。

---

## 1. 联网机：导出交付包

```bash
git clone <仓库> && cd zj_police_dialect_trans-main

# 后端 + 前端（默认）
bash scripts/export-offline.sh

# 内网用 MySQL 时，一并导出 MySQL 镜像
bash scripts/export-offline.sh --with-db --out /data/pkg
```

产出 `zjpdt-offline-<时间戳>.tar.gz`，内含：

```
images/zjpdt-backend.tar       后端镜像
images/zjpdt-web.tar           前端镜像（已含构建好的 dist）
images/mysql-8.0.tar           MySQL（--with-db 时）
compose/docker-compose.yml     编排文件
compose/nginx.zhijing.conf     上架版 nginx 配置
compose/env/*.example          环境变量模板（**不含真实密钥**）
compose/certs/README.txt       证书放置说明
MANIFEST.txt                   镜像标签 + 各 tar 的 sha256
```

**注意**：包里**故意不含证书与真实密钥**。证书在内网侧放，密钥在内网侧生成。

---

## 2. 内网机：导入

```bash
tar -xzf zjpdt-offline-*.tar.gz
cd zjpdt-offline-*/

# 先核对传输完整性（比对 MANIFEST.txt 里的 sha256）
sha256sum images/*.tar

# 载入镜像（用 MySQL 时加 --with-db）
bash load-offline.sh ./images --with-db
```

`load-offline.sh` 会做三件额外的事，失败会明确报出来：
1. 校验 `zjpdt-backend:latest` / `zjpdt-web:latest` 标签是否齐（不齐说明包与 compose 不匹配）
2. 检查后端镜像内 **ffmpeg / ffprobe** 是否存在（缺了录音上传必 500）
3. 检查前端镜像内 **index.html** 是否存在（缺了必白屏）

---

## 3. 目录就位

在**部署目录**（下称 `<部署根>`）下摆成这个结构：

```
<部署根>/
├── docker-compose.yml            ← cp compose/docker-compose.yml .
├── server/
│   └── .env.docker               ← cp compose/env/.env.zhijing.docker.example 后改名
├── deploy/
│   ├── certs/{cert.pem,key.pem}  ← 放正式证书
│   └── nginx.zhijing.conf        ← cp compose/nginx.zhijing.conf 到这里
└── logs/                          ← 首次启动自动创建
    ├── backend/
    └── nginx/
```

> `docker-compose.yml` 里挂载路径是相对路径（`./server/.env.docker`、`./deploy/certs`、`./logs/...`），
> **必须在 `<部署根>` 下执行 `docker compose`**，换目录会找不到文件。

---

## 4. 配置 `server/.env.docker`

### 4.1 必改项

| 变量 | 怎么填 | 填错的后果 |
|---|---|---|
| `SECRET_KEY` | `openssl rand -hex 32` | 留默认值 → 启动自检会报"仍为默认值"，且会话可被伪造 |
| `DATABASE_URL` | MySQL：`mysql+pymysql://zjpdt:口令@mysql:3306/zjpdt?charset=utf8mb4` | 写错 → 启动即失败（建表报错），`startup.log` 有全栈 |
| `FRONTEND_BASE` | 平台给的实际访问路径。根路径 `/`，子路径 `/record/` | 写错 → **认证回调 302 跳到错误地址**，登录后空白 |
| `ZHIJING_MODE` | 联调期 `mock`，拿到凭据后 `live` | 保持 `off` → 平台免登录完全不生效 |
| `ZHIJING_SYS_ID` | 资源管理器里的**系统标准码** | 空 → 审计 `checkSum` 算不出、`live` 模式认证必失败 |
| `ZHIJING_APP_KEY` / `ZHIJING_APP_SECRET` | 应用主键 AK / 密钥 SK | 同上 |
| `CORS_ORIGINS` | 实际访问来源。nginx 同源反代时可留本机 | 跨域时前端全接口 CORS 失败 |

### 4.2 建议一并处理的

| 变量 | 建议 | 原因 |
|---|---|---|
| `ZHIJING_AUDIT_ENABLED` | `true` | 规范要求**所有应用**接入审计；置 false 会积压本地台账 |
| `ZHIJING_AUTH_BUTTON` | 有 APPID 就填 | 配了才会做应用级鉴权；不填则跳过鉴权 |
| `SCAN_ROOT` | 设为白名单目录（如 `/data/scan`） | 不设则扫盘可读任意路径 |
| `ZHIJING_LEGACY_LOGIN` | **首次联调保持 `true`**，上架检测前改 `false` | 平台登录不通时，`super_admin` 还能用口令进去看 `/api/diag` |
| `ZHIJING_ORG_SYNC_ENABLED` | 按需 | 要同步省厅部门/警员才置 true（注意：见 §9 域定性提醒） |

### 4.3 联调期可以先跑 `mock`

`ZHIJING_MODE=mock` 时可以在**不接触平台**的前提下把"免登录进首页 → 审计留痕"整条链路自证：

```
https://<地址>/api/auth/zhijing/callback?police_no=33100400002&name=张三&as_admin=1
```

---

## 5. 证书

把正式证书放到 `deploy/certs/`，文件名必须是 `cert.pem` / `key.pem`（配置里写死）。
正式证书路径见 `nginx.zhijing.conf`。**自签证书仅限联调**（浏览器需手动信任；录音要求 HTTPS 安全上下文）。

自查：
```bash
openssl x509 -in deploy/certs/cert.pem -noout -subject -dates
```

---

## 6. 启动

```bash
cd <部署根>
docker compose ps                       # 确认没有同名旧容器
# 用 MySQL（不用则去掉 --profile mysql）
docker compose --profile mysql up -d --no-build
```

**务必加 `--no-build`**：离线环境里 `build` 一定会失败（拉不到基础镜像、装不了 npm 依赖）。
镜像已由 `load-offline.sh` 载入，`up` 直接用即可。

若报 `no such image`，说明镜像没载入或标签不符 —— 回到 §2 重新 `load-offline.sh`，并核对 `MANIFEST.txt`。

后端首次启动要建表 + 灌 282 个种子账号（bcrypt 较慢）：

```bash
docker compose logs -f backend
# 看到 "启动完成：后台循环已拉起" 与 "Application startup complete." 即就绪
```

---

## 7. 部署当天必须逐条过的验证

### 7.1 容器与进程

```bash
docker compose ps
# backend 应为 healthy；若一直 starting，看 docker compose logs backend
docker stats --no-stream
```

### 7.2 启动自检报告（**最重要的一条**）

启动时会自动生成报告，直接给结论：

```bash
cat logs/backend/startup.log
```

重点看两段：

```
【配置问题】
  - ZHIJING_MODE=off —— 平台免登录不会生效
  - SECRET_KEY 仍为默认值 —— 必须替换
  - ...
【可达性】
  认证服务: {"host":"lxrdl.gat.zj","port":5010,"resolved":"10.x.x.x","tcp":"ok"}
  审计服务: {"host":"41.188.255.179","port":9000,"resolved":"...","tcp":"..."}
```

`resolved` 字段是关键：**它显示 DNS 解析结果**。
- 出现 `198.18.x.x` → 是**代理 fake-IP**，不是真内网地址，DNS/代理没配对
- 出现 `<解析失败 ...>` → DNS 不通
- `tcp: fail(...)` → 解析通了但端口不通（防火墙/路由）

### 7.3 接口层

```bash
curl -sk https://127.0.0.1/api/health                  # {"status":"ok"}
curl -sk https://127.0.0.1/api/diag | head -60         # 数据库/外部服务/审计积压/日志大小
curl -sk https://127.0.0.1/api/zhijing/info            # 对接口径（给省厅看的）
docker compose exec web nginx -t                       # nginx 语法
```

### 7.4 免登录链路（联调核心）

`mock` 模式：

```bash
curl -sk -i "https://<地址>/api/auth/zhijing/callback?police_no=33100400002&name=测试&as_admin=1" | head -20
# 期望 303，Location 指向 https://<地址>/#/auth?token=...
```

成功后确认审计留痕：

```bash
grep "登录" logs/backend/app.log | tail -3
```

`live` 模式则由平台侧点开应用验证；用自己的账号走一遍，然后看：

```bash
tail -30 logs/backend/request.log     # 应出现 /api/auth/zhijing/callback 且 rz=1 / az=1
tail -30 logs/nginx/access.log        # 同一 trace= 的那一行
```

---

## 8. 出问题：收集日志回传

```bash
cd <部署根>
bash scripts/collect-logs.sh --url https://<地址> --since 24h
# 产出 logpack-<时间戳>.tar.gz
```

它收集：`/api/diag` 自检、后端全部日志、nginx 日志、docker 状态与 stdout、系统与版本、
证书有效期、**脱敏后的配置快照**。回传前请按保密要求确认。

排查顺序与对照表见 [诊断手册](./diagnose-playbook.md)。

---

## 9. ⚠️ 上线前必须确认的一件事：域定性

Skill 铁律 1：**需要访问省厅数据的应用必须申请数据域资源；无需访问的申请用户域资源。**

本项目判定为**用户域**的前提是：**人员信息由平台回调带过来，不主动拉省厅用户库**。

如果后来要接**统一用户/部门同步**（`ZHIJING_ORG_SYNC_ENABLED=true`，调 `deptIncrement`/`userIncrement`），
按规范应落**数据域**，那会连带改变：

| 项 | 用户域 | 数据域 |
|---|---|---|
| 认证服务 | `lxrdl.gat.zj:5010` | `rzfw.data.zj:5010` |
| 权限服务 | `lxrdl.gat.zj:5020` | `qxfw.data.zj:5020` |
| 审计服务 | `41.188.255.179:9000` | `139.3.6.101:9000` |
| 认证方式 | 动态秘钥（`dynamic`） | 令牌信息（`rzzx`） |
| 部署前置 | 无 | **必须先申请云桌面/堡垒机** |

**验证当前是哪个域**：看 `logs/backend/startup.log` 的「外部服务地址」段与传入的 `ZHIJING_RZ_URL`。

---

## 10. 已知约束

| 项 | 说明 |
|---|---|
| 浏览器 | 要求 Chromium 49+，实际按 **Chrome80** 构建并做了运行时 API 补齐（`npm run check:es-target`） |
| 录音上传 | 单请求上限 200MB（nginx `client_max_body_size`）；麦克风需 HTTPS |
| 日志留存 | 应用日志**每日轮转留 180 天**；规范要求本地留存不少于两年 → 宿主机侧需配 logrotate / 归档 |
| 审计批量 | 单批 ≤100 条 / ≤1M，且只能含同一类型日志（代码已按此裁剪） |
| 智慧运维 | **Matomo 埋点 / SLS-AIOS 日志采集 / GAPM 探针 / 浙警智评悬浮球 尚未接入**，上架前需补 |
| 数据更新 | 规范要求 ≤3 分钟；看板类页面不要写"实时" |

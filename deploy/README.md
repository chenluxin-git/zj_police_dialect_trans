# 部署一页纸（双容器）

> **离线内网部署请直接看 [`../docs/offline-deploy.md`](../docs/offline-deploy.md)**
> （内网不能 `docker pull`/`npm install`，不能 `--build`，必须走离线包）。
> 出问题看 [`../docs/diagnose-playbook.md`](../docs/diagnose-playbook.md)（现象 → 查哪个字段）。

交付包三形态（构建机出包，互不通用）：
- **整栈独立**（无宝塔裸机，https://IP/ 自签证书）：`scripts/export-stack-package.sh`，手册 `deploy/stack/DEPLOY.md`
- **宝塔子路径**（挂已有站点 /record/）：`scripts/export-record-package.sh`，手册 `deploy/record/DEPLOY.md`
- **legacy 离线整栈**（旧形式，未再演进）：`scripts/export-offline.sh`，手册 `docs/offline-deploy.md`

本页其余内容是**本机开发调试**用（根 compose 起停 + 冒烟清单），不是交付流程。

## 一次性准备

```bash
# 1. 自签证书（麦克风录音要求 HTTPS，浏览器首次访问点"继续前往"即可）
mkdir -p deploy/certs
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout deploy/certs/key.pem -out deploy/certs/cert.pem -subj "/CN=local"

# 2. 换 JWT 密钥（二选一：shell 变量注入，或改 server/.env.docker）
export SECRET_KEY=$(openssl rand -hex 32)
```

## 起停

```bash
docker compose up -d --build     # 首次构建+启动
docker compose logs -f backend   # 观察启动：建表 + seed 282 账号（bcrypt 慢，约 1-2 分钟）
                                # 看到 "Application startup complete." 即就绪
docker compose down              # 停止（数据保留在 app-data 卷）
docker compose down -v           # 停止并清空数据（慎）
```

## 冒烟清单（Spec §10，逐条过）

| # | 操作 | 预期 |
|---|---|---|
| 1 | 浏览器开 `https://<部署机IP>/` | 自签警告→继续→登录页 |
| 2 | `33100400002 / 123456` 登录 | 进首页，任务双卡 + 快捷入口 |
| 3 | 日常工作→去录音：领文本→录一段→上传 | 提示"已提交质检"；我的录音里状态**已通过**（ASR 空配置直通 passed），任务进度 +1 |
| 4 | 去标注：领音频→判定（是方言填译文）→提交 | 自动领下一条；我的标注可见记录 |
| 5 | 退出，`33000000001 / 123456` 登录 | 管理工作 12 项菜单出现 |
| 6 | 任务管理：给 33100400002 下达录音任务 10 条 | 提示成功；民警端重新登录后任务卡变化 + 站内信角标 |
| 7 | 消息发送：按区域发一条公告 | 民警端消息列表出现、角标 +1 |
| 8 | 数据总览 | 区域表有用户数，录音数随步骤 3 增加 |
| 9 | 数据导出：勾选→导出所选→等待任务完成→下载 | 得 ZIP（含 WAV + dataset.txt）；再次下载提示需重新打包（即焚） |

## 账号速查（seed 预置，密码均为 `123456`）

| 账号 | 角色 |
|---|---|
| `33000000001` | 超级管理员（全省） |
| `{市码}00001`（如 `3301000001`） | 市级管理员 |
| `{县码}00001`（如 `3310040001`） | 县级管理员 |
| `{县码}00002/00003` | 民警（每县 2 个） |

## 运维要点

- **数据备份**：音频/导出包/侧车台账在 `app-data` 卷（`/data/audio_storage` + `/data/exports` + `/data/text_imports` + `/data/audio_imports`；SQLite 形态时 `/data/app.db` 也在其中）；MySQL 形态时业务库在 `mysql-data` 卷。备份即两条：`docker run --rm -v zj_police_dialect_trans_app-data:/data -v $PWD:/bk alpine tar czf /bk/appdata.tgz /data` 与（MySQL 形态）`docker run --rm -v zj_police_dialect_trans_mysql-data:/data -v $PWD:/bk alpine tar czf /bk/mysql.tgz /data`
- **扫盘功能**：白名单根目录默认 `/data/scan`（`SCAN_ROOT`）——服务器扫盘导入只接受该目录内路径；用时先进卷建目录放音频：`docker compose exec backend mkdir -p /data/scan`
- **启用 ASR 质检**：`server/.env.docker` 填 `ASR_UPSTREAM_BASE=...`（契约 `POST {base}/asr?diarization=false`，超时 `ASR_TIMEOUT=300`）→ `docker compose up -d backend` 重建；留空时上传直通 passed
- **内网/离线机**：外网机 `docker save` 两个镜像拷入 `docker load`；npm/pip 已走国内镜像源（Dockerfile 内注明可改）
- **改密钥**：`SECRET_KEY` 变更后所有已发 token 立即失效（用户需重新登录），不影响数据
- **本机开发形态**：后端 `server/.venv/Scripts/python -m uvicorn app.main:app --port 8000`，前端 `web/` 下 `npm run dev`（vite 代理 /api → 8000，见 vite.config.ts）

## 浙警智治上架版（用户域 + 省厅零信任）

完整联调步骤见 [`../docs/deploy-zhijing-onboarding.md`](../docs/deploy-zhijing-onboarding.md)，这里只列**部署动作差异**。

### 1. 配置

```bash
# 用生产模板覆盖容器环境变量
cp server/.env.zhijing.docker.example server/.env.docker
# 必改：SECRET_KEY（openssl rand -hex 32）、DATABASE_URL 里的 MySQL 口令
# 联调阶段先把 ZHIJING_MODE 置 mock（免登录链路可自证），拿到凭据后改 live
```

### 2. 起停（含 MySQL）

```bash
docker compose --profile mysql up -d --build     # 正式形态（MySQL 8 + 后端 + nginx）
docker compose up -d --build                     # 只起后端+nginx（DATABASE_URL 指向 SQLite 卷时）
docker compose ps                                # backend 应为 healthy
```

### 3. 证书与域名

自签证书仅供内网联调；**上架必须换正式证书**，把证书放到 `deploy/certs/`（`cert.pem` / `key.pem`），
nginx 配置路径见 `deploy/nginx.zhijing.conf`。子路径部署（平台给的是 `https://域名/record/`）需要：

```bash
cd web && npm run build:record     # = vite build --mode record-demo --base=/record/ + 双自检
# 注意 npm run build -- --base= 的参数会被 npm 传给脚本末条命令，vite 收不到——必须用 build:record
# 后端 .env.docker 设 FRONTEND_BASE=/record/（认证回调 302 依赖它）
# 放开 deploy/nginx.zhijing.conf 里的 /record/ 段落后重建 web 容器
```

宝塔已有站点的服务器不走 web 容器，改用整包交付：`bash scripts/export-record-package.sh`
（前端静态由宝塔 nginx 直接服务，手册见 `deploy/record/DEPLOY.md`）。

### 4. 访问日志与留存（规范硬性：应用日志本地留存不少于两年）

`deploy/nginx.zhijing.conf` 已按**智慧运维规范**输出结构化访问日志（含 `$request_time`、
`$http_x_forwarded_for`、上游耗时/地址/状态），日志落在宿主机 `logs/nginx/`，应用日志落在 `logs/backend/`：

```bash
logs/nginx/access.log     # 前端 PV/UV、接口调用明细（SLS / AIOS-agent 采集对象）
logs/backend/startup.log  # 启动自检报告（配置齐备性 + 外部服务可达性）← 排障第一站
logs/backend/request.log  # 一行一请求（trace_id / 耗时 / 平台令牌有无）
logs/backend/client.log   # 前端上报（白屏 / JS 崩溃 / 接口失败）
logs/backend/app.log      # 应用日志（按天轮转，代码内 backupCount=180）
logs/backend/error.log
```

> 两年留存需要宿主机侧配合：给 `logs/` 配 logrotate 或对象存储归档策略，容器内轮转保留 **180 天**。
> 反馈给智慧运维的信息：**应用名称、后端服务器 IP 列表、日志路径**（见 §5）。

### 5. 联调自检（不用登录）

```bash
curl -sk https://<域名>/api/health                       # {"status":"ok"}
curl -sk https://<域名>/api/zhijing/info                 # 接入参数与地址可达性
curl -sk https://<域名>/api/auth/zhijing/self-check      # 模式/配置齐备性/审计积压/组织同步游标
```

开发机上可先跑一键预检（12 项，含免登录链路与审计留痕；默认不重建前端，避免与 dev server 抢文件锁）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\zhijing-preflight.ps1
```

拿到体检结果后把这几项反馈给省厅对接人：`callback_path`、`linkage_path`（= `/api/rzzx/linkage`）、
`mode`、`sys_id` 是否已配。

### 6. 数据库（SQLite → MySQL）切换

- 切换只需改 `DATABASE_URL`：`mysql+pymysql://用户:口令@mysql:3306/zjpdt?charset=utf8mb4`
- 建表与**自动加列**在启动时执行（`app/core/migrate.py`，只加列不改类型/约束），日志会打印实际 DDL
- **存量数据搬迁（一次性，勿用 CSV 手工导）**：仓库自带整库搬迁脚本（显式保主键 id、
  整型自增表自动顶 `AUTO_INCREMENT`、目标非空拒绝覆盖）：
  ```bash
  docker compose --profile mysql up -d mysql    # 先只起库
  docker compose run --rm backend python -m scripts.sqlite_to_mysql \
      --sqlite /data/app.db --mysql "$DATABASE_URL"
  docker compose --profile mysql up -d          # 起全家并按冒烟清单验证
  ```
  搬完逐表核对行数；`app.db` 源文件保持只读不动（回滚 = 把 `DATABASE_URL` 改回
  `sqlite:////data/app.db` 重建 backend）。真机演练记录见 `docs/plans/2026-09-23-mysql-docker-rehearsal.md`

### 7. 上架前必做

```bash
# 关闭过渡期口令登录（仅超管应急可用）
#   .env.docker: ZHIJING_LEGACY_LOGIN=false
# 清理演示账号/示例语料（登录页演示账号块仅在 dev 构建出现，生产构建已剔除）
# 浏览器兼容体检（构建时自动跑；也可单独执行）
cd web && npm run check:es-target && npm run check:polyfill
```

### 8. 部署当天先跑这三条校验

```bash
# a) nginx 配置语法（本机无 docker，必须在部署机确认）
docker compose exec web nginx -t
#    若报 "unknown directive http2"：nginx 版本 < 1.25.1，把配置里 `http2 on;` 换成
#    `listen 443 ssl http2;` 再 reload

# b) 容器健康
docker compose ps            # backend 应为 healthy

# c) 接入自检（见 §5）+ 访问日志格式
docker compose exec web tail -n 3 /var/log/nginx/access.log
#    应看到竖线分隔的 12 段字段（含耗时与 XFF），供智慧运维采集
```

---

## 已知边界

- 本开发机无 docker——本套件经静态核验（nginx 配置/构建上下文/卷路径），`compose up` 首验在部署机执行，按上方冒烟清单逐条确认
- 录音上传超过 100MB/请求 会被 nginx 拒（`client_max_body_size`，按需调）

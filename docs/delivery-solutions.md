# zjpdt 部署交付方案（宝塔子路径 / 整栈独立）

> 本文是**方案存档**：记录两种交付形态的选型、架构、交付物与已上线的实施记录，供交接与复盘。
> 服务器上的**分步操作手册**在各自交付包内的 `DEPLOY.md`（源件 `deploy/record/DEPLOY.md`、`deploy/stack/DEPLOY.md`），两者分工不同，本文不复述逐步命令。
>
> 交付包共三形态：**宝塔子路径**（§1）、**整栈独立**（§2）、legacy 离线整栈（`scripts/export-offline.sh`，旧形式未再演进，不在本文）。

## 0. 形态选型一览

| | 宝塔子路径 | 整栈独立 |
|---|---|---|
| 适用机器 | 已有对外网站（宝塔/nginx）的生产服务器 | 只有 docker 的裸机/内网新机器 |
| 访问入口 | `https://已有域名/record/`（复用主站证书） | `https://服务器IP/`（自签证书，可换正式） |
| 容器 | backend + mysql（2 个） | backend + web + mysql（3 个） |
| 前端由谁服务 | 宝塔 nginx 直接服务站点根下静态文件 | web 容器内置 nginx 直出 + 反代 `/api/` |
| 对外端口 | 0 个新增（backend 只绑 127.0.0.1:8002，mysql 不发布） | 80/443（`HTTP_PORT/HTTPS_PORT` 可改） |
| 前端构建 base | `/record/`（断言 index.html 引用 `/record/` 开头） | `/`（断言引用 `/assets/` 开头） |
| 首装脚本 | `install.sh --domain <域名>`（含 nginx 接入） | `install.sh --cn <IP|域名>`（含自签证书） |
| 增量升级包 | `zjpdt-backend-*.tar.gz` + `record_web*.tar.gz` | `zjpdt-backend-*.tar.gz` + `zjpdt-web-*.tar.gz` |
| 种子单位补挂 | update.sh 内置 SQL（修历史库） | 不需要（现版 seed.py 首启即挂单位） |

两形态共用同一套镜像与加固约定：`zjpdt-backend:latest`（FastAPI+ffmpeg）、web 侧按形态不同；compose 顶层 `name:` 锁卷名、密钥 `:?` 无默认（缺密钥拒绝启动）、TZ=Asia/Shanghai、healthcheck、日志 json-file 50m×3、restart: always、mysql utf8mb4/+08:00 且**永不发布端口**。

## 1. 宝塔子路径形态（tailect.cn/record/，2026-09-23 已上线）

### 1.1 架构

前端静态文件由宝塔 nginx 在站点根下直接服务（`/www/wwwroot/tailect.cn/record/`）；
Docker 只跑 backend（绑 `127.0.0.1:8002`，宝塔站点配置追加 location 把 `/record/api/` 反代过来）
和 mysql（不发布端口）。**全程不动现有站点既有配置**，唯一改动是往站点 conf 追加一段 location（有备份，删掉即回滚）；公网零新增入站。

### 1.2 交付物

- **整包（新机器首装）**：`zjpdt-record-pkg-20260924-152625.tar.gz`，459M，sha256 前 16 位 `a122228db34fdf50`。
  含 backend+mysql 两镜像、compose（项目名 `zjpdt-record`）、`.env.template`、`server/.env.docker`、
  `record_web.tar.gz`、`nginx-record.conf` 片段、`load.sh`/`install.sh`/`update.sh`、`DEPLOY.md`、`MANIFEST.txt`。
- **增量三件套（已部署机器升级）**，放 `dist-record/upload-20260923-232121/`：
  - `zjpdt-backend-20260923-232121.tar.gz` 235M（sha `706270edaebea257`）
  - `record_web-20260923-232121.tar.gz` 489K（sha `4cb32b308c2b2954`）
  - `deploy/record/update.sh`
  - 只改前端时传 489K 小包即可；出包命令 `bash scripts/export-record-package.sh`。

### 1.3 服务器布局（实测）

- 后端部署目录：`/opt/zjpdt-record`（compose 项目 zjpdt-record；**不是** /root/zjpdt-record——那只是历史解压目录）
- 前端静态：`/www/wwwroot/tailect.cn/record`（chown www:www）
- 升级包中转：`/root/upload/`（三个文件放同一目录后 `bash update.sh`）

### 1.4 首装与升级流程

- 首装（新机器）：解包后在包根 `bash install.sh --domain <域名>`
  （默认 tailect.cn；`--web-root/--app-dir/--skip-nginx` 可覆盖）。自动：预检→load.sh 导镜像+探针→建部署目录
  →openssl 随机三密钥写 `.env`（600，已存在保留）→compose up 等 mysql/backend healthy→前端解压站点根 chown www
  →nginx 片段渲染插入宝塔 vhost（先备份，`nginx -t` 不过自动还原）。
- 升级（已部署机器）：三件套放 `/root/upload/`，`bash update.sh`（`--no-backfill` 跳过补挂）。
  内置：mysqldump 全量备库（内容级校验）→旧镜像打 `rollback-YYYYMMDD` 回滚点（同日不覆盖）→docker load
  →compose up→健康等待失败自动回滚→种子民警补挂单位 SQL（幂等，只补空值）→前端 `record.old-*` 备份后替换+校验 base。

### 1.5 上线记录与环境实测坑（2026-09-23）

- 上线版本：9792e79「消息发送·按单位三级级联多选」，后端镜像 `4e0dae752d38`，工具链至 a34f946。
- 种子民警补挂单位 40 人 = 真实 20 区县×2（单位表 696 条中 129 条挂 10 个演示伪区划码如 `330400_JC`，UI 不可见无用户，勿当真实数据统计）。
- 该服务器（OpenCloudOS + mysql:8.0）三个坑，已全部写进脚本与手册：
  1. `docker compose exec -T` **不回传容器内退出码**（mysql 报 ERROR 仍 exit=0）→ 一律内容级校验
     （备份 zgrep `Dump completed`、SQL 输出标记 grep）；
  2. zjpdt 用户只有库级权限无全局 PROCESS → mysqldump 必须 `--no-tablespaces`；
  3. 容器无 locale，mysql 客户端按 latin1 解释语句 → 必须 `--default-character-set=utf8mb4`，否则中文 1064/写库乱码。
- 遗留待办：宝塔每日备份计划任务补 `--no-tablespaces --default-character-set=utf8mb4`；轮换 MYSQL_PASSWORD（曾在命令行暴露）；超管 33000000001 改密。

## 2. 整栈独立形态（无宝塔裸机，2026-09-24 交付）

### 2.1 架构

backend + web + mysql 三容器自成一体：web 镜像 = node24 容器内构建的前端 dist 打进 nginx:alpine，
站点配置用上架版 `deploy/nginx.zhijing.conf`（安全头/200m 上传/结构化访问日志/JSON 错误信封），
直出前端并反代 `/api/` → backend:8000。宿主机除 docker 零依赖；对外仅发布 web 的 80/443
（80 只做 301，443 唯一入口）；backend 只在 compose 网内 expose，mysql 永不发布端口。
HTTPS 用自签证书（麦克风录音要求安全上下文），install.sh 自动生成（openssl≥1.1.1 连 SAN 一起签），
换正式证书 = 覆盖 `certs/` 两文件后 `docker compose up -d`。

### 2.2 交付物

- **整包**：`dist-stack/zjpdt-stack-pkg-20260924-155314.tar.gz`，484M，sha256 前 16 位 `807f5eeadd081cb6`，Git 308236c。
  含 backend+web+mysql 三镜像、compose（项目名 `zjpdt-stack`）、`.env.template`（密钥+端口）、
  `server/.env.docker`、`nginx-site.conf`、`load.sh`/`install.sh`/`update.sh`、`DEPLOY.md`、`MANIFEST.txt`。
- **增量包（已部署机器升级）**：`zjpdt-backend-*.tar.gz` + `zjpdt-web-*.tar.gz` 两类（前端打进镜像，无落盘换文件步骤）；
  出包命令 `bash scripts/export-stack-package.sh`。

### 2.3 首装与升级流程

- 首装：解包后包根 `bash install.sh`（默认 `/opt/zjpdt-stack`、80/443、证书 CN=自动探测本机 IP；
  `--cn/--http-port/--https-port/--app-dir` 覆盖，端口被占首装硬校验拒绝）。自动：预检→load.sh 三镜像
  +ffmpeg/TZ/前端 base 探针→随机三密钥 `.env`（600，已存在保留，端口以 .env 为准）→自签 10 年证书（已存在不重签）
  →compose up→按 compose 服务名等 mysql 150s/backend 240s→全链验证（穿 web 443 的 `/api/health`+首页 200+80→301）。
  完成后需防火墙/安全组放行 80、443；浏览器首访自签告警「高级→继续前往」。
- 升级：两类镜像包与 `update.sh` 放同一目录 `bash update.sh`（默认 `APP_DIR=/opt/zjpdt-stack`）。
  内置：备库（同 1.4 口径）→backend/web 双镜像回滚点（同日不覆盖）→load（输出 grep 校验）→up
  →穿 443 全链健康等待，失败自动回滚双镜像。
- **与宝塔形态的关键差异**：新库首启种子自带单位归属（seed.py `station_by_phone`，20 区县×2=40），
  **无需补挂 SQL**；没有前端落盘与 nginx 接入步骤。

### 2.4 验证记录（本地沙箱 e2e，2026-09-24）

全新卷首装：mysql healthy 17 秒 → backend 建库+282 种子账号 72 秒 → 穿 web 容器 443 的 `/api/health` ✓、
首页 200 ✓、80→301 ✓、超管登录返回 JWT ✓、users=282 / 单位挂 40 ✓、静态资源 immutable 缓存头 ✓；
幂等重跑（.env/证书保留）✓；update.sh 无包拒跑 / web 包升级闭环 / 同日回滚点保护 ✓；
负测：未知参数、包不完整、端口被占 ✓；出包镜像内代码与仓库 HEAD 校验和全等 ✓。

## 3. 两形态通用红线与运维约定

1. 密钥：三密钥必改且只用 hex 随机串（勿含 `@ : / ? #`）；只存包根 `.env`（600）；`MYSQL_PASSWORD` 仅首启生效，改密走 ALTER USER 流程。
2. 种子账号：282 个密码全是 `123456`（1 超管+11 市管+90 县管+180 民警），超管首登立即改密，正式启用前评估清理演示账号。
3. 端口：宝塔形态 backend 绝不改绑 0.0.0.0；整栈形态对外仅 web 的 80/443；mysql 任何形态都不发布端口。
4. 备份：每日 mysqldump（`--no-tablespaces --default-character-set=utf8mb4` + `zgrep 'Dump completed'` 自检）+ 每周 app-data 卷归档。
5. HTTPS：麦克风录音要求安全上下文，任何形态都不用 http:// 提供页面（80 一律 301）。
6. 出包纪律：**先 commit 再出包**（否则 MANIFEST 盖旧提交号）；后台跑出包脚本不接 `| tail`（管道吃退出码，踩过一次）。

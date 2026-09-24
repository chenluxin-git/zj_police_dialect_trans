# 整栈独立部署手册（无宝塔，https://服务器IP/）

> 目标：在**只有 Docker** 的裸机器上把「浙江公安方言语料采集平台」整套跑起来，不装宝塔、
> 不装主机 nginx、不依赖任何已有站点。三个容器（backend + web + mysql）自成一体：
> web 容器内置 nginx，直接服务前端页面并把 `/api/` 反代给 backend；对外只发布 80/443 两个端口。
>
> 与宝塔子路径形态（tailect.cn/record/，见 deploy/record/）的取舍：那台是对外生产机、复用主站 HTTPS；
> 本形态适合独立/内网新机器——**必须**放行 80/443 入站，HTTPS 用自签证书（麦克风录音要求
> 安全上下文；正式证书可事后替换，§8）。

## 0. 包内容与三条铁律

```
zjpdt-stack-pkg-<时间戳>/
├── images/zjpdt-backend.tar    后端镜像（FastAPI + ffmpeg）
├── images/zjpdt-web.tar        前端镜像（Vue 产物打进 nginx:alpine，根路径构建）
├── images/mysql-8.0.tar        MySQL 8 镜像
├── docker-compose.yml          编排（backend + web + mysql；项目名锁死 zjpdt-stack）
├── .env.template               → cp 为 .env，整个部署唯一必须改的文件（三个密钥+端口）
├── server/.env.docker          应用运行默认值（无密钥，一般不动）
├── nginx-site.conf             web 容器站点配置（安全头/200m 上传/结构化访问日志）
├── load.sh                     镜像导入 + 自检
├── install.sh                  一键首装
├── update.sh                   增量升级一键脚本
├── DEPLOY.md                   本手册
└── MANIFEST.txt                各文件 sha256 + 打包 git 版本
```

**铁律一**：所有 `docker compose` 命令都在部署目录（默认 `/opt/zjpdt-stack`）执行
（`env_file`、`./certs`、`./logs` 相对路径以 compose 文件为基准）。
**铁律二**：必须 Docker Compose **v2**（`docker compose version` 能出结果；python 版 docker-compose v1 不认本编排）。
**铁律三**：mysql **永不发布端口**（备份/改密走 `docker compose exec`，密码不落宿主机命令行）；
backend 只在容器网内可见，对外唯一入口是 web 的 80/443。

## 0.1 一键首装（推荐；等价于 §1-§7 全部手动步骤）

交付包解压后，在**包根目录**执行：

```bash
bash install.sh                          # 默认 /opt/zjpdt-stack、端口 80/443、证书 CN=自动探测的本机 IP
bash install.sh --cn 10.0.0.5            # 浏览器用 IP 访问就填 IP；用域名就填域名（只影响证书 CN）
bash install.sh --https-port 8443        # 443 被占用时换端口（80 同理 --http-port）
```

脚本自动：预检（docker / 包完整性 / 端口空闲 / 磁盘）→ load.sh 导镜像+探针 → 建部署目录 →
openssl 随机生成三个密钥写入 `.env`（600 权限，已存在则保留不覆盖）→ 自签 10 年 HTTPS 证书 →
`docker compose up -d` → 等 mysql/backend 双 healthy（首启建库+282 种子账号约 1-4 分钟）→
全链验证（穿 web 容器的 `/api/health` + 首页 200 + 80→443 跳转）。
幂等可重复执行（.env/证书保留不覆盖）。完成后照 **§7** 逐条验证 + **放行防火墙 80/443**。

## 1. 前置检查（SSH 到服务器）

```bash
docker --version && docker compose version   # 缺 Docker：curl -fsSL https://get.docker.com | sh && systemctl enable --now docker
ss -lntp | grep -E ':(80|443)\b'             # 应无输出（或用 --http-port/--https-port 换端口）
docker ps -a | grep zjpdt                    # 应无输出（无旧容器/旧卷残留）
df -h /var/lib/docker                        # 剩余空间 ≥ 10G（镜像 ~2.2G + 数据增长）
```

与宝塔形态相反，本形态**要**在防火墙/云安全组放行 TCP 80、443（80 只做跳转，443 是唯一入口）：

```bash
# firewalld 示例（云服务器还要在控制台安全组放行）：
firewall-cmd --add-port=80/tcp --add-port=443/tcp --permanent && firewall-cmd --reload
```

## 2. 上传与解包

**部署包 tar.gz（数百 MB）必须走 SFTP/scp/rsync**，别用网页上传。

```bash
# 上传 zjpdt-stack-pkg-<时间戳>.tar.gz 到 /opt/ 后：
cd /opt && tar -xzf zjpdt-stack-pkg-*.tar.gz
mv zjpdt-stack-pkg-<时间戳> zjpdt-stack && cd zjpdt-stack
sha256sum -c <(grep -E 'images/' MANIFEST.txt)   # 核对传输完整性
```

## 3. 导入镜像

```bash
bash load.sh     # docker load ×3 + 标签校验 + ffmpeg/TZ/前端 base 探针，全部 OK 再往下
```

## 4. 配置（唯一要改的文件）

```bash
cp .env.template .env
openssl rand -hex 32     # 结果填 SECRET_KEY
openssl rand -hex 16     # 结果填 MYSQL_ROOT_PASSWORD
openssl rand -hex 16     # 结果填 MYSQL_PASSWORD（重新生成，别和上面复用）
vi .env
```

要点：

- 密码**只用 hex 随机串**，勿含 `@ : / ? #` 等字符（会破坏 DATABASE_URL 拼接）。
- `DATABASE_URL` 不用你填——compose 会用 `MYSQL_PASSWORD` 自动拼，密码只存 `.env` 一处。
- 忘填任何一个密钥：`docker compose` 直接拒绝执行并提示（编排里是 `:?` 无默认值，这是故意的）。
- `MYSQL_PASSWORD` 只在 MySQL **首次初始化**生效；之后改密走 §9.3。
- `HTTP_PORT/HTTPS_PORT` 默认 80/443；被占用时改这里（防火墙记得放行改后的端口）。
- `ASR_UPSTREAM_BASE` 已预填内网穿透隧道地址，§7 有验证步骤；换地址 = 改这里 + `docker compose up -d`；
  置空 = 质检直通 passed（录音上传不受影响，仅不做转写比对）。

## 5. 自签 HTTPS 证书

麦克风录音（MediaRecorder）要求 HTTPS 安全上下文；内网/独立机没有正式证书，先用自签：

```bash
mkdir -p certs && openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout certs/key.pem -out certs/cert.pem -subj "/CN=服务器IP" \
  -addext "subjectAltName=DNS:服务器IP,IP:服务器IP"
chmod 600 certs/key.pem
```

浏览器首次访问会告警，点「高级 → 继续前往」即可，录音功能不受影响。
换正式证书 = 覆盖 `certs/cert.pem`、`certs/key.pem` 后 `docker compose up -d`（§8）。

## 6. 启动

```bash
cd /opt/zjpdt-stack           # §2 已把包目录改名为此；.env / certs / nginx-site.conf 都在里面
docker compose up -d          # 不要加 --build（服务器离线，构建不了）
docker compose ps             # 等 mysql 先 healthy，backend 跟着转 healthy，web 常驻 running（约 1-4 分钟）
docker compose logs -f backend   # 看到「启动完成：后台循环已拉起」即就绪；Ctrl+C 退出跟随
cat logs/backend/startup.log     # 启动自检报告，【配置问题】段应为空或仅提示性条目
```

## 7. 全链验证（逐条过，全绿才算部署完成）

```bash
curl -k https://127.0.0.1/api/health                                # {"status":"ok"}（穿 web 容器 → backend）
curl -sI http://127.0.0.1/ | head -1                                # 301（跳 https）
curl -kI https://127.0.0.1/ | head -1                               # 200（前端由 web 容器直出）
curl -X POST -k https://127.0.0.1/api/auth/login -H 'Content-Type: application/json' \
     -d '{"phone":"33000000001","password":"123456"}'               # 返回 data.token（JWT）
docker compose exec mysql sh -c 'exec mysql -uzjpdt -p"$MYSQL_PASSWORD" zjpdt -e "SELECT COUNT(*) FROM users;"'
# = 282（全新库自动种子：1 超管 + 11 市管 + 90 县管 + 180 民警；密码全部是 123456，见 §11 红线）
# ASR 上游可达性（在服务器上）：
curl -k -X POST 'https://1plxo01525881.vicp.fun/asr?diarization=false' -F 'file=@/tmp/test.webm'   # {"text":...}
```

浏览器（用 Chrome 80+，从办公网访问 `https://服务器IP/`）：

1. 首次有证书告警（自签）→「高级 → 继续前往」→ 登录页（无白屏、样式正常）；
2. `33000000001 / 123456` 登录 → 管理工作菜单出现；**登录后立即改密**（§11）；
3. 换民警账号录一段音上传 → 「已提交质检」→（ASR 已接通时）稍后质检状态变化；
4. 管理端 数据导出 → 下载 ZIP 成功（验 `proxy_buffering off`）；
5. 重启自愈：`systemctl restart docker`（或计划内 reboot）后 `docker compose ps` 三容器自动回来（restart: always）。

## 8. 换正式证书

拿到正式证书（如单位统一签发）后原地覆盖即可，无需改配置：

```bash
cd /opt/zjpdt-stack
cp certs/cert.pem certs/cert.pem.bak-$(date +%F) && cp certs/key.pem certs/key.pem.bak-$(date +%F)
# 新证书放同名文件（PEM 格式；若证书链是分开的多文件，cert.pem = 证书+中间证拼接）
docker compose restart web
curl -kI https://服务器IP/     # 200，且浏览器不再告警
```

## 9. 运维

### 9.1 日志

```bash
logs/backend/app.log        # 应用日志（按天轮转，容器内保留 180 天）
logs/backend/request.log    # 一行一请求（trace_id / 耗时 / 真实 IP）
logs/backend/startup.log    # 启动自检报告 ← 排障第一站
logs/nginx/access.log       # web 容器访问日志（结构化格式：耗时/上游/trace）
docker compose logs --tail 100 backend   # 容器 stdout（json-file，已限 50m×3）
```

规范要求应用日志留存两年：给 `logs/` 配归档任务（logrotate 或 tar 到备份盘）。

### 9.2 备份（建 cron/计划任务）

```bash
# 每日 mysqldump（密码在容器环境里，宿主机不落明文）：
# --no-tablespaces 必须给：zjpdt 用户无全局 PROCESS 权限，8.0.21+ 缺省会报 "Access denied; you need PROCESS privilege" 中断
# 收尾自检：zgrep -q 'Dump completed' 备份文件（部分 compose exec 不回传容器退出码，别只看命令返回值）
mkdir -p /opt/backup && cd /opt/zjpdt-stack && docker compose exec -T mysql sh -c 'exec mysqldump --no-tablespaces --default-character-set=utf8mb4 -uzjpdt -p"$MYSQL_PASSWORD" --single-transaction zjpdt' | gzip > /opt/backup/zjpdt-db-$(date +%F).sql.gz
# 每周音频/导出卷（zjpdt-stack_app-data 卷）：
docker run --rm -v zjpdt-stack_app-data:/data -v /opt/backup:/bk alpine tar czf /bk/zjpdt-appdata-$(date +%F).tgz /data
```

### 9.3 改 MySQL 密码（.env 里的密码首启后即失效，改这里没用）

```bash
docker compose exec mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "ALTER USER '"'"'zjpdt'"'"'@'"'"'%'"'"' IDENTIFIED BY \"新密码\";"'
vi .env        # MYSQL_PASSWORD 同步为新密码
docker compose up -d    # 重建 backend 生效
```

### 9.4 升级（新交付包）

**推荐：增量分包 + 一键脚本。** 后端镜像包（`zjpdt-backend-<时间戳>.tar.gz`）与前端镜像包
（`zjpdt-web-<时间戳>.tar.gz`）是两个独立文件，与 `update.sh` 放同一目录（如 `/root/upload/`）执行：

```bash
bash update.sh               # 有什么包升什么；两个都在则一起升（替换镜像 → 统一重启 → 全链验证）
```

脚本内置：库备份（内容级校验）→ 镜像回滚点 → docker load → compose up →
全链健康等待（失败自动回滚镜像）。默认作用于 `APP_DIR=/opt/zjpdt-stack`，
部署在别处时 `APP_DIR=... bash update.sh` 覆盖。

**手动等价流程**（脚本不可用时）：

```bash
docker tag zjpdt-backend:latest zjpdt-backend:rollback-$(date +%Y%m%d)    # 先保回滚点
docker tag zjpdt-web:latest     zjpdt-web:rollback-$(date +%Y%m%d)
<按 §9.2 做一次全量备份>
docker load -i zjpdt-backend-<时间戳>.tar.gz       # 前端同理 zjpdt-web-*
cd /opt/zjpdt-stack && docker compose up -d
curl -k https://127.0.0.1/api/health               # 验证 §7 全绿后删除 rollback 镜像
```

## 10. 回滚

- 后端：`docker tag zjpdt-backend:rollback-YYYYMMDD zjpdt-backend:latest && docker compose up -d`
- 前端：`docker tag zjpdt-web:rollback-YYYYMMDD zjpdt-web:latest && docker compose up -d`
- 数据库：`docker compose exec -T mysql sh -c 'exec mysql --default-character-set=utf8mb4 -uzjpdt -p"$MYSQL_PASSWORD" zjpdt' < 备份.sql`
- 证书：还原 §8 的 `.bak-*` 文件后 `docker compose restart web`

## 11. 红线（违反任何一条都是事故）

1. **对外只发布 web 容器的 80/443**——backend/mysql 一律不发布端口（临时调试也只进容器，
   不要给 mysql 加 ports 映射）。
2. **三个密钥必改**（.env 里的 `<改我>` 不换，compose 会拒绝启动——这是机制不是建议）。
3. **282 个种子账号密码全是 `123456`**：超管首登立即改密；市/县管理员账号尽快改；
   正式启用前评估是否清理演示民警账号。
4. 麦克风录音要求 HTTPS 安全上下文——自签证书浏览器「继续前往」即满足，
   **不要**想法子用 http:// 提供页面（80 端口已强制 301 到 https）。
5. `.env` 与 `certs/key.pem` 权限保持 600，勿入库、勿外传。

## 12. 已知约束

- 浏览器基线 Chrome 80+（构建已做语法体检，polyfills 自动补齐）；
- 单请求上限 200MB（录音/导入；nginx `client_max_body_size` 与后端一致）；
- 数据总览等统计非实时（分钟级）；
- ASR 上游是内网穿透隧道（vicp.fun），可能漂移失效——失效表现是质检一直 retry，换地址流程见 §4 末条；
- 自签证书期间浏览器每次访问都会告警（属预期），内部分发可导出 `certs/cert.pem` 让各终端信任一次。

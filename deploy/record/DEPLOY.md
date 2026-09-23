# 宝塔子路径部署手册（tailect.cn/record/）

> 目标：把「浙江公安方言语料采集平台」以 Docker 容器部署到已有网站（tailect.cn）的宝塔服务器上，
> 作为子路径 `https://tailect.cn/record/` 访问。**全程不动现有站点的任何配置与数据**——
> 唯一对宝塔 nginx 的改动是往站点配置里**追加**一段 location（粘贴前有备份，删掉即回滚）。
>
> 架构：前端静态文件由宝塔 nginx 直接服务（站点根/record/）；Docker 只跑后端 API（127.0.0.1:8002）
> 和 MySQL（不发布端口）。所有端口只绑回环，公网零新增入站，不改防火墙/安全组。

## 0. 包内容与三条铁律

```
zjpdt-record-pkg-<时间戳>/
├── images/zjpdt-backend.tar    后端镜像（FastAPI + ffmpeg）
├── images/mysql-8.0.tar        MySQL 8 镜像
├── docker-compose.yml          编排（backend + mysql；项目名锁死 zjpdt-record）
├── .env.template               → cp 为 .env，整个部署唯一必须改的文件（三个密钥）
├── server/.env.docker          应用运行默认值（无密钥，一般不动）
├── record_web.tar.gz           前端产物（解到 站点根/，形成 record/ 子目录）
├── nginx-record.conf           宝塔站点要追加的 location 片段
├── load.sh                     镜像导入 + 自检
├── DEPLOY.md                   本手册
└── MANIFEST.txt                各文件 sha256 + 打包 git 版本
```

**铁律一**：所有 `docker compose` 命令都在包根目录执行（`env_file`、`./logs` 相对路径以 compose 文件为基准）。
**铁律二**：必须 Docker Compose **v2**（`docker compose version` 能出结果；python 版 docker-compose v1 不认本编排）。
**铁律三**：解压目录固定为 `/opt/zjpdt-record`（卷名已被编排锁死为 `zjpdt-record_*`，固定路径是双保险，也方便日后找）。

## 1. 前置检查（SSH 到服务器）

```bash
docker --version && docker compose version   # 缺 Docker：宝塔"Docker 管理"应用安装，或 curl -fsSL https://get.docker.com | sh
ss -lntp | grep -E ':(8002|3307)\b'          # 应无输出（8002 空闲；3307 默认根本不用）
docker ps -a | grep zjpdt                    # 应无输出（无旧容器/旧卷残留）
df -h /var/lib/docker                        # 剩余空间 ≥ 10G（镜像 ~2.1G + 数据增长）
```

确认心智：本操作只在站点 conf **追加**一个 location 片段、在站点根**新增**一个 record/ 目录，
不修改、不移动任何现有文件。

## 2. 上传与解包

**部署包 tar.gz（数百 MB）必须走 SFTP/scp/rsync**——超过宝塔面板网页上传上限（默认 100MB）且 PHP 易超时。
前端包 `record_web.tar.gz`（<1MB）可以走面板上传。

```bash
# 上传 zjpdt-record-pkg-<时间戳>.tar.gz 到 /opt/ 后：
cd /opt && tar -xzf zjpdt-record-pkg-*.tar.gz
mv zjpdt-record-pkg-<时间戳> zjpdt-record && cd zjpdt-record
sha256sum -c <(grep -E 'images/|record_web' MANIFEST.txt)   # 核对传输完整性
```

## 3. 导入镜像

```bash
bash load.sh     # docker load ×2 + 标签校验 + ffmpeg/TZ 探针，全部 OK 再往下
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
- `MYSQL_PASSWORD` 只在 MySQL **首次初始化**生效；之后改密走 §10.3。
- `ASR_UPSTREAM_BASE` 已预填内网穿透隧道地址，§9 有验证步骤；换地址 = 改这里 + `docker compose up -d`。

## 5. 启动

```bash
docker compose up -d          # 不要加 --build（服务器离线，构建不了）
docker compose ps             # 等 mysql 先 healthy，backend 跟着转 healthy（首启建表+种子约 1-2 分钟，bcrypt 慢是正常）
docker compose logs -f backend   # 看到「启动完成：后台循环已拉起」即就绪；Ctrl+C 退出跟随
cat logs/backend/startup.log     # 启动自检报告，【配置问题】段应为空或仅提示性条目
```

## 6. 后端直连验证（还没接 nginx 前先证明容器本身是好的）

```bash
curl 127.0.0.1:8002/api/health    # {"status":"ok"}
curl -X POST 127.0.0.1:8002/api/auth/login -H 'Content-Type: application/json' \
     -d '{"phone":"33000000001","password":"123456"}'            # 返回 data.token（JWT）
docker compose exec mysql sh -c 'exec mysql -uzjpdt -p"$MYSQL_PASSWORD" zjpdt -e "SELECT COUNT(*) FROM users;"'
# = 282（全新库自动种子：1 超管 + 11 市管 + 90 县管 + 180 民警；密码全部是 123456，见 §11 红线）
docker compose exec backend date    # 应为 CST +0800 本地时间（TZ 修复生效）
```

## 7. 前端部署（站点根 + record/ 子目录）

```bash
# 站点根以实际为准（宝塔默认 /www/wwwroot/tailect.cn；面板 → 网站 → tailect.cn 可查"根目录"）
tar -xzf record_web.tar.gz -C /www/wwwroot/tailect.cn/    # 生成 /www/wwwroot/tailect.cn/record/
chown -R www:www /www/wwwroot/tailect.cn/record           # 宝塔 nginx worker 跑 www 用户
ls /www/wwwroot/tailect.cn/record/                        # 应有 index.html、assets/、favicon.svg
```

## 8. nginx 接入（唯一动宝塔的一步）

```bash
cp /www/server/panel/vhost/nginx/tailect.cn.conf{,.bak-zjpdt-$(date +%F)}   # 先备份！回滚=还原此文件
```

面板 → 网站 → tailect.cn → 设置 → **配置文件**，把 `nginx-record.conf` 的内容粘贴到
`listen 443 ssl` 的 `server{}` 内、**最后一个 `}` 之前**；粘贴前把其中两处 `<站点根>`
替换为实际路径。保存（面板自动 `nginx -t` + 重载），或命令行等效：

```bash
/www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload
# 宝塔若装的是 OpenResty，路径为 /usr/local/openresty/nginx/sbin/nginx，语法同理
```

装了宝塔 WAF（nginx 免费防火墙）的：给 `/record/api/` 加 URL 白名单——它的 POST body 检查
可能拦 200MB 录音上传或多文件接口，症状是 403/被 Challenge，与后端无关。

## 9. 全链验证（逐条过，全绿才算部署完成）

```bash
curl https://tailect.cn/record/api/health                                  # ok（经主站 HTTPS 反代）
curl -I https://tailect.cn/record                                          # 301 → /record/
curl -I https://tailect.cn/record/assets/$(ls /www/wwwroot/tailect.cn/record/assets | head -1)   # 200 + immutable
# ASR 上游可达性（在服务器上）：
curl -k -X POST 'https://1plxo01525881.vicp.fun/asr?diarization=false' -F 'file=@/tmp/test.webm'   # {"text":...}
```

浏览器（用 Chrome 80+）：

1. 开 `https://tailect.cn/record/` → 登录页（无白屏、样式正常 = base 正确）；
2. `33000000001 / 123456` 登录 → 管理工作菜单出现；**登录后立即改密**（§11）；
3. 换民警账号录一段音上传 → 「已提交质检」→（ASR 已接通时）稍后质检状态变化；
4. 管理端 数据导出 → 下载 ZIP 成功（验 `proxy_buffering off`）；
5. **主站回归**：`curl -I https://tailect.cn/` 主站照常、error.log 无新增报错——这是"不影响现有站点"的验收项；
6. 重启自愈：`systemctl restart docker`（或计划内 reboot）后 `docker compose ps` 双容器自动回来（restart: always）。

## 10. 运维

### 10.1 日志

```bash
logs/backend/app.log        # 应用日志（按天轮转，容器内保留 180 天）
logs/backend/request.log    # 一行一请求（trace_id / 耗时 / 真实 IP）
logs/backend/startup.log    # 启动自检报告 ← 排障第一站
logs/backend/error.log
docker compose logs --tail 100 backend     # 容器 stdout（json-file，已限 50m×3）
```

规范要求应用日志留存两年：给 `logs/` 配宝塔计划任务（logrotate 或 tar 归档到备份盘）。

### 10.2 备份（放宝塔「计划任务」，别手塞 crontab——面板里看得见）

```bash
# 每日 mysqldump（密码在容器环境里，宿主机不落明文）：
cd /opt/zjpdt-record && docker compose exec -T mysql sh -c 'exec mysqldump -uzjpdt -p"$MYSQL_PASSWORD" --single-transaction zjpdt' | gzip > /www/backup/zjpdt-db-$(date +%F).sql.gz
# 每周音频/导出卷（zjpdt-record_app-data 卷）：
docker run --rm -v zjpdt-record_app-data:/data -v /www/backup:/bk alpine tar czf /bk/zjpdt-appdata-$(date +%F).tgz /data
```

### 10.3 改 MySQL 密码（.env 里的密码首启后即失效，改这里没用）

```bash
docker compose exec mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "ALTER USER '"'"'zjpdt'"'"'@'"'"'%'"'"' IDENTIFIED BY \"新密码\";"'
vi .env        # MYSQL_PASSWORD 同步为新密码
docker compose up -d    # 重建 backend 生效
```

### 10.4 升级（新交付包）

**推荐：增量分包 + 一键脚本。** 后端镜像包（`zjpdt-backend-<时间戳>.tar.gz`，docker save 后 gzip）
与前端包（`record_web<-.时间戳>.tar.gz`）是两个独立文件，与 `update.sh` 放同一目录（如 `/root/upload/`）执行：

```bash
bash update.sh               # 有什么包升什么；两个都在则先 backend 后 frontend
bash update.sh --no-backfill # 跳过种子民警补挂单位（默认自动执行，幂等只补空值）
```

脚本内置：库备份 → 镜像回滚点 → docker load → compose up → 健康等待（失败自动回滚镜像）
→ 补挂单位 SQL → 前端 record.old 备份/解压/chown/校验。默认作用于 `APP_DIR=/opt/zjpdt-record`、
`WEB_ROOT=/www/wwwroot/tailect.cn`，部署在别处时用同名环境变量覆盖再执行。

**手动等价流程**（脚本不可用时）：

```bash
docker tag zjpdt-backend:latest zjpdt-backend:rollback-$(date +%Y%m%d)    # 先保回滚点
<按 §10.2 做一次全量备份>
cd /opt && tar -xzf 新包.tar.gz && rsync -a 新包目录/ /opt/zjpdt-record/ --exclude=logs   # .env/logs 保留不覆盖
cd /opt/zjpdt-record && docker compose up -d
mv /www/wwwroot/tailect.cn/record /www/wwwroot/tailect.cn/record.old-$(date +%F)   # 前端同样先留旧版
tar -xzf record_web.tar.gz -C /www/wwwroot/tailect.cn/ && chown -R www:www /www/wwwroot/tailect.cn/record
# 验证 §9 全绿后删除 rollback 镜像与 record.old-*
```

### 10.5 回滚

- 后端：`docker tag zjpdt-backend:rollback-YYYYMMDD zjpdt-backend:latest && docker compose up -d`
- 前端：`rm -rf record && mv record.old-YYYYMMDD record`
- 数据库：`docker compose exec -T mysql sh -c 'exec mysql -uzjpdt -p"$MYSQL_PASSWORD" zjpdt' < 备份.sql`
- nginx：还原 §8 的 conf 备份后重载

## 11. 红线（违反任何一条都是事故）

1. **8002 绝不改绑 0.0.0.0**——API 无公网防护，只允许 127.0.0.1；mysql 同理（临时调试也只绑回环）。
2. **三个密钥必改**（.env 里的 `<改我>` 不换，compose 会拒绝启动——这是机制不是建议）。
3. **282 个种子账号密码全是 `123456`**：超管首登立即改密；市/县管理员账号尽快改；正式启用前评估是否清理演示民警账号。
4. 不修改现有站点的任何既有配置行；对站点 conf 的唯一合法操作是 §8 的追加（且有备份）。
5. 麦克风录音要求 HTTPS 安全上下文——主站证书已满足，**不要**想法子用 http:// 提供页面。

## 12. 已知约束

- 浏览器基线 Chrome 80+（构建已做语法体检，polyfills 自动补齐）；
- 单请求上限 200MB（录音/导入；nginx `client_max_body_size` 与后端一致）；
- 数据总览等统计非实时（分钟级）；
- ASR 上游是内网穿透隧道（vicp.fun），可能漂移失效——失效表现是质检一直 retry，换地址流程见 §4 末条。

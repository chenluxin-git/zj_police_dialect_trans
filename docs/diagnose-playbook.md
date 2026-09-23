# 内网排障诊断手册

> 用法：**先在左列找现象，再照右列去看对应文件的那几个字段。**
> 定位不到时，直接 `bash scripts/collect-logs.sh` 把整包回传。
>
> 所有日志都在 `<部署根>/logs/` 下（容器内挂卷，宿主机可直接读）。

---

## 0. 一页速查：五个日志文件各管什么

| 文件 | 管什么 | 最该搜什么 |
|---|---|---|
| `logs/backend/startup.log` | **启动自检报告**：配置齐备性 + 外部服务可达性 | `【配置问题】`、`【可达性】` |
| `logs/backend/request.log` | 一行一请求：trace / 耗时 / 平台令牌有无 | `REQ-EXC`、`SLOW`、`401`、`502`、`rz=` |
| `logs/backend/client.log` | **前端上报**：白屏 / JS 崩溃 / 接口失败 | `source=window`、`source=resource`、`source=api` |
| `logs/backend/app.log` | 业务日志 | `启动中`、`启动完成`、`建表失败` |
| `logs/backend/error.log` | ERROR 及以上 + **异常全栈** | 整个文件（有内容就是问题） |
| `logs/nginx/access.log` | 访问与耗时、上游状态、trace | `trace=`、`rz=`、`502` |
| `logs/nginx/error.log` | 上游连接失败 / DNS / TLS | `connect() failed`、`no resolver`、`upstream` |

---

## 1. `startup.log` 字段怎么读

### 1.1 配没配（布尔类）

| 字段 | `false` 的含义 | 是否阻塞 |
|---|---|---|
| `SYS_ID(系统标准码)` | 审计 `checkSum` 算不出；`live` 认证必失败 | **live 模式阻塞** |
| `APP_KEY` | 同上 | **live 模式阻塞** |
| `APP_SECRET` | 审计上报无法签名 | **审计阻塞** |
| `AUTH_BUTTON(APPID)` | 跳过应用级鉴权（不报错，但少一道校验） | 不阻塞 |
| `组织同步开关` | 不同步省厅部门/警员 | 按需 |

### 1.2 可达性

```json
{"host":"lxrdl.gat.zj","port":5010,"resolved":"10.1.2.3","tcp":"ok"}
```

| `resolved` / `tcp` | 说明 | 处理 |
|---|---|---|
| `10.x` / `x.x.x.x` + `tcp: ok` | 正常 | — |
| `198.18.x.x` | **代理 fake-IP**，不是真内网地址 | 关掉本机代理，或让 DNS 走内网 DNS（用户域 `10.118.1.10`） |
| `<解析失败 ...>` | DNS 不通 | 配 `10.118.1.10`；`/etc/resolv.conf` 或宿主 DNS |
| `tcp: fail(TimeoutError)` | 解析通了但端口不通 | 防火墙 / 路由 / 源地址未加白 |
| `tcp: fail(ConnectionRefusedError)` | 对端拒绝 | 地址或端口写错，或服务未在该地址监听 |
| `tcp: skipped(dns)` | 因 DNS 失败跳过 | 先修 DNS |

---

## 2. 按现象查

### ① 容器起不来 / 反复重启

```bash
docker compose ps                       # 看 STATUS 是否 Restarting
docker compose logs --tail 100 backend  # 容器自身 stdout
cat logs/backend/error.log              # 应用异常全栈
```

| 关键线索 | 原因 | 处理 |
|---|---|---|
| `error.log` 有 `建表失败` 全栈 | 数据库连不上 / 口令错 / 库不存在 | 查 `DATABASE_URL`；MySQL 未 ready 时先起 mysql 再起 backend |
| `no such host` / `Unknown MySQL server host` | compose 网内解析不到 `mysql` | 确认 `--profile mysql` 起了 mysql；服务名是否为 `mysql` |
| `Access denied for user` | MySQL 口令不符 | `.env.docker` 的口令要和 compose 里 `MYSQL_PASSWORD` 一致 |
| `Address already in use` | 80/443/3306 被占 | `ss -tlnp \| grep -E ':(80\|443\|3306)'` |
| `permission denied` 挂载文件 | `logs/` 或 `deploy/certs/` 属主不对 | `chown -R`，或确认 `.env.docker` 存在（缺失会挂成目录） |
| 容器 `Exited (1)` 无日志 | 配置文件语法错 | 见 ④ |

**注意**：`.env.docker` 若不存在，compose 挂载会**创建一个同名目录**，后端读不到配置且报错诡异。确认它是**文件**不是目录。

### ② 后端 healthy，但浏览器打不开

```bash
curl -sk https://127.0.0.1/api/health    # 后端是否真的活着
cat logs/nginx/error.log | tail -30
cat logs/backend/client.log | tail -30   # 前端上报
```

| 线索 | 原因 | 处理 |
|---|---|---|
| `client.log` 有 `source=resource` + `静态资源加载失败` | **产物没挂对**：`/assets/*.js` 404 | 确认 web 镜像内 `/usr/share/nginx/html/index.html` 存在 |
| `client.log` 有 `source=resource` 且路径带前缀 | **子路径 base 配错** | 构建要 `--base=/record/`，且 nginx 放开子路径段 |
| `nginx/error.log` 有 `connect() failed ... 8000` | nginx 连不上后端 | 后端容器是否在跑；是否同一 compose 网络 |
| 页面 200 但一片空白，`client.log` 无新记录 | JS 未执行（Chrome 版本过低） | 本项目按 Chrome80 构建；低于该版本会挂 |
| `client.log` 有 `source=window` + `TypeError` | 前端代码异常 | 把该行连同 `route=` 回传 |

### ③ 「加载中」卡住 / 接口全 401

```bash
tail -50 logs/backend/request.log
tail -50 logs/nginx/access.log
```

| 线索 | 原因 | 处理 |
|---|---|---|
| 大量 `-> 401` | 会话失效或未建立 | 看是否有 `/api/auth/zhijing/callback` 成功记录（应为 303） |
| 没有 `/api/auth/zhijing/callback` 记录 | **平台没打进来** | 回调地址填错 / 平台未配置 / 网络不通。先确认 `nginx/access.log` 里连那一行都没有 → 请求根本没到 |
| `access.log` 里 `rz=0 az=0 ct=-` | 平台打开时**没带令牌也没带参数** | 认证配置未生效；或平台走了别的入口。找省厅确认回调方式 |
| `access.log` 里 `rz=1 az=1` 但后端 401 | 令牌带着了，但校验失败 | 看 `error.log` 有无认证服务调用失败；`mode` 是否为 `live` |
| 有 callback 但返回 **403** | 应用级鉴权拒绝 | 当前用户无本应用权限（`AUTH_BUTTON` 配了就会校验） |
| 有 callback 但 302 到错误地址 | **`FRONTEND_BASE` 配错** | 改成与平台实际访问路径一致 |
| `REQ-EXC` 且堆栈含 `zero_trust` / `认证服务不可达` | 到省厅零信任不通 | 见 ⑤ |

### ④ nginx 起不来 / 502

```bash
docker compose exec web nginx -t
cat logs/nginx/error.log
```

| 线索 | 原因 | 处理 |
|---|---|---|
| `unknown directive "http2"` | nginx < 1.25.1 | 把 `http2 on;` 换成 `listen 443 ssl http2;` |
| `cannot load certificate` | 证书路径/文件名不对 | 必须叫 `cert.pem` / `key.pem` 放 `deploy/certs/` |
| `BIO_new_file() failed` | 私钥权限或格式 | `chmod 600 key.pem`，确认是 PEM |
| `502` + `connect() failed (111)` | 后端没起 | 起后端；确认服务名 `backend` |
| `413 Request Entity Too Large` | 录音超限 | 调 `client_max_body_size`（默认 200m） |
| `504` | 后端处理超时 | 看 `request.log` 里该请求的 `SLOW` 行与耗时 |

> **网关错误现在返回 JSON 信封**：`{"code":502,"msg":"网关错误 HTTP 502（来源：nginx）"}`。
> 前端会直接把这个 msg 弹出来，所以"看到的提示"本身就能区分**网关问题**还是**应用问题**。

### ⑤ 调省厅零信任服务不通

```bash
cat logs/backend/startup.log            # 【可达性】段
grep -i "认证服务\|权限服务\|审计服务" logs/backend/app.log
grep -i "零信任\|rzzx\|zerotrust" logs/backend/error.log
```

对照 §1.2 的 `resolved` / `tcp` 表。**先解决 DNS 与端口连通，再谈业务。**

常见：内网 DNS 未指向 `10.118.1.10`；服务器出网走了代理导致 `198.18.x.x`。

### ⑥ 审计不上去 / 台账积压

```bash
curl -sk https://127.0.0.1/api/diag | grep -A6 审计
grep -i "审计\|audit" logs/backend/app.log | tail -20
```

| 线索 | 原因 |
|---|---|
| `enabled: false` | `ZHIJING_AUDIT_ENABLED=false`，未上报（台账会一直涨） |
| `pending` 持续增长 | 审计服务不可达或报文被拒 |
| `retry_over_limit` > 0 | 重试超限，需人工排查（见 `last_error`） |
| `oldest_pending_at` 很旧 | 长时间未成功上报 |

字段含义：`pending` 待上报、`sent` 已上报、`backlog` 台账总量。

### ⑦ 录音上传失败

```bash
tail -30 logs/backend/request.log | grep recordings
cat logs/backend/error.log | tail -40
```

| 线索 | 原因 | 处理 |
|---|---|---|
| `500` + 堆栈含 `ffmpeg` / `FileNotFoundError` | 后端镜像缺 ffmpeg | `bash load-offline.sh` 会自检这项；缺了要重新导出镜像 |
| `413` | 超过 `client_max_body_size` | 调大或限制单文件 |
| 前端 `source=api` + `status=0` | 请求没发出去（HTTPS 上下文不足） | 麦克风必须 HTTPS；自签证书要手动信任 |
| `403 您没有分配此文本` | 未先领取 | 业务逻辑，非故障 |

### ⑧ 二维码/名称乱码、中文显示异常

`logs/backend/*.log` 全部以 **UTF-8** 写入。若 `cat` 出现乱码而内容逻辑正常，是**终端编码**问题：

```bash
locale                 # 应为 zh_CN.UTF-8 或 en_US.UTF-8
export LANG=C.UTF-8    # 临时修正
```

**不要**因为终端乱码就判断"日志坏了"——回传后我这边按 UTF-8 读是正常的。

---

## 3. trace_id：三方对齐

同一请求在三个地方有**相同的 trace id**：

```
logs/nginx/access.log         … trace=9eb1eb061b2b4dd6|rz=1|az=1
logs/backend/request.log      REQ trace=9eb1eb061b2b4dd6 POST /api/auth/zhijing/callback -> 303 44ms
logs/backend/client.log       CLIENT … trace=9eb1eb061b2b4dd6 …
```

用法：

```bash
# 拿到一个 trace 后，一次看全三方
T=9eb1eb061b2b4dd6
grep "$T" logs/nginx/access.log logs/backend/request.log logs/backend/client.log
```

排查"用户说点了报错"时，让现场 F12 看响应头 `X-Trace-Id`，或直接从 `client.log` 拿。

---

## 4. 回传什么给我

```bash
bash scripts/collect-logs.sh --url https://<地址> --since 24h
```

产出 `logpack-<时间戳>.tar.gz`，已含：`/api/diag`、五个后端日志、nginx 日志、docker 状态与 stdout、
系统与版本、证书有效期、**脱敏后的配置快照**。

**另外请附上**（脚本抓不到的）：

1. **做了什么操作**（点了哪个菜单、什么账号、大概时间）
2. **看到的原话**（界面报错文案 / 白屏 / 转圈）
3. `logs/backend/client.log` 里对应时间的行（如有）

--- 

## 5. 脱敏说明（回传前请确认）

日志里的以下内容**已被打码**：`token` / `password` / `secret` / `app_secret` / `authorization` /
`rzzx-usertoken` / `rzzx-apptoken` / 身份证号 / 警号 / 手机号。

**未打码**（排障需要）：姓名、机构码、区域码、请求路径、状态码、耗时、堆栈。

> ⚠️ `logs/nginx/access.log` 由 nginx 在**转发之前**写出，格式里的 `$request` 含**完整 query string**。
> 若平台把身份证号放在 query 里（动态秘钥回调的常见形态），**那份日志里会有明文**。
> 回传前请按保密要求处理，或告知我"nginx 日志未脱敏"，我按内网规范另行处理。

---

## 6. 附：一键自查脚本

```bash
# 部署后立即跑一遍，把结果留着做基线
cd <部署根>
echo "--- ps ---";        docker compose ps
echo "--- health ---";    curl -sk https://127.0.0.1/api/health
echo "--- diag ---";      curl -sk https://127.0.0.1/api/diag
echo "--- nginx -t ---";  docker compose exec -T web nginx -t
echo "--- startup ---";   tail -60 logs/backend/startup.log
echo "--- errors ---";    tail -30 logs/backend/error.log
```

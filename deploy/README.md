# 部署一页纸（双容器）

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

- **数据备份**：全部在 `app-data` 卷（`/data/app.db` + `/data/audio_storage` + `/data/exports` + `/data/text_imports` + `/data/audio_imports` 侧车台账）。备份即 `docker run --rm -v zj_police_dialect_trans_app-data:/data -v $PWD:/bk alpine tar czf /bk/backup.tgz /data`
- **扫盘功能**：白名单根目录默认 `/data/scan`（`SCAN_ROOT`）——服务器扫盘导入只接受该目录内路径；用时先进卷建目录放音频：`docker compose exec backend mkdir -p /data/scan`
- **启用 ASR 质检**：`server/.env.docker` 填 `ASR_API_URL=...` → `docker compose up -d backend` 重建；留空时上传直通 passed
- **内网/离线机**：外网机 `docker save` 两个镜像拷入 `docker load`；npm/pip 已走国内镜像源（Dockerfile 内注明可改）
- **改密钥**：`SECRET_KEY` 变更后所有已发 token 立即失效（用户需重新登录），不影响数据
- **本机开发形态**：后端 `server/.venv/Scripts/python -m uvicorn app.main:app --port 8000`，前端 `web/` 下 `npm run dev`（vite 代理 /api → 8000，见 vite.config.ts）

## 已知边界

- 本开发机无 docker——本套件经静态核验（nginx 配置/构建上下文/卷路径），`compose up` 首验在部署机执行，按上方冒烟清单逐条确认
- 录音上传超过 100MB/请求 会被 nginx 拒（`client_max_body_size`，按需调）

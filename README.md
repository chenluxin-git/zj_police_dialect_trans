# 浙江公安方言语料采集平台

面向浙江省公安系统的方言语料采集与标注平台。民警按文本朗读录音、系统质检入库、区县标注员转写为普通话文本，省/市/县三级管理员在各自辖区内治理数据并导出语料包。

```
文本导入（管理员） → 民警领文本·录音 → ASR 质检（未配置则直通） → 音频标注（转写） → 数据总览 → 导出 ZIP
```

## 功能

**民警端（日常工作）**
- 录音采集：领取文本、浏览器麦克风录音（建议 5～20 秒）、`unique(user, text)` 防重复提交
- 我的录音 / 我的标注：质检状态（已通过 / 待质检）、历史记录
- 任务进度卡与站内消息（角标提醒）

**标注作业**
- 领取待标注音频（按区域精确匹配）、3 分钟占用锁防止重复劳动
- 提交普通话转写（译文必填），提交后自动领下一条

**管理端（三级权限：省 → 市 → 区县，数据范围随账号自动限定，越权 403）**
- 文本导入：`.txt` / `.docx`、类别（警情/生活/地名/俚语/自定义），归属**强制区县级**（市/省级码会产生用户领不到的死数据，前后端双重拦截）
- 音频素材：页面上传、服务器扫盘（`SCAN_ROOT` 白名单）两入口
- 录音管理 / 标注管理：列表、筛选、试听
- 数据总览：统计卡 + 任务进度 + 类别分布；区域表**市 → 区县 → 派出所**三级行内展开（按民警单位名称聚合）
- 任务管理：录音 / 标注任务指标（完成率、未启动人数）
- 消息发送：按区域 / 按人群发站内信
- 数据导出：勾选导出 ZIP（WAV + dataset.txt），打包件即焚（二次下载需重新打包）

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10 · FastAPI · SQLAlchemy 2.0 · MySQL 8（开发默认 SQLite）· JWT |
| 前端 | Vue 3 · TypeScript · Element Plus · Vite |
| 质检 | 可选 ASR HTTP 接口（`ASR_UPSTREAM_BASE` 留空则直通通过） |
| 部署 | Docker Compose（backend: python3.10-slim + ffmpeg；web: node 构建 → nginx） |

## 目录结构

```
server/              FastAPI 后端（app/ 源码、tests/ 148 个 pytest 用例）
web/                 Vue 3 前端（vite 代理 /api → 127.0.0.1:8000）
deploy/              部署一页纸（README.md）与证书目录
docker-compose.yml   双容器编排（443 自签 nginx + /api 反代）
docs/                specs（规格）/ plans（实施计划存档）
dome/                静态设计稿
```

## 快速开始（本地开发）

```bash
# 后端（Python 3.10；启动时自动建表 + seed 账号/区域/派出所/方言）
cd server
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Linux: .venv/bin/pip
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload

# 前端
cd web
npm install
npm run dev            # http://localhost:5173（vite 已代理 /api）

# 测试与构建
cd server && .venv/Scripts/python -m pytest -q      # 148 passed
cd web && npm run build                              # vue-tsc + vite
```

## 种子账号（密码均为 `123456`）

| 账号 | 角色 |
|---|---|
| `33000000001` | 超级管理员（全省） |
| `{市码}00001`（如 `33100000001` 台州市） | 市级管理员（11 市） |
| `{县码}00001`（如 `33100400001`） | 县级管理员（90 区县） |
| `{县码}00002` / `{县码}00003` | 民警（每县 2 个，共 180） |

共 282 个种子账号（见 `server/app/utils/seed.py`），覆盖全省 11 市 90 区县。

## 部署

- **Docker Compose（推荐）**：证书生成、起停、冒烟清单、备份与运维要点见 [deploy/README.md](deploy/README.md)
- **宝塔子路径（如 `/record/`）**：前端 `npm run build -- --mode record-demo --base=/record/`（配合 `web/.env.record-demo` 的 `VITE_API_BASE=/record/api`），路由 base 与登录跳转自动适配构建期 `BASE_URL`

## 说明

- 麦克风录音要求 HTTPS（本地 `localhost` 除外），自签证书首次访问需手动继续
- 运行数据（`server/data/`、`server/audio_storage/`、`server/exports/`）不入库，备份迁移按 deploy/README 的卷方案处理
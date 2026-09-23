# MySQL 改造真机交接计划（Linux + Docker 执行机）

> **执行状态（2026-09-23）**：Task A–D 已在演练机（Ubuntu VM，Docker 29.4.0）执行完毕，全部预期达成——基线 156 passed + 4 skipped；门控集成测试 **5 passed**（含 utf8mb4 中文往返/unique/索引/搬迁 E2E），带库全量 **160 passed**；种子搬迁演练逐表核对 **users 282 / regions 102 / dialects 11 / police_stations 696 = 1091 行**，MySQL 侧 `AUTO_INCREMENT=283`、`ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`、id=1 省超管 UTF-8 字节完好；compose 全家桶冒烟（宿主 80 被 dialect_* 占用，临时 override 改 8080/8443）health ok、种子账号登录、任务下达/区域公告/领文本/录音上传 QC 直通 passed/数据总览全链绿，中文零乱码，`down` 后双卷保留。**Task E（生产切换）待生产部署机择窗口执行。** 下文勾选框不再单独维护，以本状态行为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在有 Docker 的 Linux 机器上完成 MySQL 改造的真机验证（集成测试、搬迁演练、compose 全家桶冒烟）与生产切换（含存量 SQLite 数据搬迁）。

**Architecture:** 改造代码已全部合入 main（build_engine 方言分支、搬迁脚本、compose db 服务），本计划只做「验证 + 部署」，不改任何代码；除演练暴露缺陷需修复外（修复须按仓库风格提交并说明）。

**Tech Stack:** Docker / Docker Compose · mysql:8.0 · Python 3.10+ · SQLAlchemy 2.0.23 + PyMySQL 1.1.0 · pytest

**Spec:** [docs/plans/2026-09-23-mysql-migration.md](2026-09-23-mysql-migration.md)（改造总计划，其 Task 1–3 已完成、Task 4 由本文件接替细化）

## 已完成状态（执行机须知，勿重做）

| 已合入 main 的提交 | 内容 |
|---|---|
| `a696628` | database.py 抽 `build_engine()`：SQLite 分支 `check_same_thread=False`；MySQL 分支 `pool_recycle=3600`；新增 `server/tests/test_mysql_integration.py`（1 常跑 + 4 个 `TEST_MYSQL_URL` 门控） |
| `230db39` | `server/scripts/sqlite_to_mysql.py` 整库搬迁（显式主键保 id、目标非空守卫、整型主键判型后顶 `AUTO_INCREMENT`）+ 4 例 sqlite→sqlite 测试 |
| `87203e9` | compose 加 `db`（mysql:8.0、utf8mb4、healthcheck、`mysql-data` 卷）、`.env.docker` 切 `mysql+pymysql://zjpdt:...@db:3306/zjpdt?charset=utf8mb4`、deploy/README 搬迁与双卷备份 |

无 docker 的开发机已验证：常规套件 **156 passed + 4 skipped**（skipped 即本计划要真机跑的门控测试）。模型层/查询层经摸排零改动（无外键、无 server_default、无原生 SQL）。

## Global Constraints

- 不改依赖版本：`requirements.txt` 锁定（pymysql==1.1.0 已含；cryptography 随 python-jose 引入，覆盖 MySQL 8 caching_sha2_password）。
- **破坏性红线**：门控测试会对目标库 `drop_all/create_all`——`TEST_MYSQL_URL` 只准指向一次性测试库，**绝不指向生产库**；搬迁脚本 `--force` 会清空目标表，只准对空库/演练库使用。
- 业务不改密不重启原则：生产切换时 `app-data` 卷内 `app.db` 原文件保留不删（回滚即把 `.env.docker` 的 `DATABASE_URL` 改回 `sqlite:////data/app.db` 重建 backend）。
- 所有验证步骤必须留下命令输出作为证据；预期值不匹配即停（STOP），不要猜着修。
- MySQL 版本下限 5.7（`String(512)` 唯一索引 utf8mb4 需 InnoDB DYNAMIC），统一用 `mysql:8.0`。
- commit 信息中文一行式（如需修复性提交）。

---

### Task A: 环境准备与基线

**Files:** 无改动（纯环境验证）

- [ ] **Step 1: 拉代码并确认分支与提交**

```bash
git clone https://github.com/chenluxin-git/zj_police_dialect_trans.git   # 或已有目录 git pull
cd zj_police_dialect_trans && git log --oneline -4
```

Expected: 最近提交含 `87203e9`（MySQL 改造③）。

- [ ] **Step 2: Python 环境与常规套件基线**

```bash
cd server && python -m pip install -r requirements.txt
python -m pytest -q
```

Expected: **156 passed, 4 skipped**（4 skipped 是 `TEST_MYSQL_URL` 未设置的门控测试，属正常基线）。

- [ ] **Step 3: Docker 可用性**

```bash
docker --version && docker compose version
```

Expected: 两者均出版本号。若 `mysql:8.0` 拉取超时：配置镜像加速器，或改用内网已有 mysql:8.x 镜像（`docker run` 步骤同步换 tag）。

---

### Task B: 一次性 MySQL 测试库 + 门控集成测试

**Files:** 无改动（跑 `server/tests/test_mysql_integration.py` 的 4 个门控用例）

- [ ] **Step 1: 起一次性测试库（端口 33061，与生产隔离）**

```bash
docker run -d --name zjpdt-mysql-test \
  -e MYSQL_ROOT_PASSWORD=root123 -e MYSQL_DATABASE=zjpdt_test -p 33061:3306 mysql:8.0
until docker exec zjpdt-mysql-test mysqladmin ping -h localhost -uroot -proot123 --silent 2>/dev/null; do sleep 3; done && echo DB_READY
```

Expected: 输出 `DB_READY`（mysqladmin: alive）。首次拉镜像较久属正常。

- [ ] **Step 2: 跑门控集成测试**

```bash
cd server
export TEST_MYSQL_URL='mysql+pymysql://root:root123@127.0.0.1:33061/zjpdt_test?charset=utf8mb4'
python -m pytest tests/test_mysql_integration.py -v
```

Expected: **5 passed, 0 skipped**。五个用例分别验证：引擎分支、utf8mb4 中文往返、unique 约束（users.phone / recordings(user_id,text_id)）、连接字符集 + phone 唯一索引、搬迁脚本 sqlite→mysql 全链路（主键保留 + AUTO_INCREMENT 顶起）。

- [ ] **Step 3: 带库跑全量（可选加强）**

```bash
python -m pytest -q
```

Expected: **160 passed, 0 skipped**（156 + 4 门控全部真跑）。

---

### Task C: 存量搬迁演练（真实 schema + 真实种子数据）

**Files:** 无改动（生成临时演练库后删除）

- [ ] **Step 1: 用真实种子造 SQLite 源库**

```bash
cd server && python - <<'EOF'
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.utils.seed import run_seed
eng = create_engine("sqlite:///./data/migrate_rehearsal.db")
Base.metadata.create_all(eng)
with sessionmaker(bind=eng)() as s:
    run_seed(s)
EOF
```

Expected: 无输出、正常退出（282 账号 bcrypt 加密约需 1–2 分钟）。`data/` 目录下出现 `migrate_rehearsal.db`。

- [ ] **Step 2: 执行搬迁（--force 因目标库已被 Task B 用例建表）**

```bash
python -m scripts.sqlite_to_mysql --sqlite ./data/migrate_rehearsal.db \
    --mysql "$TEST_MYSQL_URL" --force
```

Expected: 逐表行数清单，且必须等于——
`users: 282`（1 超管 + 11 市管 + 90 县管 + 180 民警）、`regions: 102`（1 省 + 11 市 + 90 县）、`dialects: 11`、`police_stations: 696`，其余表 0；末行 `完成，共 1091 行`。

- [ ] **Step 3: MySQL 侧抽查**

```bash
docker exec zjpdt-mysql-test mysql -uroot -proot123 zjpdt_test -e \
  "SELECT COUNT(*) AS users FROM users; SELECT id, real_name FROM users WHERE id=1; SHOW CREATE TABLE users\G" | head -30
```

Expected: `users`=282；`id=1` 为「省超管」；`SHOW CREATE TABLE` 中 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`。

- [ ] **Step 4: 清理演练产物**

```bash
rm -f server/data/migrate_rehearsal.db && docker rm -f zjpdt-mysql-test && unset TEST_MYSQL_URL
```

Expected: 无输出。

---

### Task D: compose 全家桶冒烟（db + backend + web）

**Files:** 无改动

- [ ] **Step 1: 起全家桶**

```bash
cd <仓库根目录>
docker compose up -d --build && docker compose ps
```

Expected: 三容器 `zjpdt-db`（healthy）/ `zjpdt-backend` / `zjpdt-web` 均 Up；backend 在 db healthy 后才启动（depends_on: service_healthy）。**若 80/443 被占用**：部署机已有 nginx/宝塔时改 `docker-compose.yml` 端口映射为 `8080:80`、`8443:443` 再起（改动仅为本机冒烟，勿提交）。

- [ ] **Step 2: 健康检查 + 种子账号登录（MySQL 落库证据）**

```bash
curl -k https://localhost/api/health
curl -k -X POST https://localhost/api/auth/login \
  -H 'Content-Type: application/json' -d '{"phone":"33000000001","password":"123456"}'
docker compose exec db mysql -uzjpdt -pchange-me-in-prod zjpdt \
  -e "SELECT COUNT(*) FROM users;"
```

Expected: ① `{"status":"ok"}`；② 返回含 token 的登录成功响应；③ `282`（startup 在 MySQL 上幂等灌种子成功）。

- [ ] **Step 3: 按 deploy 冒烟清单走剩余项**

对照 [deploy/README.md](../../deploy/README.md) 的冒烟清单逐条确认（含上传/导出等可选项），证据留存。

- [ ] **Step 4: 收尾**

```bash
docker compose down        # 保留卷；生产切换在 Task E
```

---

### Task E: 生产切换（存量数据搬迁，仅生产部署机执行）

**Files:** 无代码改动；生产数据从 SQLite `app-data` 卷迁入 `mysql-data` 卷

**前置确认（缺一不可）：** ① 老部署 `app-data` 卷内存在 `/data/app.db` 且有业务数据；② 已按 deploy/README 更换 `SECRET_KEY`（或 shell 注入）；③ 停止民警端使用窗口。

- [ ] **Step 1: 只起库，搬数据**

```bash
cd <仓库根目录>
docker compose up -d db
docker compose run --rm backend python -m scripts.sqlite_to_mysql \
    --sqlite /data/app.db --mysql "$DATABASE_URL"
```

Expected: 逐表行数清单。**逐表核对源库行数**（源侧计数：`docker compose run --rm backend python -c "import sqlite3; ..."` 或宿主机 sqlite3），任一表不等即停。

- [ ] **Step 2: 起全家桶并验证**

```bash
docker compose up -d
curl -k https://localhost/api/health
# 用一个真实民警账号登录验证（密码哈希已随库搬迁，原密码应可登录）
docker compose exec db mysql -uzjpdt -p<密码> zjpdt -e "SELECT COUNT(*) FROM users; SELECT COUNT(*) FROM recordings;"
```

Expected: health ok；真实账号登录成功；users/recordings 数与源库一致。management 端抽查一页录音列表与 QC 状态正常。

- [ ] **Step 3: 回滚预案（不执行，仅备案）**

任一验证不过：`docker compose stop backend` → `server/.env.docker` 的 `DATABASE_URL` 改回 `sqlite:////data/app.db` → `docker compose up -d backend`。`app.db` 未被脚本改动（只读源），MySQL 侧数据留在 `mysql-data` 卷待排查。

---

## Self-Review 记录

- **覆盖度**：原计划 Task 4 三步（门控真跑/搬迁演练/全家桶冒烟）→ Task B/C/D；生产切换（原 deploy 文档浓缩为可执行步骤+回滚）→ Task E；环境基线 → Task A。
- **预期值全部量化**：156+4 / 5 passed / 160 passed / 282·102·11·696=1091 行 / health ok；不匹配即停。
- **破坏性操作已设红线**：TEST_MYSQL_URL 仅限一次性库；`--force` 仅限演练/空库；生产搬迁不改 `app.db` 源文件，回滚路径明确。
- **类型/命名一致性**：`TEST_MYSQL_URL`、`scripts.sqlite_to_mysql`、`build_engine` 与已合入代码一致；端口 33061 仅 Task B/C 演练用，生产 compose 内走服务名 `db:3306`。

#!/usr/bin/env bash
# 离线包导入与启动（在**内网**服务器上执行）
#
# 前提：已从联网机拷入 zjpdt-offline-<时间戳>.tar.gz
# 本脚本只做三件事：docker load 镜像 → 校验 → 给出下一步命令。
# **不会**自动起服务：配置（.env/证书）需要人填，起之前必须先看自检输出。
#
# 用法：
#   tar -xzf zjpdt-offline-*.tar.gz
#   cd zjpdt-offline-*/
#   bash load-offline.sh                    # 从 ./images 载入
#   bash load-offline.sh ./images --with-db # 同载 MySQL 镜像

set -euo pipefail

IMG_DIR="${1:-./images}"
WITH_DB=0
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --with-db) WITH_DB=1; shift ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

say() { printf '[load] %s\n' "$*"; }
die() { printf '[load] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装并启动 Docker"

[ -d "$IMG_DIR" ] || die "镜像目录不存在：$IMG_DIR"

marker() { printf '\n===== %s =====\n' "$*"; }

# ---------------------------------------------------------------- 1) 载入
marker "1/4 docker load"
for t in zjpdt-backend zjpdt-web; do
  f="$IMG_DIR/$t.tar"
  if [ -f "$f" ]; then
    say "载入 $f …"
    docker load -i "$f" | sed 's/^/        /'
  else
    say "  WARN 缺少 $f，跳过"
  fi
done

if [ "$WITH_DB" -eq 1 ]; then
  if [ -f "$IMG_DIR/mysql-8.0.tar" ]; then
    say "载入 mysql-8.0.tar …"
    docker load -i "$IMG_DIR/mysql-8.0.tar" | sed 's/^/        /'
  else
    say "  WARN 包内无 mysql-8.0.tar；若用 MySQL 请确认内网已有该镜像"
  fi
fi

# ---------------------------------------------------------------- 2) 校验
marker "2/4 校验镜像标签"
fail=0
for tag in zjpdt-backend:latest zjpdt-web:latest; do
  if docker image inspect "$tag" >/dev/null 2>&1; then
    size="$(docker image inspect "$tag" --format '{{.Size}}' 2>/dev/null || echo '?')"
    say "  OK  $tag  (size=$size)"
  else
    say "  FAIL 缺少镜像 $tag"
    fail=1
  fi
done
[ "$fail" -eq 0 ] || die "镜像标签不齐。若 MANIFEST.txt 里的标签不是 zjpdt-*，说明导出包与 compose 不匹配"

# ---------------------------------------------------------------- 3) 关键依赖自检
marker "3/4 镜像内依赖自检"
# ffmpeg 缺失会导致录音上传 500，这是最容易在换环境后暴露的问题
if docker run --rm --entrypoint sh zjpdt-backend:latest -c 'command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null' 2>/dev/null; then
  say "  OK  后端镜像含 ffmpeg / ffprobe"
else
  say "  WARN 后端镜像内未找到 ffmpeg/ffprobe —— 录音转码会失败，请确认导出的是正确镜像"
fi
# 前端产物是否打进去了（白屏常见原因）
if docker run --rm --entrypoint sh zjpdt-web:latest -c 'test -f /usr/share/nginx/html/index.html' 2>/dev/null; then
  say "  OK  前端镜像含 index.html"
else
  say "  FAIL 前端镜像内没有 /usr/share/nginx/html/index.html —— 该镜像构建产物缺失，需重新导出"
  fail=1
fi

# ---------------------------------------------------------------- 4) 下一步
marker "4/4 载入完成，下一步要人工做的事"
cat <<'EOF'
镜像已就绪。起服务前请先完成配置（详细步骤见 OFFLINE-DEPLOY.md）：

  1) 编排与配置就位
       cp compose/docker-compose.yml .
       cp compose/nginx.zhijing.conf ./deploy-nginx.zhijing.conf   # 挂载时用
       mkdir -p server deploy/certs
       cp compose/env/.env.zhijing.docker.example  server/.env.docker
       cp compose/certs/README.txt deploy/certs/

  2) 改 server/.env.docker（**必改**）
       SECRET_KEY      = openssl rand -hex 32 的结果
       DATABASE_URL    = MySQL 连接串（用 MySQL 时）
       ZHIJING_MODE    = 联调期先 mock，拿到平台凭据后改 live
       ZHIJING_SYS_ID / ZHIJING_APP_KEY / ZHIJING_APP_SECRET = 平台侧提供
       FRONTEND_BASE   = 与平台给的实际访问路径一致（子路径如 /record/ 必填）

  3) 放正式证书到 deploy/certs/{cert.pem,key.pem}

  4) 启动（注意：**不要加 --build**，离线环境构建不了）
       docker compose up -d              # 后端 + nginx（SQLite）
       docker compose --profile mysql up -d   # 含 MySQL

  5) 验证（关键）
       docker compose ps                                   # backend 应为 healthy
       curl -sk https://127.0.0.1/api/health               # {"status":"ok"}
       curl -sk https://127.0.0.1/api/diag | head -50      # **启动自检：配置问题与外部服务可达性**
       docker compose exec web nginx -t                    # nginx 语法
       tail -n 30 logs/backend/startup.log                 # 启动自检报告（人读）

  6) 出问题就收集日志回传
       bash scripts/collect-logs.sh --url https://<你的地址>
EOF

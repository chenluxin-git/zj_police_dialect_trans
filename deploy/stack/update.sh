#!/usr/bin/env bash
# zjpdt 整栈增量升级一键脚本（无宝塔形态，前后端镜像分包按需升级）
#
# 用法：把本脚本与升级包放在同一目录（建议 /root/upload/），在服务器上执行：
#   bash update.sh                  # 有什么包升什么：backend 包→升后端，web 包→升前端
#
# 目录里识别的包（放一个就只做那部分，两个都在则一起升，替换镜像后统一重启+验证）：
#   zjpdt-backend-*.tar.gz   后端镜像（docker save 的 tar 或其 gzip）
#   zjpdt-web-*.tar.gz       前端镜像（dist 已打进 nginx 镜像，无磁盘落盘步骤）
#
# 可用环境变量覆盖路径：APP_DIR / BACKUP_DIR
#
# 流程：预检 → 备库+留回滚点 → docker load → compose up → 全链健康等待(失败自动回滚)
#       （新库首启种子自带单位归属，无需宝塔形态里那条补挂 SQL）
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/zjpdt-stack}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backup}"
UPLOAD_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
RB_DATE="$(date +%Y%m%d)"

say() { printf '[update %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '[update %s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

BACKEND_PKG="$(ls "$UPLOAD_DIR"/zjpdt-backend-*.tar.gz 2>/dev/null | head -1 || true)"
WEB_PKG="$(ls "$UPLOAD_DIR"/zjpdt-web-*.tar.gz 2>/dev/null | head -1 || true)"
[ -n "$BACKEND_PKG" ] || [ -n "$WEB_PKG" ] || die "目录 $UPLOAD_DIR 下没有 zjpdt-backend-*.tar.gz 也没有 zjpdt-web-*.tar.gz"

say "预检：docker / 部署目录 / 升级包"
command -v docker >/dev/null 2>&1 || die "未找到 docker"
[ -f "$APP_DIR/.env" ] || die "$APP_DIR/.env 不存在——APP_DIR 设错了吗？（可用 APP_DIR=... bash update.sh 覆盖）"
cd "$APP_DIR"
docker compose ps >/dev/null 2>&1 || die "docker compose 在 $APP_DIR 执行失败"
[ -n "$BACKEND_PKG" ] && say "后端包：$(basename "$BACKEND_PKG")（$(du -h "$BACKEND_PKG" | cut -f1)）"
[ -n "$WEB_PKG" ] && say "前端包：$(basename "$WEB_PKG")（$(du -h "$WEB_PKG" | cut -f1)）"
HTTPS_PORT="$(grep -h '^HTTPS_PORT=' "$APP_DIR/.env" | tail -1 | cut -d= -f2)"; HTTPS_PORT="${HTTPS_PORT:-443}"

# ---------------------------------------------------------------- 1/5 数据库备份（动了后端必先备）
if [ -n "$BACKEND_PKG" ]; then
  say "[1/5] 数据库全量备份"
  mkdir -p "$BACKUP_DIR"
  # --no-tablespaces 必须给：zjpdt 用户只有库级权限、无全局 PROCESS，8.0.21+ 缺省会报错中断
  docker compose exec -T mysql sh -c 'exec mysqldump --no-tablespaces --default-character-set=utf8mb4 -uzjpdt -p"$MYSQL_PASSWORD" --single-transaction zjpdt' \
    | gzip > "$BACKUP_DIR/zjpdt-db-$STAMP.sql.gz"
  [ -s "$BACKUP_DIR/zjpdt-db-$STAMP.sql.gz" ] || die "备份文件为空，中止（未做任何变更）"
  # 部分版本 docker compose exec 不回传容器内退出码（踩过：mysqldump 报错脚本照样继续），
  # 故用内容标记校验：mysqldump 正常收尾必写 "Dump completed" 尾注
  zgrep -q 'Dump completed' "$BACKUP_DIR/zjpdt-db-$STAMP.sql.gz" \
    || die "备份不完整（缺 Dump completed 尾标记），已中止未做任何变更"
  say "  备份：$BACKUP_DIR/zjpdt-db-$STAMP.sql.gz"
else
  say "[1/5] 无后端包，跳过备库"
fi

# ---------------------------------------------------------------- 2/5 回滚点
keep_rollback() { # $1=镜像 tag
  if docker image inspect "$1" >/dev/null 2>&1; then
    say "[2/5] 回滚点 $1 今日已存在，保留不覆盖（防重跑把旧镜像回滚点冲掉）"
  else
    say "[2/5] 旧镜像留回滚点：$1"
    docker tag "$2" "$1"
  fi
}
[ -n "$BACKEND_PKG" ] && keep_rollback "zjpdt-backend:rollback-$RB_DATE" zjpdt-backend:latest
[ -n "$WEB_PKG" ]     && keep_rollback "zjpdt-web:rollback-$RB_DATE"     zjpdt-web:latest

# ---------------------------------------------------------------- 3/5 导入新镜像
say "[3/5] 导入新镜像（docker load）"
if [ -n "$BACKEND_PKG" ]; then
  LOAD_OUT="$(docker load -i "$BACKEND_PKG")"
  echo "$LOAD_OUT"
  echo "$LOAD_OUT" | grep -q "zjpdt-backend:latest" || die "导入结果里没有 zjpdt-backend:latest，包可能不对，中止（线上未受影响）"
fi
if [ -n "$WEB_PKG" ]; then
  LOAD_OUT="$(docker load -i "$WEB_PKG")"
  echo "$LOAD_OUT"
  echo "$LOAD_OUT" | grep -q "zjpdt-web:latest" || die "导入结果里没有 zjpdt-web:latest，包可能不对，中止（线上未受影响）"
fi

# ---------------------------------------------------------------- 4/5 重启并全链验证
say "[4/5] 重启容器并等待全链健康（https://127.0.0.1:${HTTPS_PORT}/api/health，最长 120 秒）"
docker compose up -d
ok=0
for _ in $(seq 1 60); do
  if curl -kfsS "https://127.0.0.1:${HTTPS_PORT}/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != 1 ]; then
  say "健康检查失败！自动回滚 …"
  [ -n "$BACKEND_PKG" ] && docker tag "zjpdt-backend:rollback-$RB_DATE" zjpdt-backend:latest
  [ -n "$WEB_PKG" ]     && docker tag "zjpdt-web:rollback-$RB_DATE"     zjpdt-web:latest
  docker compose up -d
  die "已回滚旧镜像并重启。请查日志：docker compose logs --tail=100 backend web"
fi
B_ID="$(docker image inspect zjpdt-backend:latest --format '{{.Id}}' | cut -c8-19)"
W_ID="$(docker image inspect zjpdt-web:latest --format '{{.Id}}' | cut -c8-19)"
say "[5/5] 已上线：backend $B_ID / web $W_ID"

# ---------------------------------------------------------------- 汇总
say "============================================================"
say "全链已验证（回滚点 zjpdt-*-rollback-$RB_DATE）"
say "浏览器过一遍 DEPLOY.md §7 后清理："
[ -n "$BACKEND_PKG" ] && { say "  docker rmi zjpdt-backend:rollback-$RB_DATE"; say "  库备份 $BACKUP_DIR/zjpdt-db-$STAMP.sql.gz 确认无误后归档"; }
[ -n "$WEB_PKG" ] && say "  docker rmi zjpdt-web:rollback-$RB_DATE"
say "完成。"

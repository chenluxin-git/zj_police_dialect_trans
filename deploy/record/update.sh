#!/usr/bin/env bash
# zjpdt 增量升级一键脚本（宝塔 /record/ 部署形态，前后端分包按需部署）
#
# 用法：把本脚本与升级包放在同一目录（建议 /root/upload/），在服务器上执行：
#   bash update.sh                  # 有什么包升什么：backend 包→升后端，record_web 包→换前端
#   bash update.sh --no-backfill    # 跳过种子民警补挂单位（默认自动执行，幂等只补空值）
#
# 目录里识别的包（放一个就只做那部分，两个都在则先 backend 后 frontend，顺序不可反）：
#   zjpdt-backend-*.tar.gz   后端镜像（docker save 的 tar 或其 gzip）
#   record_web*.tar.gz       前端静态产物（含 record/ 顶层目录）
#
# 可用环境变量覆盖路径：APP_DIR / WEB_ROOT / BACKUP_DIR
#
# 流程：预检 → [后端] 备库+留回滚点 → docker load → compose up → 健康等待(失败自动回滚)
#       → 补挂单位 SQL（幂等） → [前端] record.old 备份 → 解压 → chown → 校验 → 汇总
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/zjpdt-record}"
WEB_ROOT="${WEB_ROOT:-/www/wwwroot/tailect.cn}"
BACKUP_DIR="${BACKUP_DIR:-/www/backup}"
UPLOAD_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
ROLLBACK_TAG="zjpdt-backend:rollback-$(date +%Y%m%d)"

DO_BACKFILL=1
for a in "$@"; do
  case "$a" in
    --no-backfill) DO_BACKFILL=0 ;;
    -h|--help)     sed -n '2,15p' "$0"; exit 0 ;;
    *)             echo "未知参数：$a（仅支持 --no-backfill）"; exit 2 ;;
  esac
done

say() { printf '[update %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '[update %s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

BACKEND_PKG="$(ls "$UPLOAD_DIR"/zjpdt-backend-*.tar.gz 2>/dev/null | head -1 || true)"
FRONTEND_PKG="$(ls "$UPLOAD_DIR"/record_web*.tar.gz 2>/dev/null | head -1 || true)"
[ -n "$BACKEND_PKG" ] || [ -n "$FRONTEND_PKG" ] || die "目录 $UPLOAD_DIR 下没有 zjpdt-backend-*.tar.gz 也没有 record_web*.tar.gz"

say "预检：docker / 部署目录 / 升级包"
command -v docker >/dev/null 2>&1 || die "未找到 docker"
[ -f "$APP_DIR/.env" ] || die "$APP_DIR/.env 不存在——APP_DIR 设错了吗？（可用 APP_DIR=... bash update.sh 覆盖）"
cd "$APP_DIR"
docker compose ps >/dev/null 2>&1 || die "docker compose 在 $APP_DIR 执行失败"
[ -n "$BACKEND_PKG" ] && say "后端包：$(basename "$BACKEND_PKG")（$(du -h "$BACKEND_PKG" | cut -f1)）"
[ -n "$FRONTEND_PKG" ] && say "前端包：$(basename "$FRONTEND_PKG")（$(du -h "$FRONTEND_PKG" | cut -f1)）"

# ---------------------------------------------------------------- 后端
if [ -n "$BACKEND_PKG" ]; then
  say "[后端 1/5] 数据库全量备份"
  mkdir -p "$BACKUP_DIR"
  # --no-tablespaces 必须给：zjpdt 用户只有库级权限、无全局 PROCESS，8.0.21+ 缺省会报错中断
  docker compose exec -T mysql sh -c 'exec mysqldump --no-tablespaces --default-character-set=utf8mb4 -uzjpdt -p"$MYSQL_PASSWORD" --single-transaction zjpdt' \
    | gzip > "$BACKUP_DIR/zjpdt-db-$STAMP.sql.gz"
  [ -s "$BACKUP_DIR/zjpdt-db-$STAMP.sql.gz" ] || die "备份文件为空，中止（未做任何变更）"
  # 部分版本 docker compose exec 不回传容器内退出码（踩过：mysqldump 报错脚本照样继续），
  # 故用内容标记校验：mysqldump 正常收尾必写 "Dump completed" 尾注
  zgrep -q 'Dump completed' "$BACKUP_DIR/zjpdt-db-$STAMP.sql.gz" \
    || die "备份不完整（缺 Dump completed 尾标记），已中止未做任何变更。报 tablespace/PROCESS 权限错时见 DEPLOY.md §10.2 加 --no-tablespaces"

  if docker image inspect "$ROLLBACK_TAG" >/dev/null 2>&1; then
    say "[后端 2/5] 回滚点 $ROLLBACK_TAG 今日已存在，保留不覆盖（防重跑把旧镜像回滚点冲掉）"
  else
    say "[后端 2/5] 旧镜像留回滚点：$ROLLBACK_TAG"
    docker tag zjpdt-backend:latest "$ROLLBACK_TAG"
  fi

  say "[后端 3/5] 导入新镜像（docker load）"
  LOAD_OUT="$(docker load -i "$BACKEND_PKG")"
  echo "$LOAD_OUT"
  echo "$LOAD_OUT" | grep -q "zjpdt-backend:latest" || die "导入结果里没有 zjpdt-backend:latest，包可能不对，中止（未重启容器，线上未受影响）"

  say "[后端 4/5] 重启后端容器"
  docker compose up -d

  say "[后端 5/5] 等待健康检查（/api/health，最长 90 秒）"
  PORT="$(docker compose port backend 8000 2>/dev/null | cut -d: -f2 || true)"
  PORT="${PORT:-8002}"
  ok=0
  for _ in $(seq 1 45); do
    if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 2
  done
  if [ "$ok" != 1 ]; then
    say "健康检查失败！自动回滚到 $ROLLBACK_TAG …"
    docker tag "$ROLLBACK_TAG" zjpdt-backend:latest
    docker compose up -d
    die "已回滚旧镜像并重启。请查日志：docker compose logs --tail=100 backend"
  fi
  say "后端已上线：$(docker image inspect zjpdt-backend:latest --format '{{.Id}}' | cut -c8-19)"

  if [ "$DO_BACKFILL" = 1 ]; then
    say "[后端] 种子民警补挂单位（幂等：只补 role=user 且单位为空、手机号=区划码+00002/00003 的种子账号）"
    # --default-character-set=utf8mb4 必须显式给：容器内无 locale，客户端按 latin1 解释语句，
    # 中文会语法错、写库会变乱码；别名用 ASCII，并用输出标记校验（compose exec 不回传退出码）
    BF_OUT="$(docker compose exec -T mysql sh -c 'exec mysql --default-character-set=utf8mb4 -uzjpdt -p"$MYSQL_PASSWORD" zjpdt' <<'SQL'
SELECT COUNT(*) AS station_before FROM users WHERE role='user' AND police_station<>'';
UPDATE users u
JOIN (
  SELECT ps.region_code, ps.name,
         ROW_NUMBER() OVER (PARTITION BY ps.region_code ORDER BY ps.sort_order, ps.code) AS rn
  FROM police_stations ps
) s ON s.region_code = u.region_code
   AND ((RIGHT(u.phone, 5) = '00002' AND s.rn = 1)
     OR (RIGHT(u.phone, 5) = '00003' AND s.rn = 2))
SET u.police_station = s.name
WHERE u.role = 'user'
  AND (u.police_station IS NULL OR u.police_station = '')
  AND u.phone LIKE CONCAT(u.region_code, '%');
SELECT COUNT(*) AS station_after FROM users WHERE role='user' AND police_station<>'';
SQL
)"
    echo "$BF_OUT"
    echo "$BF_OUT" | grep -q 'station_after' \
      || die "补挂 SQL 未执行成功（看上方 mysql 报错）。后端已上线、前端未动——修好后重跑本脚本即可"
    say "补挂完成（见上方 station_before → station_after；真实区县 20 个×每县 2 民警=40，另 129 条单位挂演示伪区划码无用户不影响）"
  fi
else
  say "未发现后端包，跳过后端（本次只动前端）"
fi

# ---------------------------------------------------------------- 前端
if [ -n "$FRONTEND_PKG" ]; then
  say "[前端 1/4] 校验包结构（须含 record/ 顶层目录）"
  tar -tzf "$FRONTEND_PKG" record/index.html >/dev/null 2>&1 \
    || die "包里没有 record/index.html——不是本平台的 record_web 包，中止"

  say "[前端 2/4] 旧版备份为 record.old-$STAMP"
  [ -d "$WEB_ROOT/record" ] && mv "$WEB_ROOT/record" "$WEB_ROOT/record.old-$STAMP"

  say "[前端 3/4] 解压新前端并授权 www"
  if ! tar -xzf "$FRONTEND_PKG" -C "$WEB_ROOT"; then
    [ -d "$WEB_ROOT/record.old-$STAMP" ] && mv "$WEB_ROOT/record.old-$STAMP" "$WEB_ROOT/record"
    die "解压失败，已还原旧前端"
  fi
  chown -R www:www "$WEB_ROOT/record"

  say "[前端 4/4] 校验产物"
  [ -f "$WEB_ROOT/record/index.html" ] || die "解压后缺 index.html（旧版在 record.old-$STAMP）"
  grep -q '/record/' "$WEB_ROOT/record/index.html" \
    || die "index.html 资源引用不含 /record/ 前缀——包的 base 不对，请勿对外发布（旧版在 record.old-$STAMP）"
else
  say "未发现前端包，跳过前端（本次只动后端）"
fi

# ---------------------------------------------------------------- 汇总
say "============================================================"
[ -n "$BACKEND_PKG" ] && say "后端：已上线（回滚点 $ROLLBACK_TAG；库备份 $BACKUP_DIR/zjpdt-db-$STAMP.sql.gz）"
[ -n "$FRONTEND_PKG" ] && say "前端：已替换（旧版 $WEB_ROOT/record.old-$STAMP）"
say "验证：curl -s http://127.0.0.1:${PORT:-8002}/api/health && curl -I https://tailect.cn/record"
say "浏览器过一遍 §9 后清理："
[ -n "$BACKEND_PKG" ] && say "  docker rmi $ROLLBACK_TAG"
[ -n "$FRONTEND_PKG" ] && say "  rm -rf $WEB_ROOT/record.old-$STAMP"
say "完成。"

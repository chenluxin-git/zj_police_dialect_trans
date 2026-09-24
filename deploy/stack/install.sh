#!/usr/bin/env bash
# zjpdt 整栈一键首装（无宝塔/无主机 nginx 的裸机器；在交付包根目录执行）
#
# 整栈形态 = backend + web + mysql 三个容器，web 容器内 nginx 直接服务前端并反代 /api/，
# 对外只占 80/443 两个端口，宿主机除 docker 外零依赖。
#
# 与 load.sh / update.sh 的分工：
#   load.sh    只导入镜像+自检，不起服务（最保守）
#   install.sh 首装全流程：导镜像 → 建部署目录 → 生成密钥 .env → 自签证书 → 起容器 → 全链验证（本脚本）
#   update.sh  已部署机器的增量升级（后端/前端镜像包有什么升什么）
#
# 用法（交付包解压后，在包根目录）：
#   bash install.sh                          # 全默认：/opt/zjpdt-stack，端口 80/443，证书 CN=自动探测的本机 IP
#   bash install.sh --cn 10.0.0.5            # 指定证书 CN（IP 或域名，浏览器地址栏用哪个就填哪个）
#   bash install.sh --https-port 8443        # 443 被占用时换端口（80 同理 --http-port）
#   参数：--cn <IP|域名>  --http-port <端口>  --https-port <端口>  --app-dir <部署目录>
#
# 幂等：重复执行安全——.env 已存在则保留（MySQL 密码只认首启），证书已存在不重签。
# 前提：docker + compose v2 已装好（curl -fsSL https://get.docker.com | sh && systemctl enable --now docker）。
set -euo pipefail

APP_DIR="/opt/zjpdt-stack"
HTTP_PORT="80"
HTTPS_PORT="443"
CN=""

while [ $# -gt 0 ]; do
  case "$1" in
    --cn)         CN="$2"; shift 2 ;;
    --http-port)  HTTP_PORT="$2"; shift 2 ;;
    --https-port) HTTPS_PORT="$2"; shift 2 ;;
    --app-dir)    APP_DIR="$2"; shift 2 ;;
    -h|--help)    sed -n '2,19p' "$0"; exit 0 ;;
    *)            echo "未知参数：$1"; exit 2 ;;
  esac
done
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
CN="${CN:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
CN="${CN:-localhost}"

say() { printf '[install %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '[install %s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

port_busy() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }

# ---------------------------------------------------------------- 1/7 预检
say "1/7 预检：docker / 交付包完整性 / 端口 / 磁盘空间"
command -v docker >/dev/null 2>&1 || die "未找到 docker。先装：curl -fsSL https://get.docker.com | sh && systemctl enable --now docker"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose v2 插件（不支持 python 版 docker-compose v1）"
command -v curl >/dev/null 2>&1 || die "未找到 curl（最终验证需要）"
for f in images/zjpdt-backend.tar images/zjpdt-web.tar images/mysql-8.0.tar docker-compose.yml \
         server/.env.docker .env.template nginx-site.conf load.sh; do
  [ -f "$PKG_DIR/$f" ] || die "包不完整：缺 $f（应在交付包根目录执行本脚本）"
done
# 端口只在首装时硬校验（重跑时端口可能是本项目的容器在听，交给 compose 自己 reconcile）
if [ ! -f "$APP_DIR/.env" ]; then
  port_busy "$HTTP_PORT"  && die "$HTTP_PORT 端口已被占用。先停占用者，或换：bash install.sh --http-port <其他端口> --https-port <其他端口>"
  port_busy "$HTTPS_PORT" && die "$HTTPS_PORT 端口已被占用。先停占用者，或换：bash install.sh --https-port <其他端口>"
fi
AVAIL_GB="$(df -BG --output=avail "$(dirname "$APP_DIR")" 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)"
[ "${AVAIL_GB:-0}" -ge 3 ] || say "  WARN：$APP_DIR 所在盘仅剩 ${AVAIL_GB}G（镜像+数据建议 ≥3G）"
say "  部署目录=$APP_DIR  端口=$HTTP_PORT/$HTTPS_PORT  证书CN=$CN"

# ---------------------------------------------------------------- 2/7 镜像导入（复用 load.sh 的自检）
say "2/7 导入镜像（含 ffmpeg/时区/前端 base 探针）"
(cd "$PKG_DIR" && bash load.sh) | sed 's/^/    /'

# ---------------------------------------------------------------- 3/7 部署目录与 .env
say "3/7 建部署目录并生成密钥"
mkdir -p "$APP_DIR"
for f in docker-compose.yml .env.template nginx-site.conf load.sh DEPLOY.md; do
  [ -f "$PKG_DIR/$f" ] && cp -f "$PKG_DIR/$f" "$APP_DIR/"
done
[ -f "$PKG_DIR/update.sh" ] && cp -f "$PKG_DIR/update.sh" "$APP_DIR/"
mkdir -p "$APP_DIR/server" && cp -f "$PKG_DIR/server/.env.docker" "$APP_DIR/server/.env.docker"
if [ -f "$APP_DIR/.env" ]; then
  say "  .env 已存在，保留不覆盖（MySQL 密码只认数据卷首启；端口/ASR 想变直接编辑该文件）"
else
  command -v openssl >/dev/null 2>&1 || die "未找到 openssl，无法生成密钥"
  ASR_LINE="$(grep -h '^ASR_UPSTREAM_BASE=' "$PKG_DIR/.env.template" || true)"
  umask 077
  {
    echo "# 由 install.sh 于 $(date '+%F %T') 自动生成；改端口/密钥/ASR 后 docker compose up -d 生效"
    echo "SECRET_KEY=$(openssl rand -hex 32)"
    echo "MYSQL_ROOT_PASSWORD=$(openssl rand -hex 16)"
    echo "MYSQL_PASSWORD=$(openssl rand -hex 16)"
    echo ""
    echo "HTTP_PORT=$HTTP_PORT"
    echo "HTTPS_PORT=$HTTPS_PORT"
    echo ""
    echo "${ASR_LINE:-ASR_UPSTREAM_BASE=}"
  } > "$APP_DIR/.env"
  say "  已生成随机密钥写入 $APP_DIR/.env（权限 600，内容勿外传；ASR 上游沿用模板值）"
fi
# 生效端口以 .env 为准（重跑时 .env 里的旧值优先于本次命令行参数）
HTTP_PORT="$(grep -h '^HTTP_PORT='  "$APP_DIR/.env" | tail -1 | cut -d= -f2)"; HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="$(grep -h '^HTTPS_PORT=' "$APP_DIR/.env" | tail -1 | cut -d= -f2)"; HTTPS_PORT="${HTTPS_PORT:-443}"

# ---------------------------------------------------------------- 4/7 自签证书
say "4/7 自签 HTTPS 证书（麦克风录音要求安全上下文；正式证书替换见 DEPLOY.md §8）"
mkdir -p "$APP_DIR/certs"
if [ -f "$APP_DIR/certs/cert.pem" ] && [ -f "$APP_DIR/certs/key.pem" ]; then
  say "  证书已存在，保留不重签"
else
  # SAN 一起签上 IP/域名（openssl≥1.1.1）；老版本不支持 -addext 就退回仅 CN
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$APP_DIR/certs/key.pem" -out "$APP_DIR/certs/cert.pem" \
    -subj "/CN=$CN" -addext "subjectAltName=DNS:$CN,IP:$CN" 2>/dev/null \
  || openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$APP_DIR/certs/key.pem" -out "$APP_DIR/certs/cert.pem" \
    -subj "/CN=$CN"
  chmod 600 "$APP_DIR/certs/key.pem"
  say "  已生成：$APP_DIR/certs/cert.pem（CN=$CN，10 年期自签）"
fi

# ---------------------------------------------------------------- 5/7 起容器
say "5/7 启动容器（首次建库+建表+282 个种子账号，最长约 4 分钟）"
cd "$APP_DIR"
docker compose up -d
wait_healthy() { # $1=服务名 $2=最长秒数（按 compose 服务名寻址，不依赖容器名）
  local i cid max=$(( $2 / 3 ))
  for i in $(seq 1 "$max"); do
    cid="$(docker compose ps -q "$1" 2>/dev/null || true)"
    if [ -n "$cid" ] && [ "$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo x)" = "healthy" ]; then
      return 0
    fi
    sleep 3
  done
  return 1
}
wait_healthy mysql 150 || { docker compose logs --tail=30 mysql 2>&1 | sed 's/^/    /'; die "mysql 150 秒内未 healthy（看上方日志；常见：磁盘满/旧数据卷密码不匹配）"; }
say "  mysql healthy"
wait_healthy backend 240 || { docker compose logs --tail=50 backend 2>&1 | sed 's/^/    /'; die "backend 240 秒内未 healthy（看上方日志）"; }
say "  backend healthy（镜像 $(docker image inspect zjpdt-backend:latest --format '{{.Id}}' | cut -c8-19)）"

# ---------------------------------------------------------------- 6/7 全链验证（穿过 web 容器的 443）
say "6/7 全链验证（https://127.0.0.1:${HTTPS_PORT} 穿 web 容器 → backend）"
sleep 2
curl -kfsS "https://127.0.0.1:${HTTPS_PORT}/api/health" >/dev/null 2>&1 \
  || { docker compose logs --tail=30 web 2>&1 | sed 's/^/    /'; die "https://127.0.0.1:${HTTPS_PORT}/api/health 不通——容器间 healthy 但 web 反代失败，看上方 web 日志"; }
say "  OK  /api/health（web → backend 链路通）"
PAGE_CODE="$(curl -ksI -o /dev/null -w '%{http_code}' "https://127.0.0.1:${HTTPS_PORT}/" || true)"
[ "$PAGE_CODE" = "200" ] || die "首页返回 $PAGE_CODE（预期 200）——查 docker compose logs web"
say "  OK  首页 200（前端已由 web 容器直出）"
REDIR_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${HTTP_PORT}/" || true)"
[ "$REDIR_CODE" = "301" ] || say "  WARN http://${HTTP_PORT} 返回 $REDIR_CODE（预期 301 跳 https；不影响使用）"

# ---------------------------------------------------------------- 7/7 汇总
VISIT_URL="https://${CN}/"
[ "$HTTPS_PORT" != "443" ] && VISIT_URL="https://${CN}:${HTTPS_PORT}/"
say "============================================================"
say "首装完成。验证（DEPLOY.md §7）："
say "  curl -k https://127.0.0.1:${HTTPS_PORT}/api/health"
say "  防火墙/云安全组放行 TCP ${HTTP_PORT}、${HTTPS_PORT}（systemctl status firewalld >/dev/null && firewall-cmd --add-port=${HTTPS_PORT}/tcp --add-port=${HTTP_PORT}/tcp --permanent && firewall-cmd --reload）"
say "浏览器：${VISIT_URL}  → 首次有证书告警（自签），点「高级 → 继续前往」"
say "  → 33000000001 / 123456，**登录后立即改密**（DEPLOY.md §11 红线）"
say "后续升级：zjpdt-backend-*.tar.gz / zjpdt-web-*.tar.gz 与 update.sh 放同一目录 bash update.sh"
say "备份（DEPLOY.md §9.2 建计划任务，命令含 --no-tablespaces）与换正式证书（§8）见 $APP_DIR/DEPLOY.md"
say "完成。"

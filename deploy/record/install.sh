#!/usr/bin/env bash
# zjpdt 首装一键脚本（宝塔 /record/ 子路径形态；在交付包根目录执行）
#
# 与 load.sh / update.sh 的分工：
#   load.sh    只导入镜像+自检，不起服务（最保守）
#   install.sh 首装全流程：导镜像 → 建部署目录 → 生成随机密钥 .env → 起容器 → 前端落盘 → 接入 nginx（本脚本）
#   update.sh  已部署机器的增量升级（后端镜像包 / 前端包有什么升什么）
#
# 用法（交付包解压后，在包根目录）：
#   bash install.sh                                    # 全默认：域名 tailect.cn，/opt/zjpdt-record
#   bash install.sh --domain demo.example.cn           # 新机器换了域名
#   bash install.sh --skip-nginx                       # 非宝塔机器：跳过 nginx 接入，打印手动步骤
#   参数：--domain <域名>  --web-root <站点根>  --app-dir <部署目录>  --skip-nginx
#
# 幂等：重复执行安全——.env 已存在则保留（MySQL 密码只认首启），nginx 只接一次，前端重跑会先备份旧版。
# 前提：docker + compose v2 已装好（宝塔 Docker 管理应用或 curl -fsSL https://get.docker.com | sh）。
set -euo pipefail

DOMAIN="tailect.cn"
APP_DIR="/opt/zjpdt-record"
WEB_ROOT=""
SKIP_NGINX=0

while [ $# -gt 0 ]; do
  case "$1" in
    --domain)   DOMAIN="$2"; shift 2 ;;
    --web-root) WEB_ROOT="$2"; shift 2 ;;
    --app-dir)  APP_DIR="$2"; shift 2 ;;
    --skip-nginx) SKIP_NGINX=1; shift ;;
    -h|--help)  sed -n '2,16p' "$0"; exit 0 ;;
    *)          echo "未知参数：$1"; exit 2 ;;
  esac
done
WEB_ROOT="${WEB_ROOT:-/www/wwwroot/$DOMAIN}"
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"

say() { printf '[install %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '[install %s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 1/6 预检
say "1/6 预检：docker / 交付包完整性 / 磁盘空间"
command -v docker >/dev/null 2>&1 || die "未找到 docker。先装：宝塔『Docker 管理应用』或 curl -fsSL https://get.docker.com | sh && systemctl enable --now docker"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose v2 插件（不支持 python 版 docker-compose v1）"
for f in images/zjpdt-backend.tar images/mysql-8.0.tar docker-compose.yml \
         record_web.tar.gz server/.env.docker .env.template nginx-record.conf load.sh; do
  [ -f "$PKG_DIR/$f" ] || die "包不完整：缺 $f（应在交付包根目录执行本脚本）"
done
AVAIL_GB="$(df -BG --output=avail "$(dirname "$APP_DIR")" 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)"
[ "${AVAIL_GB:-0}" -ge 3 ] || say "  WARN：$APP_DIR 所在盘仅剩 ${AVAIL_GB}G（镜像+数据建议 ≥3G）"
say "  域名=$DOMAIN  部署目录=$APP_DIR  站点根=$WEB_ROOT"

# ---------------------------------------------------------------- 2/6 镜像导入（复用 load.sh 的自检）
say "2/6 导入镜像（含 ffmpeg/时区探针）"
(cd "$PKG_DIR" && bash load.sh) | sed 's/^/    /'

# ---------------------------------------------------------------- 3/6 部署目录与 .env
say "3/6 建部署目录并生成密钥"
mkdir -p "$APP_DIR"
for f in docker-compose.yml .env.template nginx-record.conf load.sh DEPLOY.md; do
  [ -f "$PKG_DIR/$f" ] && cp -f "$PKG_DIR/$f" "$APP_DIR/"
done
[ -f "$PKG_DIR/update.sh" ] && cp -f "$PKG_DIR/update.sh" "$APP_DIR/"
mkdir -p "$APP_DIR/server" && cp -f "$PKG_DIR/server/.env.docker" "$APP_DIR/server/.env.docker"
if [ -f "$APP_DIR/.env" ]; then
  say "  .env 已存在，保留不覆盖（MySQL 密码只认数据卷首启，重装不换库）"
else
  command -v openssl >/dev/null 2>&1 || die "未找到 openssl，无法生成密钥"
  ASR_LINE="$(grep -h '^ASR_UPSTREAM_BASE=' "$PKG_DIR/.env.template" || true)"
  umask 077
  {
    echo "# 由 install.sh 于 $(date '+%F %T') 自动生成；改密/换 ASR 上游后 docker compose up -d 生效"
    echo "SECRET_KEY=$(openssl rand -hex 32)"
    echo "MYSQL_ROOT_PASSWORD=$(openssl rand -hex 16)"
    echo "MYSQL_PASSWORD=$(openssl rand -hex 16)"
    echo ""
    echo "${ASR_LINE:-ASR_UPSTREAM_BASE=}"
  } > "$APP_DIR/.env"
  say "  已生成随机密钥写入 $APP_DIR/.env（权限 600，内容勿外传；ASR 上游沿用模板值）"
fi

# ---------------------------------------------------------------- 4/6 起容器
say "4/6 启动容器（首次建库+建表+282 个种子账号，最长约 4 分钟）"
cd "$APP_DIR"
docker compose up -d
wait_healthy() { # $1=容器名 $2=最长秒数
  local i; local max=$(( $2 / 3 ))
  for i in $(seq 1 "$max"); do
    [ "$(docker inspect --format '{{.State.Health.Status}}' "$1" 2>/dev/null || echo x)" = "healthy" ] && return 0
    sleep 3
  done
  return 1
}
wait_healthy zjpdt-mysql 150 || { docker logs --tail=30 zjpdt-mysql 2>&1 | sed 's/^/    /'; die "mysql 容器 150 秒内未 healthy（看上方日志；常见：端口/磁盘/旧数据卷密码不匹配）"; }
say "  mysql healthy"
wait_healthy zjpdt-backend 240 || { docker compose logs --tail=50 backend 2>&1 | sed 's/^/    /'; die "backend 容器 240 秒内未 healthy（看上方日志）"; }
PORT="$(docker compose port backend 8000 2>/dev/null | cut -d: -f2 || true)"; PORT="${PORT:-8002}"
curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null || die "容器 healthy 但 /api/health 不通——查 docker compose logs backend"
say "  backend healthy（镜像 $(docker image inspect zjpdt-backend:latest --format '{{.Id}}' | cut -c8-19)，127.0.0.1:${PORT}）"

# ---------------------------------------------------------------- 5/6 前端落盘
say "5/6 前端解压到站点根"
mkdir -p "$WEB_ROOT"
[ -d "$WEB_ROOT/record" ] && mv "$WEB_ROOT/record" "$WEB_ROOT/record.old-$STAMP"
tar -xzf "$PKG_DIR/record_web.tar.gz" -C "$WEB_ROOT" || die "前端解压失败（record_web.tar.gz 损坏？对照 MANIFEST.txt sha256）"
if id www >/dev/null 2>&1; then chown -R www:www "$WEB_ROOT/record"; fi
grep -q '/record/' "$WEB_ROOT/record/index.html" || die "index.html 资源引用不含 /record/ 前缀——包异常，勿对外发布"
say "  OK：$WEB_ROOT/record（旧版备份 record.old-$STAMP，如有）"

# ---------------------------------------------------------------- 6/6 nginx 接入
if [ "$SKIP_NGINX" = 1 ]; then
  say "6/6 跳过 nginx（--skip-nginx）。手动接入见 $APP_DIR/DEPLOY.md §8，片段：$APP_DIR/nginx-record.conf（<站点根> 替换为 $WEB_ROOT）"
else
  say "6/6 nginx 接入"
  NGINX_BIN="$(command -v nginx || true)"
  [ -z "$NGINX_BIN" ] && [ -x /www/server/nginx/sbin/nginx ] && NGINX_BIN=/www/server/nginx/sbin/nginx
  [ -z "$NGINX_BIN" ] && [ -x /usr/local/openresty/nginx/sbin/nginx ] && NGINX_BIN=/usr/local/openresty/nginx/sbin/nginx
  VHOST="/www/server/panel/vhost/nginx/$DOMAIN.conf"
  if [ -z "$NGINX_BIN" ] || [ ! -f "$VHOST" ]; then
    say "  未找到宝塔 nginx 或站点配置（$VHOST），转手动："
    [ -d /www/server/panel/vhost/nginx ] && ls /www/server/panel/vhost/nginx/*.conf 2>/dev/null | sed 's/^/    可选站点: /'
    say "  手动步骤=$APP_DIR/DEPLOY.md §8（片段已就位 $APP_DIR/nginx-record.conf，<站点根>→$WEB_ROOT）"
  elif grep -q 'zjpdt-record\|location = /record' "$VHOST"; then
    say "  $VHOST 已含 /record 接入，跳过（如需重做先删旧片段）"
  else
    say "  渲染片段（<站点根> → $WEB_ROOT）并插入 $VHOST"
    sed "s|<站点根>|$WEB_ROOT|g" "$APP_DIR/nginx-record.conf" > "$APP_DIR/nginx-record.rendered.conf"
    cp -f "$VHOST" "$VHOST.bak-zjpdt-$STAMP"
    LAST_BRACE="$(grep -n '^}' "$VHOST" | tail -1 | cut -d: -f1)"
    if [ -n "$LAST_BRACE" ] && [ "$LAST_BRACE" -gt 1 ]; then
      sed -i "${LAST_BRACE}i\\
    include $APP_DIR/nginx-record.rendered.conf;" "$VHOST"
    else
      cp -f "$VHOST.bak-zjpdt-$STAMP" "$VHOST"
      say "  站点配置格式特殊（没找到行首 server 结束大括号），转手动：§8 粘贴 $APP_DIR/nginx-record.rendered.conf"
    fi
    if "$NGINX_BIN" -t 2>/tmp/nginx-t.err; then
      "$NGINX_BIN" -s reload
      say "  nginx -t 通过并已 reload（回滚：cp $VHOST.bak-zjpdt-$STAMP $VHOST && nginx -s reload）"
    else
      cp -f "$VHOST.bak-zjpdt-$STAMP" "$VHOST"
      "$NGINX_BIN" -s reload >/dev/null 2>&1 || true
      say "  nginx -t 失败已自动还原站点配置，原因：$(cat /tmp/nginx-t.err | tail -2)；请按 §8 手动接入"
    fi
  fi
fi

# ---------------------------------------------------------------- 汇总
say "============================================================"
say "首装完成。验证（§9）："
say "  curl -s http://127.0.0.1:${PORT}/api/health"
say "  curl -kI https://$DOMAIN/record        # 应 301 → /record/（证书配好后去 -k）"
say "浏览器：https://$DOMAIN/record/ → 33000000001 / 123456，**登录后立即改密**（§11 红线）"
say "后续升级：把 zjpdt-backend-*.tar.gz / record_web*.tar.gz 与 update.sh 放同一目录 bash update.sh"
say "备份任务（§10.2 记得建宝塔计划任务，命令含 --no-tablespaces）与红线见 $APP_DIR/DEPLOY.md"
say "完成。"

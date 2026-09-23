#!/usr/bin/env bash
# 内网部署一键收集日志（Linux 版，排障回传用）
#
# 与 scripts/collect-logs.ps1 等价，供内网 Linux 服务器使用。
#
# 用法：
#   bash scripts/collect-logs.sh
#   bash scripts/collect-logs.sh --url https://10.0.0.5 --since 72h --out /tmp
#
# 收集：运行期自检、后端日志、nginx 日志、容器状态与 stdout、系统与版本、
#       证书有效期、脱敏后的配置快照。
#
# 脱敏：对 app_secret/secret_key/password/token/身份证号/手机号 做掩码。
#       ⚠️ 仅尽力而为；若日志含公民个人信息，回传前请按保密要求自行处理。

set -uo pipefail

BASE_URL="http://127.0.0.1"
OUT_DIR="./logpack"
SINCE="24h"

while [ $# -gt 0 ]; do
  case "$1" in
    --url)   BASE_URL="$2"; shift 2 ;;
    --out)   OUT_DIR="$2";  shift 2 ;;
    --since) SINCE="$2";    shift 2 ;;
    -h|--help)
      sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="${OUT_DIR%/}/logpack-${STAMP}"
say() { printf '[collect] %s\n' "$*"; }

mkdir -p "$WORK"

# ---------------------------------------------------------------- 脱敏
# 用 sed -E：值超过 4 位就保留首 2 尾 2，否则整体打码
mask_secrets() {
  sed -E \
    -e 's/(app_?secret)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(securekey)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(secret_?key)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(password)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(mysql_root_password)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(mysql_password)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(rzzx-usertoken)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(rzzx-apptoken)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(authorization)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(token)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/(callersign)([[:space:]]*[=:][[:space:]]*)([^[:space:]"'"'"'&,}]+)/\1\2****/Ig' \
    -e 's/([0-9]{17}[0-9Xx])/<身份证号已打码>/g' \
    -e 's/(1[3-9][0-9]{9})/<手机号已打码>/g'
}

# 落盘（自动脱敏）。$1=源文件或 "-" 表示从 stdin 读，$2=目标相对路径，$3=说明
save_stream() {
  local src="$1" dest="$WORK/$2" label="$3"
  mkdir -p "$(dirname "$dest")"
  if [ "$src" = "-" ]; then
    mask_secrets > "$dest"
  else
    mask_secrets < "$src" > "$dest"
  fi
  say "  OK  $label"
}

say "out dir: $WORK"

# ---------------------------------------------------------------- 0) 汇总头
cat > "$WORK/00-read-me-first.txt" <<EOF
收集时间 : $(date '+%Y-%m-%d %H:%M:%S')
主机名   : $(hostname)
访问地址 : $BASE_URL
日志范围 : $SINCE

== 建议按顺序看 ==
  1. backend/startup.log     启动自检（配置齐备性 + 外部服务可达性）
  2. backend/request.log     一行一请求；搜 REQ-EXC / SLOW / 401 / 502
  3. backend/client.log      前端上报（白屏/JS 崩溃/接口失败的唯一线索）
  4. nginx/error.log         upstream 连接失败、DNS 解析、TLS 握手
  5. nginx/access.log        搜 trace= 对齐后端；rz=1 表示平台带了令牌
  6. diag.json               当前数据库与外部服务状态
  7. config/                 环境变量是否配全（已脱敏）

== trace 三方对齐 ==
  nginx access.log 的 trace=xxx  ←→  backend/request.log 的 trace=xxx
  ←→  backend/client.log 的 trace=xxx（前端上报时带回）
EOF

# ---------------------------------------------------------------- 1) 运行期自检
say "1/6 runtime self-check"
if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 60 "$BASE_URL/api/diag?refresh=1" -o "$WORK/diag.raw" 2>"$WORK/diag.err"; then
    mask_secrets < "$WORK/diag.raw" > "$WORK/diag.json"
    rm -f "$WORK/diag.raw" "$WORK/diag.err"
    say "  OK  diag.json"
  else
    {
      echo "调用 $BASE_URL/api/diag 失败"
      cat "$WORK/diag.err" 2>/dev/null
      echo "（若后端未起或端口不通，这本身就是关键线索）"
    } > "$WORK/diag.json"
    rm -f "$WORK/diag.raw" "$WORK/diag.err"
    say "  OK  diag.json (failed path)"
    if curl -fsS --max-time 10 "$BASE_URL/api/health" -o "$WORK/health.txt" 2>/dev/null; then
      say "  OK  health.txt"
    else
      echo "health 也不通（连进程/端口都不通）" > "$WORK/health.txt"
      say "  OK  health.txt (failed)"
    fi
  fi
else
  echo "curl 不可用，跳过运行期自检" > "$WORK/diag.json"
  say "  WARN curl 不可用"
fi

# ---------------------------------------------------------------- 2) 日志文件
say "2/6 log files"
found_any=0
copy_log() {
  local rel="$1" dest_rel="$2"
  [ -f "$rel" ] || return 0
  found_any=1
  mkdir -p "$(dirname "$WORK/$dest_rel")"
  # 日志文件也过一遍脱敏（日志里可能有令牌残留）
  mask_secrets < "$rel" > "$WORK/$dest_rel"
  say "  OK  $rel -> $dest_rel"
}
copy_log "logs/backend/startup.log"           "backend/startup.log"
copy_log "logs/backend/startup-report.json"   "backend/startup-report.json"
copy_log "logs/backend/request.log"           "backend/request.log"
copy_log "logs/backend/client.log"            "backend/client.log"
copy_log "logs/backend/app.log"               "backend/app.log"
copy_log "logs/backend/error.log"             "backend/error.log"
copy_log "logs/nginx/access.log"              "nginx/access.log"
copy_log "logs/nginx/error.log"               "nginx/error.log"
copy_log "server/logs/startup.log"            "backend/startup.log"
copy_log "server/logs/startup-report.json"    "backend/startup-report.json"
copy_log "server/logs/request.log"            "backend/request.log"
copy_log "server/logs/client.log"             "backend/client.log"
copy_log "server/logs/app.log"                "backend/app.log"
copy_log "server/logs/error.log"              "backend/error.log"
[ "$found_any" -eq 0 ] && say "  WARN 未找到日志文件；容器部署请看 docker/ 下的 stdout"

# ---------------------------------------------------------------- 3) 容器状态
say "3/6 docker state"
if command -v docker >/dev/null 2>&1; then
  mkdir -p "$WORK/docker"
  docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' > "$WORK/docker/ps.txt" 2>&1 \
    && say "  OK  docker ps" || say "  FAIL docker ps"
  for c in zjpdt-backend zjpdt-web zjpdt-mysql; do
    if docker inspect "$c" > "$WORK/docker/inspect-$c.json" 2>/dev/null; then
      mask_secrets < "$WORK/docker/inspect-$c.json" > "$WORK/docker/inspect-$c.json.tmp" \
        && mv "$WORK/docker/inspect-$c.json.tmp" "$WORK/docker/inspect-$c.json"
      say "  OK  inspect $c"
    fi
    if docker logs --since "$SINCE" --tail 3000 "$c" > "$WORK/docker/logs-$c.raw" 2>&1; then
      mask_secrets < "$WORK/docker/logs-$c.raw" > "$WORK/docker/logs-$c.txt"
      rm -f "$WORK/docker/logs-$c.raw"
      say "  OK  logs $c"
    else
      rm -f "$WORK/docker/logs-$c.raw"
      say "  WARN 容器 $c 不存在或未启动"
    fi
  done
  docker compose config > "$WORK/docker/compose-config.yaml" 2>&1 \
    && mask_secrets < "$WORK/docker/compose-config.yaml" > "$WORK/docker/compose-config.yaml.tmp" \
    && mv "$WORK/docker/compose-config.yaml.tmp" "$WORK/docker/compose-config.yaml" \
    && say "  OK  compose config"
  # 容器资源占用：内存不足是内网部署常见故障
  docker stats --no-stream > "$WORK/docker/stats.txt" 2>&1 && say "  OK  docker stats"
else
  say "  WARN 未安装 docker，跳过"
fi

# ---------------------------------------------------------------- 4) 环境与版本
say "4/6 env and versions"
{
  echo "== OS ==";        uname -a 2>/dev/null; cat /etc/os-release 2>/dev/null
  echo "== Python ==";    (python3 --version 2>&1 || python --version 2>&1 || echo "python 不可用")
  echo "== Node ==";      (node --version 2>&1 || echo "node 不可用")
  echo "== Docker ==";    (docker version 2>&1 || true)
  echo "== 时间与时区 ==";  date; date -u; cat /etc/timezone 2>/dev/null; timedatectl 2>/dev/null | head -5
  echo "== 磁盘 ==";       df -h 2>/dev/null
  echo "== 内存 ==";       free -h 2>/dev/null
  echo "== 监听端口 ==";   (ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null || echo "无权限/无工具") | head -40
  echo "== 证书有效期 =="
  for cert in deploy/certs/cert.pem server/certs/cert.pem; do
    if [ -f "$cert" ]; then
      echo "--- $cert"
      openssl x509 -in "$cert" -noout -subject -dates 2>&1 || echo "openssl 不可用"
    else
      echo "$cert : 不存在"
    fi
  done
  echo "== DNS 解析（零信任服务）=="
  for h in lxrdl.gat.zj rzfw.data.zj qxfw.data.zj; do
    printf '%s -> ' "$h"
    (getent hosts "$h" || echo "解析失败") 2>&1 | head -2
  done
} > "$WORK/env-system.raw" 2>&1
mask_secrets < "$WORK/env-system.raw" > "$WORK/env-system.txt"
rm -f "$WORK/env-system.raw"
say "  OK  env-system.txt"

# ---------------------------------------------------------------- 5) 配置快照
say "5/6 config snapshot (masked)"
found_env=0
for rel in server/.env server/.env.docker server/.env.zhijing.docker .env; do
  if [ -f "$rel" ]; then
    found_env=1
    name="$(echo "$rel" | tr '/' '_').masked"
    save_stream "$rel" "config/$name" "config $rel"
  fi
done
[ "$found_env" -eq 0 ] && say "  WARN 未找到 .env"

{
  echo "== 关键环境变量是否已设置（只记有无与长度，不记值）=="
  for k in ZHIJING_MODE ZHIJING_LOGIN_SOURCE ZHIJING_LEGACY_LOGIN ZHIJING_SYS_ID \
           ZHIJING_APP_KEY ZHIJING_APP_SECRET ZHIJING_AUTH_BUTTON ZHIJING_DQXTBS \
           ZHIJING_RZ_URL ZHIJING_QX_URL ZHIJING_AUDIT_URL ZHIJING_AUDIT_ENABLED \
           ZHIJING_ORG_SYNC_ENABLED ZHIJING_ORG_BASE_URL \
           DATABASE_URL FRONTEND_BASE SECRET_KEY SCAN_ROOT CORS_ORIGINS; do
    v="$(printenv "$k" 2>/dev/null || true)"
    if [ -z "$v" ]; then echo "$k = <未设置(进程环境)>"; else echo "$k = <已设置, 长度 ${#v}>"; fi
  done
  echo ""
  echo "注意：上面读的是**进程环境**。若用 env_file 提供给容器，"
  echo "      真实取值请看 config/*.masked 或 docker/inspect-*.json。"
} > "$WORK/config/env-var-presence.txt"
say "  OK  env-var-presence.txt"

# ---------------------------------------------------------------- 6) 打包
say "6/6 packaging"
ARCHIVE="${WORK}.tar.gz"
# 不吞 stderr：打包失败时把 tar 的报错原样打出来，否则只能看到一句"打包失败"无从下手
if tar -czf "$ARCHIVE" -C "$(dirname "$WORK")" "$(basename "$WORK")"; then
  echo ""
  echo "DONE. Send this file back:"
  echo "  $ARCHIVE"
  echo ""
  echo "Before sending: if logs contain personal data (ID card / police no / phone),"
  echo "handle per your confidentiality rules."
else
  say "  FAIL 打包失败（见上方 tar 报错）；目录仍在 $WORK，可手动打包："
  say "        tar -czf ${ARCHIVE} -C $(dirname "$WORK") $(basename "$WORK")"
fi

#!/usr/bin/env bash
# 交付包镜像导入与自检（在目标服务器、包根目录执行；整栈形态三个镜像）
#
# 只做三件事：docker load 镜像 → 校验标签 → 关键依赖探针。
# **不会**自动起服务：密钥要人填（或用 install.sh 一键），起之前必须先看自检输出。
#
# 用法：bash load.sh            # 从 ./images 载入

set -euo pipefail

IMG_DIR="./images"

say() { printf '[load] %s\n' "$*"; }
die() { printf '[load] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装：curl -fsSL https://get.docker.com | sh && systemctl enable --now docker"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose v2 插件（本编排不支持 python 版 docker-compose v1）"

[ -d "$IMG_DIR" ] || die "镜像目录不存在：$IMG_DIR（请在包根执行本脚本）"

marker() { printf '\n===== %s =====\n' "$*"; }

# ---------------------------------------------------------------- 1) 载入
marker "1/3 docker load"
for f in "$IMG_DIR/zjpdt-backend.tar" "$IMG_DIR/zjpdt-web.tar" "$IMG_DIR/mysql-8.0.tar"; do
  [ -f "$f" ] || die "缺少 $f"
  say "载入 $f …"
  docker load -i "$f" | sed 's/^/        /'
done

# ---------------------------------------------------------------- 2) 校验
marker "2/3 校验镜像标签"
fail=0
for tag in zjpdt-backend:latest zjpdt-web:latest mysql:8.0; do
  if docker image inspect "$tag" >/dev/null 2>&1; then
    size="$(docker image inspect "$tag" --format '{{.Size}}' 2>/dev/null || echo '?')"
    say "  OK  $tag  (size=$size)"
  else
    say "  FAIL 缺少镜像 $tag"
    fail=1
  fi
done
[ "$fail" -eq 0 ] || die "镜像标签不齐。若 MANIFEST.txt 里的标签与此不符，说明包被改动过"

# ---------------------------------------------------------------- 3) 依赖自检
marker "3/3 镜像内依赖自检"
# ffmpeg 缺失会导致录音上传 500，这是换环境后最容易暴露的问题
if docker run --rm --entrypoint sh zjpdt-backend:latest -c 'command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null' 2>/dev/null; then
  say "  OK  后端镜像含 ffmpeg / ffprobe"
else
  say "  WARN 后端镜像内未找到 ffmpeg/ffprobe —— 录音转码会失败，请确认镜像完整（对照 MANIFEST.txt sha256）"
fi
# TZ 修复是否带上（差 8 小时时间戳的根源）
if docker run --rm -e TZ=Asia/Shanghai --entrypoint sh zjpdt-backend:latest -c 'test "$(date +%z)" = "+0800"' 2>/dev/null; then
  say "  OK  镜像时区支持正常（TZ=Asia/Shanghai 生效）"
else
  say "  WARN 镜像内 TZ 设置未生效——时间戳将差 8 小时，请联系打包方"
fi
# web 镜像：前端产物以根路径打包（资源引用 /assets/…），整栈形态在 https://域名/ 直出
if docker run --rm --entrypoint sh zjpdt-web:latest -c 'grep -q "src=\"/assets/" /usr/share/nginx/html/index.html' 2>/dev/null; then
  say "  OK  web 镜像前端产物为根路径构建（/assets/ 引用）"
else
  say "  WARN web 镜像内 index.html 不是根路径构建——浏览器会白屏，请联系打包方"
fi

# ---------------------------------------------------------------- 下一步
cat <<'EOF'

镜像已就绪。推荐直接一键首装（导镜像已做，会跳过重复部分）：

  bash install.sh

或按 DEPLOY.md §4-§7 手动继续：cp .env.template .env 改三个 <改我> →
生成自签证书 → docker compose up -d → curl -k https://127.0.0.1/api/health
EOF

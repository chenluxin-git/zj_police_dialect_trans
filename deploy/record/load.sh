#!/usr/bin/env bash
# 交付包镜像导入与自检（在宝塔服务器、包根目录执行）
#
# 只做三件事：docker load 镜像 → 校验标签 → 关键依赖探针。
# **不会**自动起服务：密钥要人填，起之前必须先看自检输出。
#
# 用法：bash load.sh            # 从 ./images 载入

set -euo pipefail

IMG_DIR="./images"

say() { printf '[load] %s\n' "$*"; }
die() { printf '[load] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装（宝塔 Docker 管理应用，或 curl -fsSL https://get.docker.com | sh）"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose v2 插件（本编排不支持 python 版 docker-compose v1）"

[ -d "$IMG_DIR" ] || die "镜像目录不存在：$IMG_DIR（请在包根执行本脚本）"

marker() { printf '\n===== %s =====\n' "$*"; }

# ---------------------------------------------------------------- 1) 载入
marker "1/3 docker load"
for f in "$IMG_DIR/zjpdt-backend.tar" "$IMG_DIR/mysql-8.0.tar"; do
  [ -f "$f" ] || die "缺少 $f"
  say "载入 $f …"
  docker load -i "$f" | sed 's/^/        /'
done

# ---------------------------------------------------------------- 2) 校验
marker "2/3 校验镜像标签"
fail=0
for tag in zjpdt-backend:latest mysql:8.0; do
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

# ---------------------------------------------------------------- 下一步
cat <<'EOF'

镜像已就绪。起服务前按 DEPLOY.md §4-§5 继续：

  1) cp .env.template .env，用 openssl rand -hex 生成并替换三个 <改我>
  2) docker compose up -d        # 注意：不要加 --build（服务器离线，构建不了）
  3) docker compose ps           # 等 mysql → backend 双 healthy
  4) curl 127.0.0.1:8002/api/health   应返回 {"status":"ok"}

完整步骤（前端解包 / nginx 接入 / 验证 / 运维 / 回滚）见包内 DEPLOY.md。
EOF

#!/usr/bin/env bash
# 离线交付包导出（在**有外网**的构建机上执行）
#
# 为什么需要：内网不能 docker pull / npm install。
# web 镜像是多阶段构建（构建期要联网跑 npm ci），所以**必须在联网机构建好再导出**，
# 内网侧只能 docker load，不能 --build。
#
# 产出 <out>/zjpdt-offline-<时间戳>/
#   images/zjpdt-backend.tar      后端镜像
#   images/zjpdt-web.tar          前端镜像（含已构建好的 dist）
#   images/mysql-8.0.tar          MySQL 镜像（--with-db 时）
#   compose/docker-compose.yml    编排文件（与导出版本一致）
#   compose/env/                  .env 模板
#   compose/nginx.zhijing.conf    上架版 nginx 配置
#   MANIFEST.txt                  镜像标签与 sha256，供内网侧核对
#   最后整体打一个 .tar.gz
#
# 用法：
#   bash scripts/export-offline.sh                 # 后端 + 前端
#   bash scripts/export-offline.sh --with-db       # 另含 MySQL（内网用 MySQL 时加）
#   bash scripts/export-offline.sh --out /data/pkg
#   bash scripts/export-offline.sh --no-build      # 复用本地已有镜像，不重新构建

set -euo pipefail

WITH_DB=0
DO_BUILD=1
OUT_DIR="./dist-offline"

while [ $# -gt 0 ]; do
  case "$1" in
    --with-db)  WITH_DB=1; shift ;;
    --no-build) DO_BUILD=0; shift ;;
    --out)      OUT_DIR="$2"; shift 2 ;;
    -h|--help)  sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

say() { printf '[export] %s\n' "$*"; }
die() { printf '[export] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker"

STAMP="$(date +%Y%m%d-%H%M%S)"
PKG="${OUT_DIR%/}/zjpdt-offline-${STAMP}"
IMAGES="$PKG/images"

marker() { printf '\n===== %s =====\n' "$*"; }

marker "0/5 准备目录"
mkdir -p "$IMAGES" "$PKG/compose/env"
say "输出：$PKG"

# ---------------------------------------------------------------- 1) 构建
marker "1/5 构建镜像"
if [ "$DO_BUILD" -eq 1 ]; then
  if [ "$WITH_DB" -eq 1 ]; then
    docker compose --profile mysql build
  else
    docker compose build
  fi
  say "构建完成"
else
  say "跳过构建（--no-build），将直接导出本地已有镜像"
fi

# 构建后必须存在的镜像
for tag in zjpdt-backend:latest zjpdt-web:latest; do
  docker image inspect "$tag" >/dev/null 2>&1 || die "镜像 $tag 不存在。先执行 docker compose build（或去掉 --no-build）"
done

# ---------------------------------------------------------------- 2) 导出镜像
marker "2/5 导出镜像（docker save）"
docker save zjpdt-backend:latest -o "$IMAGES/zjpdt-backend.tar"
say "  OK  zjpdt-backend.tar  $(du -h "$IMAGES/zjpdt-backend.tar" | cut -f1)"
docker save zjpdt-web:latest -o "$IMAGES/zjpdt-web.tar"
say "  OK  zjpdt-web.tar      $(du -h "$IMAGES/zjpdt-web.tar" | cut -f1)"

if [ "$WITH_DB" -eq 1 ]; then
  if ! docker image inspect mysql:8.0 >/dev/null 2>&1; then
    say "  本地无 mysql:8.0，尝试拉取…"
    docker pull mysql:8.0 || die "拉取 mysql:8.0 失败；请在有网环境先 docker pull mysql:8.0"
  fi
  docker save mysql:8.0 -o "$IMAGES/mysql-8.0.tar"
  say "  OK  mysql-8.0.tar      $(du -h "$IMAGES/mysql-8.0.tar" | cut -f1)"
fi

# ---------------------------------------------------------------- 3) 编排与配置
marker "3/5 复制编排文件与配置模板"
cp docker-compose.yml "$PKG/compose/docker-compose.yml"
say "  OK  docker-compose.yml"

cp deploy/nginx.zhijing.conf "$PKG/compose/nginx.zhijing.conf"
say "  OK  nginx.zhijing.conf"

# .env 模板：不允许把真实密钥打进包里，只放模板
for f in server/.env.zhijing.docker.example server/.env.docker; do
  if [ -f "$f" ]; then
    cp "$f" "$PKG/compose/env/$(basename "$f")"
    say "  OK  $(basename "$f")"
  fi
done

# 证书目录占位（正式证书由内网侧放入，不能附带自签私钥）
mkdir -p "$PKG/compose/certs"
cat > "$PKG/compose/certs/README.txt" <<'EOF'
把正式证书放到本目录，文件名必须是：
  cert.pem   服务器证书（含中间证书链）
  key.pem    私钥

文件名在 deploy/nginx.zhijing.conf 里写死：
  ssl_certificate     /etc/nginx/certs/cert.pem;
  ssl_certificate_key /etc/nginx/certs/key.pem;

容器以只读方式挂载本目录，权限建议 600（key.pem）。
EOF
say "  OK  certs/README.txt"

# ---------------------------------------------------------------- 4) 清单
marker "4/5 生成 MANIFEST（镜像标签 + sha256）"
{
  echo "浙警智治方言语料采集平台 —— 离线交付包"
  echo "打包时间 : $(date '+%Y-%m-%d %H:%M:%S')"
  echo "Git 版本 : $(git rev-parse --short HEAD 2>/dev/null || echo '（非 git 仓库）')"
  echo "含 MySQL : $([ "$WITH_DB" -eq 1 ] && echo 是 || echo 否)"
  echo ""
  echo "== 镜像 =="
  for t in zjpdt-backend:latest zjpdt-web:latest; do
    echo "  $t"
    docker image inspect "$t" --format '    ID={{.Id}}' 2>/dev/null || true
    docker image inspect "$t" --format '    创建={{.Created}}  大小={{.Size}}' 2>/dev/null || true
  done
  [ "$WITH_DB" -eq 1 ] && echo "  mysql:8.0"
  echo ""
  echo "== 文件 sha256（内网侧 load 后可用 tar 校验传输完整性）=="
  ( cd "$PKG" && find images -type f -name '*.tar' -exec sha256sum {} \; )
  echo ""
  echo "== 内网侧下一步 =="
  echo "  1) 解压本包"
  echo "  2) bash scripts/load-offline.sh ./images"
  echo "  3) 按 OFFLINE-DEPLOY.md 填 .env、放证书、起服务"
} > "$PKG/MANIFEST.txt"
say "  OK  MANIFEST.txt"

# ---------------------------------------------------------------- 5) 打包
marker "5/5 打包为 tar.gz"
TARBALL="${PKG}.tar.gz"
tar -czf "$TARBALL" -C "$(dirname "$PKG")" "$(basename "$PKG")"
say "  完成：$TARBALL  $(du -h "$TARBALL" | cut -f1)"
echo ""
echo "把下面这个文件拷到内网服务器："
echo "  $TARBALL"
echo ""
echo "内网侧解压后先读 OFFLINE-DEPLOY.md（本包未含，见仓库 docs/offline-deploy.md，请一并拷入）"

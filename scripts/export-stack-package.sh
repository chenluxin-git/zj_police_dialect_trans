#!/usr/bin/env bash
# 整栈独立部署包导出（在**有外网**的构建机上执行；目标机器无需宝塔/nginx，只要有 docker）
#
# 与 export-record-package.sh（宝塔子路径形态）的区别：多打一个 zjpdt-web 镜像
# （前端 dist 已打进 nginx:alpine，服务器上**没有**前端落盘/nginx 接入步骤），
# compose 对外发布 80/443，HTTPS 用自签证书（install.sh 自动生成）。
#
# 产出 <out>/zjpdt-stack-pkg-<时间戳>/
#   images/zjpdt-backend.tar    后端镜像
#   images/zjpdt-web.tar        前端镜像（根路径构建，内含 nginx 配置默认值）
#   images/mysql-8.0.tar        MySQL 镜像
#   docker-compose.yml          编排（来源 deploy/stack/docker-compose.yml；项目名锁死 zjpdt-stack）
#   .env.template               密钥/端口模板（install.sh 自动 cp+填密钥）
#   server/.env.docker          应用默认值（无密钥；来源 deploy/stack/server.env.docker）
#   nginx-site.conf             web 容器站点配置（来源 deploy/nginx.zhijing.conf）
#   load.sh / install.sh / update.sh   导入自检 / 一键首装 / 增量升级
#   DEPLOY.md                   部署手册（整栈版）
#   MANIFEST.txt                sha256 + git 版本 + 构建命令
#   最后整体打一个 .tar.gz
#
# 用法：
#   bash scripts/export-stack-package.sh                # 全新构建（backend + web 两个镜像）
#   bash scripts/export-stack-package.sh --no-build     # 复用本地 zjpdt-backend/web:latest，跳过 docker build
#   bash scripts/export-stack-package.sh --out /data/pkg

set -euo pipefail

DO_BUILD=1
OUT_DIR="./dist-stack"

while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) DO_BUILD=0; shift ;;
    --out)      OUT_DIR="$2"; shift 2 ;;
    -h|--help)  sed -n '2,27p' "$0"; exit 0 ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

say() { printf '[export-stack] %s\n' "$*"; }
die() { printf '[export-stack] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker"

STAMP="$(date +%Y%m%d-%H%M%S)"
PKG="${OUT_DIR%/}/zjpdt-stack-pkg-${STAMP}"
IMAGES="$PKG/images"

marker() { printf '\n===== %s =====\n' "$*"; }

marker "0/6 准备目录"
mkdir -p "$IMAGES" "$PKG/server"
say "输出：$PKG"

# ---------------------------------------------------------------- 1) 后端镜像
marker "1/6 后端镜像"
if [ "$DO_BUILD" -eq 1 ]; then
  docker build -t zjpdt-backend:latest ./server
  say "构建完成"
else
  say "跳过构建（--no-build），复用本地镜像"
fi
docker image inspect zjpdt-backend:latest >/dev/null 2>&1 \
  || die "镜像 zjpdt-backend:latest 不存在。先去掉 --no-build 重新执行"

# ---------------------------------------------------------------- 2) 前端镜像（dist 在容器内构建，宿主机无需 node）
marker "2/6 前端镜像"
if [ "$DO_BUILD" -eq 1 ]; then
  docker build -t zjpdt-web:latest ./web
  say "构建完成（node 阶段在容器内 npm ci + vite build，base=/）"
else
  say "跳过构建（--no-build），复用本地镜像"
fi
docker image inspect zjpdt-web:latest >/dev/null 2>&1 \
  || die "镜像 zjpdt-web:latest 不存在。先去掉 --no-build 重新执行"
# 关键断言：整栈形态前端在根路径直出，资源引用必须是 /assets/ 而非 /record/（base 错了浏览器必白屏）
docker run --rm --entrypoint sh zjpdt-web:latest -c 'grep -q "src=\"/assets/" /usr/share/nginx/html/index.html' \
  || die "镜像内 index.html 资源引用不是 /assets/ 开头——base 不对，禁止出包"

# ---------------------------------------------------------------- 3) 导出镜像
marker "3/6 导出镜像（docker save）"
docker save zjpdt-backend:latest -o "$IMAGES/zjpdt-backend.tar"
say "  OK  zjpdt-backend.tar  $(du -h "$IMAGES/zjpdt-backend.tar" | cut -f1)"
docker save zjpdt-web:latest -o "$IMAGES/zjpdt-web.tar"
say "  OK  zjpdt-web.tar      $(du -h "$IMAGES/zjpdt-web.tar" | cut -f1)"
if ! docker image inspect mysql:8.0 >/dev/null 2>&1; then
  say "  本地无 mysql:8.0，尝试拉取…"
  docker pull mysql:8.0 || die "拉取 mysql:8.0 失败；请在有网环境先 docker pull mysql:8.0"
fi
docker save mysql:8.0 -o "$IMAGES/mysql-8.0.tar"
say "  OK  mysql-8.0.tar      $(du -h "$IMAGES/mysql-8.0.tar" | cut -f1)"

# ---------------------------------------------------------------- 4) 编排与配置
marker "4/6 复制编排文件与配置模板"
cp deploy/stack/docker-compose.yml "$PKG/docker-compose.yml"
cp deploy/stack/.env.template      "$PKG/.env.template"
cp deploy/stack/server.env.docker  "$PKG/server/.env.docker"
cp deploy/nginx.zhijing.conf       "$PKG/nginx-site.conf"
cp deploy/stack/load.sh            "$PKG/load.sh"
cp deploy/stack/install.sh         "$PKG/install.sh"
cp deploy/stack/update.sh          "$PKG/update.sh"
cp deploy/stack/DEPLOY.md          "$PKG/DEPLOY.md"
chmod +x "$PKG/load.sh" "$PKG/install.sh" "$PKG/update.sh"
say "  OK  compose / env 模板 / 站点配置 / load+install+update / DEPLOY.md"

# ---------------------------------------------------------------- 5) 清单与总包
marker "5/6 生成 MANIFEST 并打包"
# MANIFEST 自身不参与校验和（它记录其他文件的 sha256）
CHECKSUMS="$( (cd "$PKG" && find . -type f ! -name MANIFEST.txt -exec sha256sum {} \;) )"
{
  echo "浙江公安方言语料采集平台 —— 整栈独立部署包（无宝塔，https://IP/）"
  echo "打包时间 : $(date '+%Y-%m-%d %H:%M:%S')"
  echo "Git 版本 : $(git rev-parse --short HEAD 2>/dev/null || echo '（非 git 仓库）')"
  echo ""
  echo "== 镜像 =="
  for t in zjpdt-backend:latest zjpdt-web:latest mysql:8.0; do
    echo "  $t"
    docker image inspect "$t" --format '    ID={{.Id}}  创建={{.Created}}  大小={{.Size}}' 2>/dev/null || true
  done
  echo ""
  echo "== 构建 == "
  echo "  前端：容器内 npm ci + vite build（base=/，VITE_API_BASE=/api），dist 打进 nginx:alpine"
  echo "  断言：镜像内 index.html 资源引用以 /assets/ 开头"
  echo ""
  echo "== 文件 sha256（服务器侧 sha256sum -c 核对传输完整性）=="
  echo "$CHECKSUMS"
  echo ""
  echo "== 服务器侧下一步（新机器首装）=="
  echo "  1) tar -xzf 本包.tar.gz && cd 包目录"
  echo "  2) bash install.sh               # 一键：导镜像/密钥/自签证书/起容器/全链验证，详见 DEPLOY.md §0.1"
  echo "  3) 防火墙/安全组放行 80、443，按 DEPLOY.md §7 全链验证"
  echo "  （已部署机器的增量升级：zjpdt-backend-*.tar.gz / zjpdt-web-*.tar.gz + update.sh，见 DEPLOY.md §9.4）"
} > "$PKG/MANIFEST.txt"
say "  OK  MANIFEST.txt"

TARBALL="${PKG}.tar.gz"
tar -czf "$TARBALL" -C "$(dirname "$PKG")" "$(basename "$PKG")"
say "  完成：$TARBALL  $(du -h "$TARBALL" | cut -f1)"
echo ""
echo "把下面这个文件传到目标服务器（数百 MB，走 SFTP/scp）："
echo "  $TARBALL"

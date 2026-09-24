#!/usr/bin/env bash
# 宝塔子路径部署包导出（在**有外网**的构建机上执行）
#
# 与 export-offline.sh 的区别：那是"内网整栈离线包"（含 web 容器+证书位），
# 这是"宝塔已有站点"形态——前端由宝塔 nginx 直接服务静态文件，包里只有
# backend + mysql 两个镜像与接入所需的 nginx 片段/手册。
#
# 产出 <out>/zjpdt-record-pkg-<时间戳>/
#   images/zjpdt-backend.tar    后端镜像
#   images/mysql-8.0.tar        MySQL 镜像
#   docker-compose.yml          编排（来源 deploy/record/docker-compose.yml；项目名锁死 zjpdt-record）
#   .env.template               密钥模板（服务器上 cp 为 .env，唯一必改文件）
#   server/.env.docker          应用默认值（无密钥；来源 deploy/record/server.env.docker）
#   record_web.tar.gz           前端产物（解到站点根形成 record/ 子目录）
#   nginx-record.conf           宝塔站点追加的 location 片段
#   load.sh                     服务器侧镜像导入+自检
#   update.sh                   增量升级一键脚本（分包部署：zjpdt-backend-*.tar.gz + record_web*.tar.gz）
#   install.sh                  首装一键脚本（导镜像/生成密钥/起容器/前端落盘/nginx 接入）
#   DEPLOY.md                   部署手册
#   MANIFEST.txt                sha256 + git 版本 + 构建命令
#   最后整体打一个 .tar.gz
#
# 用法：
#   bash scripts/export-record-package.sh                # 全新构建（镜像 + 前端）
#   bash scripts/export-record-package.sh --no-build     # 复用本地 zjpdt-backend:latest，跳过 docker build
#   bash scripts/export-record-package.sh --out /data/pkg

set -euo pipefail

DO_BUILD=1
OUT_DIR="./dist-record"

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

say() { printf '[export-record] %s\n' "$*"; }
die() { printf '[export-record] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker"
command -v node  >/dev/null 2>&1 || die "未找到 node（前端构建需要 Node 20+）"

STAMP="$(date +%Y%m%d-%H%M%S)"
PKG="${OUT_DIR%/}/zjpdt-record-pkg-${STAMP}"
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

# ---------------------------------------------------------------- 2) 前端构建（base=/record/）
marker "2/6 前端构建"
# npm ci 保证依赖树与 lockfile 一致（交付可复现）；build:record 全链 =
# vue-tsc 类型检查 + vite --mode record-demo --base=/record/ + Chrome80 语法体检 + 菜单路由自检
(cd web && npm ci --no-audit --no-fund && npm run build:record)
# 关键断言：入口资源引用必须以 /record/ 开头，否则 base 没生效、上宝塔必白屏
grep -qE '(src|href)="/record/' web/dist/index.html \
  || die "dist/index.html 资源引用不是 /record/ 开头——构建没吃到 --base，禁止出包"

# ---------------------------------------------------------------- 3) 导出镜像
marker "3/6 导出镜像（docker save）"
docker save zjpdt-backend:latest -o "$IMAGES/zjpdt-backend.tar"
say "  OK  zjpdt-backend.tar  $(du -h "$IMAGES/zjpdt-backend.tar" | cut -f1)"
if ! docker image inspect mysql:8.0 >/dev/null 2>&1; then
  say "  本地无 mysql:8.0，尝试拉取…"
  docker pull mysql:8.0 || die "拉取 mysql:8.0 失败；请在有网环境先 docker pull mysql:8.0"
fi
docker save mysql:8.0 -o "$IMAGES/mysql-8.0.tar"
say "  OK  mysql-8.0.tar      $(du -h "$IMAGES/mysql-8.0.tar" | cut -f1)"

# ---------------------------------------------------------------- 4) 前端产物打包
marker "4/6 前端产物打包"
# 打成含 record/ 顶层目录的 tar：服务器上 tar -xzf 到站点根即形成 record/ 子目录
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -r web/dist "$STAGE/record"
[ -f "$STAGE/record/index.html" ] || die "web/dist/index.html 缺失，构建异常"
tar -czf "$PKG/record_web.tar.gz" -C "$STAGE" record
say "  OK  record_web.tar.gz  $(du -h "$PKG/record_web.tar.gz" | cut -f1)"

# ---------------------------------------------------------------- 5) 编排与配置
marker "5/6 复制编排文件与配置模板"
cp deploy/record/docker-compose.yml "$PKG/docker-compose.yml"
cp deploy/record/.env.template      "$PKG/.env.template"
cp deploy/record/server.env.docker  "$PKG/server/.env.docker"
cp deploy/record/nginx-record.conf  "$PKG/nginx-record.conf"
cp deploy/record/load.sh            "$PKG/load.sh"
chmod +x "$PKG/load.sh"
cp deploy/record/update.sh          "$PKG/update.sh"
chmod +x "$PKG/update.sh"
cp deploy/record/install.sh          "$PKG/install.sh"
chmod +x "$PKG/install.sh"
cp deploy/record/DEPLOY.md          "$PKG/DEPLOY.md"
say "  OK  compose / env 模板 / nginx 片段 / load.sh / update.sh / DEPLOY.md"

# ---------------------------------------------------------------- 6) 清单与总包
marker "6/6 生成 MANIFEST 并打包"
CHECKSUMS="$( (cd "$PKG" && find . -type f ! -name MANIFEST.txt -exec sha256sum {} \;) )"
{
  echo "浙江公安方言语料采集平台 —— 宝塔 /record/ 子路径部署包"
  echo "打包时间 : $(date '+%Y-%m-%d %H:%M:%S')"
  echo "Git 版本 : $(git rev-parse --short HEAD 2>/dev/null || echo '（非 git 仓库）')"
  echo ""
  echo "== 镜像 =="
  for t in zjpdt-backend:latest mysql:8.0; do
    echo "  $t"
    docker image inspect "$t" --format '    ID={{.Id}}  创建={{.Created}}  大小={{.Size}}' 2>/dev/null || true
  done
  echo ""
  echo "== 构建 == "
  echo "  前端：npx vite build --mode record-demo --base=/record/（VITE_API_BASE=/record/api）"
  echo "  断言：dist/index.html 资源引用以 /record/ 开头"
  echo ""
  echo "== 文件 sha256（服务器侧 sha256sum -c 核对传输完整性）=="
  echo "$CHECKSUMS"
  echo ""
  echo "== 服务器侧下一步（新机器首装）=="
  echo "  1) tar -xzf 本包.tar.gz && cd 包目录"
  echo "  2) bash install.sh --domain <你的域名>   # 一键：导镜像/生成密钥/起容器/前端/nginx，详见 DEPLOY.md §0.1"
  echo "  3) 按 DEPLOY.md §9 全链验证"
  echo "  （已部署机器的增量升级：用 update.sh + 分包，见 DEPLOY.md §10.4）"
} > "$PKG/MANIFEST.txt"
say "  OK  MANIFEST.txt"

TARBALL="${PKG}.tar.gz"
tar -czf "$TARBALL" -C "$(dirname "$PKG")" "$(basename "$PKG")"
say "  完成：$TARBALL  $(du -h "$TARBALL" | cut -f1)"
echo ""
echo "把下面这个文件传到宝塔服务器（数百 MB，超过面板网页上传上限，走 SFTP/scp）："
echo "  $TARBALL"

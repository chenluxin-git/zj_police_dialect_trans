# 前端镜像：node 24 构建（vite 8 工具链要求 node ≥20.19，取与本机验证构建一致的 v24）→ nginx 托管
FROM node:24-alpine AS build
WORKDIR /app

# 先装依赖（利用层缓存）；内网走 npmmirror，可直连官方源时去掉 --registry
COPY package.json package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 443

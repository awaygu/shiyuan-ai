# ── 构建阶段 ──
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# 跳过 vue-tsc 类型检查（vue-tsc 1.x 与新版 TypeScript 存在兼容问题），直接构建
RUN npx vite build

# ── 服务阶段 ──
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

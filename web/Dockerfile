# ── 构建阶段 ──
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# 可选类型检查：CI 传入 RUN_TYPECHECK=true
ARG RUN_TYPECHECK=false
RUN if [ "$RUN_TYPECHECK" = "true" ]; then npx vue-tsc --noEmit; fi
RUN npx vite build

# ── 服务阶段 ──
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

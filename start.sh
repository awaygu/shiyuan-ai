#!/bin/bash

echo "========================================"
echo "  识渊 AI - 项目启动脚本"
echo "========================================"
echo

# ── 获取脚本所在目录 ──
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 检查 Python ──
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装 Python 3.10+"
    exit 1
fi

# ── 检查 Node ──
if ! command -v node &> /dev/null; then
    echo "[错误] 未找到 Node.js，请先安装 Node.js 18+"
    exit 1
fi

# ── 1. Python 虚拟环境 ──
if [ ! -d "server/venv" ]; then
    echo "[1/4] 创建 Python 虚拟环境..."
    cd server
    python3 -m venv venv
    cd "$SCRIPT_DIR"
else
    echo "[1/4] Python 虚拟环境已存在，跳过"
fi

# ── 2. 后端依赖 ──
if ! server/venv/bin/pip show fastapi &> /dev/null; then
    echo "[2/4] 安装后端依赖..."
    server/venv/bin/pip install -r server/requirements.txt
else
    echo "[2/4] 后端依赖已安装，跳过"
fi

# ── 3. Playwright 浏览器 ──
if [ ! -d "$HOME/Library/Caches/ms-playwright/chromium-"* ] 2>/dev/null; then
    echo "[3/4] 安装 Playwright 浏览器..."
    server/venv/bin/playwright install chromium
else
    echo "[3/4] Playwright 浏览器已安装，跳过"
fi

# ── 4. 前端依赖 ──
if [ ! -d "web/node_modules" ]; then
    echo "[4/4] 安装前端依赖..."
    cd web
    npm install
    cd "$SCRIPT_DIR"
else
    echo "[4/4] 前端依赖已安装，跳过"
fi

echo
echo "========================================"
echo "  启动服务..."
echo "========================================"
echo

# ── 检查 .env 文件 ──
if [ ! -f "server/.env" ]; then
    echo "[警告] 未找到 server/.env，请复制 .env.example 并填写配置"
    echo "        cp server/.env.example server/.env"
    echo
fi

# ── 启动后端 ──
echo "[后端] 启动 FastAPI 服务 (http://localhost:8000) ..."
cd server
nohup venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload > /tmp/shiyuan-backend.log 2>&1 &
BACKEND_PID=$!
cd "$SCRIPT_DIR"

# ── 启动前端 ──
echo "[前端] 启动 Vite 开发服务器 (http://localhost:3000) ..."
cd web
nohup npm run dev > /tmp/shiyuan-frontend.log 2>&1 &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

echo
echo "========================================"
echo "  服务已启动！"
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:3000"
echo "  后端日志: /tmp/shiyuan-backend.log"
echo "  前端日志: /tmp/shiyuan-frontend.log"
echo "  停止服务: kill $BACKEND_PID $FRONTEND_PID"
echo "========================================"

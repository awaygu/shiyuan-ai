@echo off
chcp 65001 >nul
echo ========================================
echo   识渊 AI - 项目启动脚本
echo ========================================
echo.

:: ── 检查 Python ──
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: ── 检查 Node ──
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Node.js，请先安装 Node.js 18+
    pause
    exit /b 1
)

:: ── 1. Python 虚拟环境 ──
if not exist "server\venv" (
    echo [1/4] 创建 Python 虚拟环境...
    cd server
    python -m venv venv
    cd ..
) else (
    echo [1/4] Python 虚拟环境已存在，跳过
)

:: ── 2. 后端依赖 ──
server\venv\Scripts\pip.exe show fastapi >nul 2>&1
if %errorlevel% neq 0 (
    echo [2/4] 安装后端依赖...
    cd server
    call venv\Scripts\activate && pip install -r requirements.txt && deactivate
    cd ..
) else (
    echo [2/4] 后端依赖已安装，跳过
)

:: ── 3. Playwright 浏览器 ──
if not exist "%LOCALAPPDATA%\ms-playwright\chromium-*" (
    echo [3/4] 安装 Playwright 浏览器...
    cd server
    call venv\Scripts\activate && playwright install chromium && deactivate
    cd ..
) else (
    echo [3/4] Playwright 浏览器已安装，跳过
)

:: ── 4. 前端依赖 ──
if not exist "web\node_modules" (
    echo [4/4] 安装前端依赖...
    cd web
    npm install
    cd ..
) else (
    echo [4/4] 前端依赖已安装，跳过
)

echo.
echo ========================================
echo   启动服务...
echo ========================================
echo.

:: ── 检查 .env 文件 ──
if not exist "server\.env" (
    echo [警告] 未找到 server\.env，请复制 .env.example 并填写配置
    echo         copy server\.env.example server\.env
    echo.
)

:: ── 启动后端 ──
echo [后端] 启动 FastAPI 服务 (http://localhost:8000) ...
start "识渊-后端" cmd /k "cd /d %~dp0server && venv\Scripts\activate && python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload"

:: ── 启动前端 ──
echo [前端] 启动 Vite 开发服务器 (http://localhost:8088) ...
start "识渊-前端" cmd /k "cd /d %~dp0web && npm run dev"

echo.
echo ========================================
echo   服务已启动！
echo   后端: http://localhost:8000
echo   前端: http://localhost:8088
echo ========================================
echo.
timeout /t 3 >nul

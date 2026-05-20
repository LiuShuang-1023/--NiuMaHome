@echo off
chcp 65001 >nul
title 牛马归栏 NiuMaHome 启动器

echo.
echo  ██████████████████████████████████████
echo  █                                    █
echo  █    🐂 牛马归栏 NiuMaHome v0.3.2    █
echo  █       打工人的 AI 租房助理          █
echo  █                                    █
echo  ██████████████████████████████████████
echo.

:: ── 路径定位（相对于本文件所在目录）──────────────────────────
set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend
set PYTHON=%BACKEND%\.venv\Scripts\python.exe
set UVICORN=%BACKEND%\.venv\Scripts\uvicorn.exe

:: ── 检查 Python 虚拟环境 ──────────────────────────────────────
if not exist "%PYTHON%" (
    echo [错误] 未找到 Python 虚拟环境：%PYTHON%
    echo 请确认解压完整，.venv 目录应在 backend\ 下。
    pause
    exit /b 1
)

:: ── 检查 Node.js ──────────────────────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Node.js！
    echo.
    echo 请先安装 Node.js LTS：https://nodejs.org/zh-cn/download
    echo 安装完成后重新双击本文件启动。
    echo.
    pause
    exit /b 1
)

:: ── 检查 .env.local ───────────────────────────────────────────
if not exist "%FRONTEND%\.env.local" (
    echo [警告] 未找到 %FRONTEND%\.env.local
    echo.
    echo 请复制 frontend\.env.local.example 为 frontend\.env.local
    echo 并填入你的 API Key，然后重新启动。
    echo.
    pause
    exit /b 1
)

:: ── 检查前端是否已构建 ────────────────────────────────────────
if not exist "%FRONTEND%\.next\BUILD_ID" (
    echo [提示] 前端尚未构建，正在构建（首次约需 30-60 秒）...
    echo.
    cd /d "%FRONTEND%"
    call npm run build
    if errorlevel 1 (
        echo [错误] 前端构建失败，请检查 Node.js 版本或网络。
        pause
        exit /b 1
    )
    echo.
    echo [OK] 前端构建完成。
    echo.
)

:: ── 启动后端 ──────────────────────────────────────────────────
echo [1/2] 启动后端服务（端口 8000）...
cd /d "%BACKEND%"
start "牛马归栏-后端" cmd /k "title 牛马归栏-后端 && "%UVICORN%" app.main:app --host 0.0.0.0 --port 8000"

:: ── 等待后端就绪 ──────────────────────────────────────────────
echo     等待后端启动...
:wait_backend
timeout /t 1 /nobreak >nul
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto wait_backend
echo     [OK] 后端已就绪。

:: ── 启动前端 ──────────────────────────────────────────────────
echo [2/2] 启动前端服务（端口 3000）...
cd /d "%FRONTEND%"
start "牛马归栏-前端" cmd /k "title 牛马归栏-前端 && npm run start"

:: ── 等待前端就绪 ──────────────────────────────────────────────
echo     等待前端启动...
timeout /t 4 /nobreak >nul

:: ── 打开浏览器 ────────────────────────────────────────────────
echo [OK] 正在打开浏览器...
start http://localhost:3000

echo.
echo  ✅ 牛马归栏已启动！
echo     前端：http://localhost:3000
echo     后端：http://localhost:8000
echo.
echo  关闭程序：直接关闭"牛马归栏-后端"和"牛马归栏-前端"两个窗口即可。
echo.
pause

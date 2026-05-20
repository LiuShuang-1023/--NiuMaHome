@echo off
chcp 65001 > nul
echo ========================================
echo   牛马归栏 - 前端缓存重置 + 启动
echo ========================================
cd /d "%~dp0frontend"

echo [1/3] 清理 Next.js 构建缓存...
if exist .next (
    rmdir /s /q .next
    echo   .next 目录已删除
)

echo [2/3] 检查依赖...
if not exist node_modules (
    echo   首次运行，安装依赖...
    call npm install
)

echo [3/3] 启动 Next.js 开发服务器 (http://localhost:3000)
call npm run dev

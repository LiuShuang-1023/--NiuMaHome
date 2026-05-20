@echo off
chcp 65001 >nul
title 牛马归栏 - 前端
cd /d "%~dp0frontend"
echo [前端] 启动中...
npm run dev
pause

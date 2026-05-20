@echo off
chcp 65001 >nul
title 牛马归栏 - 后端
cd /d "%~dp0backend"
echo [后端] 启动中...
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause

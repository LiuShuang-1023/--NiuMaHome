@echo off
chcp 65001 >nul
title 牛马归栏 - 关闭所有服务

echo 正在关闭牛马归栏后端和前端...

:: 关闭占用 8000 端口的进程（后端）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 "') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: 关闭占用 3000 端口的进程（前端）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000 "') do (
    taskkill /PID %%p /F >nul 2>&1
)

echo [OK] 已关闭所有服务。
timeout /t 2 /nobreak >nul

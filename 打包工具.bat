@echo off
chcp 65001 >nul
title 牛马归栏 - 打包工具

echo.
echo  ============================================
echo    牛马归栏 NiuMaHome - 打包工具
echo    打包完成后会生成 NiuMaHome_v0.3.2.zip
echo  ============================================
echo.

set ROOT=%~dp0
set OUT_NAME=NiuMaHome_v0.3.2
set OUT_DIR=%ROOT%%OUT_NAME%
set ZIP_FILE=%ROOT%%OUT_NAME%.zip

:: ── Step 1: 构建前端（生产模式）──────────────────────────────
echo [1/4] 构建前端（next build）...
cd /d "%ROOT%frontend"
call npm run build
if errorlevel 1 (
    echo [错误] 前端构建失败！
    pause
    exit /b 1
)
echo [OK] 前端构建完成。
echo.

:: ── Step 2: 清理旧的打包目录 ─────────────────────────────────
echo [2/4] 准备打包目录...
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

:: ── Step 3: 复制文件 ─────────────────────────────────────────
echo [3/4] 复制文件...

:: 后端
xcopy "%ROOT%backend" "%OUT_DIR%\backend" /E /I /Q /EXCLUDE:"%ROOT%pack_exclude.txt"
echo     [OK] 后端复制完成

:: 前端（包含 .next 构建产物和 node_modules）
xcopy "%ROOT%frontend" "%OUT_DIR%\frontend" /E /I /Q /EXCLUDE:"%ROOT%pack_exclude.txt"
echo     [OK] 前端复制完成

:: 根目录文件
copy "%ROOT%启动牛马归栏.bat"  "%OUT_DIR%\启动牛马归栏.bat" >nul
copy "%ROOT%关闭牛马归栏.bat"  "%OUT_DIR%\关闭牛马归栏.bat" >nul
copy "%ROOT%.env.local.example" "%OUT_DIR%\.env.local.example" >nul
if exist "%ROOT%.env.local" copy "%ROOT%.env.local" "%OUT_DIR%\.env.local" >nul
copy "%ROOT%README.md"         "%OUT_DIR%\README.md" >nul 2>&1

:: 写一个简单的说明文件
(
echo 牛马归栏 NiuMaHome v0.3.2 便携版
echo =====================================
echo.
echo 使用前请先：
echo 1. 安装 Node.js LTS：https://nodejs.org/zh-cn/download
echo    （已安装则跳过）
echo.
echo 2. 配置 API Key：
echo    - 将 .env.local.example 复制一份，重命名为 .env.local
echo    - 用记事本打开，填入你的 DeepSeek Key 和高德 Key
echo    - 保存
echo.
echo 3. 双击"启动牛马归栏.bat"
echo    首次启动会自动构建前端（约30秒），之后每次秒开。
echo.
echo 关闭：双击"关闭牛马归栏.bat"，或直接关闭两个命令行窗口。
echo.
echo 注意：需要联网才能使用（AI对话和地图API需要网络）。
) > "%OUT_DIR%\使用说明.txt"

echo     [OK] 说明文件写入完成
echo.

:: ── Step 4: 压缩 ─────────────────────────────────────────────
echo [4/4] 压缩打包（使用 PowerShell，可能需要几分钟）...
if exist "%ZIP_FILE%" del "%ZIP_FILE%"

powershell -Command "Compress-Archive -Path '%OUT_DIR%\*' -DestinationPath '%ZIP_FILE%' -CompressionLevel Optimal"

if errorlevel 1 (
    echo [错误] 压缩失败！
    echo 打包目录已在：%OUT_DIR%
    echo 可以手动压缩该目录。
    pause
    exit /b 1
)

:: 清理临时目录
rmdir /s /q "%OUT_DIR%"

echo.
echo  ✅ 打包完成！
echo     输出文件：%ZIP_FILE%
echo.

:: 显示文件大小
powershell -Command "& { $s = (Get-Item '%ZIP_FILE%').Length; Write-Host ('     文件大小：' + [math]::Round($s/1MB,1) + ' MB') }"

echo.
echo  将 %OUT_NAME%.zip 发给别人，解压后双击"启动牛马归栏.bat"即可。
echo  （目标电脑需提前安装 Node.js LTS，其他无需安装任何东西）
echo.
pause

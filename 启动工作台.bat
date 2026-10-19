@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  全本地自动短剧视频生成 · 工作台启动器
rem  作者：太阳阶梯jqk8707
rem  用法一：把项目文件夹拖到本文件图标上
rem  用法二：把本文件复制进项目文件夹，双击
rem  用法三：命令行 启动工作台.bat "C:\Users\<用户名>\Downloads\剧名-20261018"
rem ============================================================

set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "SKILL=C:\Users\Administrator\.workbuddy\skills\auto-drama-video"
set "PROJ=%~1"

if "%PROJ%"=="" set "PROJ=%~dp0"
if not exist "%PROJ%\drama.json" (
  echo [x] 这里没有 drama.json：%PROJ%
  echo     请把项目文件夹拖到本文件上，或在项目文件夹里双击本文件。
  echo.
  pause
  exit /b 1
)

echo 项目：%PROJ%
echo 地址：http://127.0.0.1:8765/   （关掉这个窗口 = 停止服务）
echo.
"%PY%" "%SKILL%\scripts\drama.py" serve --project "%PROJ%" --port 8765
echo.
echo 服务已停止。
pause

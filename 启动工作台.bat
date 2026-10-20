@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  Auto Drama Video - Workbench Launcher
rem  Author: taiyangjieti jqk8707
rem
rem  Usage 1: drag a project folder onto this file
rem  Usage 2: copy this file into the project folder and double-click
rem  Usage 3: this file "D:\downloads\drama-20261018"
rem
rem  Nothing is hardcoded:
rem    project = dropped folder, else current dir, else this file's folder
rem    skill   = this file's folder, else AUTO_DRAMA_HOME, else current dir,
rem              else the .drama-skill pointer inside the project
rem    python  = AUTO_DRAMA_PY, else "py -3", else "python"
rem ============================================================

rem ---- 1) project dir ----
set "PROJ=%~1"
if "%PROJ%"=="" if exist "%CD%\drama.json" set "PROJ=%CD%"
if "%PROJ%"=="" if exist "%~dp0drama.json" set "PROJ=%~dp0"
if "%PROJ%"=="" set "PROJ=%CD%"

rem ---- 2) skill dir ----
set "SKILL=%~dp0"
if exist "%SKILL%scripts\drama.py" goto :skill_ok
if not defined AUTO_DRAMA_HOME goto :skill_cwd
set "SKILL=%AUTO_DRAMA_HOME%\"
if exist "%SKILL%scripts\drama.py" goto :skill_ok
:skill_cwd
set "SKILL=%CD%\"
if exist "%SKILL%scripts\drama.py" goto :skill_ok
:skill_ptr
if not exist "%PROJ%\.drama-skill" goto :skill_fail
set /p SKILL=<"%PROJ%\.drama-skill"
set "SKILL=%SKILL%\"
if exist "%SKILL%scripts\drama.py" goto :skill_ok
:skill_fail
echo [x] 没找到 scripts\drama.py
echo     请把本文件放回技能目录再双击；或先设好环境变量：
echo         set AUTO_DRAMA_HOME=技能目录的完整路径
echo.
pause
exit /b 1
:skill_ok

rem ---- 3) python ----
set "PY="
if defined AUTO_DRAMA_PY if exist "%AUTO_DRAMA_PY%" set "PY=%AUTO_DRAMA_PY%"
if defined PY goto :py_ok
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if defined PY goto :py_ok
python -c "import sys" >nul 2>nul && set "PY=python"
if defined PY goto :py_ok
echo [x] 没找到 Python。请装 Python 3.9+ 并加入 PATH，
echo     或先设好环境变量：set AUTO_DRAMA_PY=python.exe 的完整路径
echo.
pause
exit /b 1
:py_ok

rem ---- 4) project check + serve ----
if not exist "%PROJ%\drama.json" goto :no_project

echo 项目：%PROJ%
echo 技能：%SKILL%
echo 地址：http://127.0.0.1:8765/   （关掉这个窗口 = 停止服务）
echo.
%PY% "%SKILL%scripts\drama.py" serve --project "%PROJ%" --port 8765
echo.
echo 服务已停止。
pause
exit /b 0

:no_project
echo [x] 这个目录里没有 drama.json：%PROJ%
echo     请把项目文件夹拖到本文件上，或在项目文件夹里双击本文件。
echo.
pause
exit /b 1

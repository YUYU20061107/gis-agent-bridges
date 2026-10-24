@echo off
chcp 65001 >nul
setlocal
rem ==== SuperMap 文件回退桥启动器（在工作空间副本上起桥，原文件只读） ====
rem 用法: 把 .smwu 工作空间文件拖到本脚本上，或在命令行执行:
rem    start_bridge.cmd "C:\path\to\workspace.smwu"
rem
rem 按你的机器修改下面几项（也可以预先用同名环境变量覆盖）:
rem   PY                   带 iobjectspy 的 Python 运行时
rem                        （搭建方法见 docs/CALIBRATION-RESULTS-20261024.md）
rem   SM_BRIDGE_TOKEN_FILE token 文件位置
rem   SM_BRIDGE_WORK_DIR   副本工作目录
rem   IDESKTOP_HOME        iDesktop 安装目录（下面是产品默认安装路径，按你的安装位置修改）
if not defined PY set "PY=python"
if not defined SM_BRIDGE_TOKEN_FILE set "SM_BRIDGE_TOKEN_FILE=%USERPROFILE%\.supermap-live-bridge\bridge.token"
if not defined SM_BRIDGE_WORK_DIR set "SM_BRIDGE_WORK_DIR=%USERPROFILE%\.supermap-live-bridge\work"
set "IDESKTOP_HOME=C:\SuperMap\SuperMap iDesktop 10i"
set "PYTHONIOENCODING=utf-8"
set "PATH=%IDESKTOP_HOME%\Bin;%IDESKTOP_HOME%\Tools\jre\bin;%PATH%"

if "%~1"=="" (
  echo 用法: 把 .smwu 工作空间文件拖到本脚本上，或在命令行执行:
  echo    start_bridge.cmd "C:\path\to\workspace.smwu"
  pause
  exit /b 2
)

echo.
echo 即将在【工作空间副本】上启动桥（原文件只读）。
echo   工作空间: %~1
echo   桥地址  : 127.0.0.1:47615
echo   停止    : 在此窗口按 Ctrl+C
echo.
"%PY%" "%~dp0run_bridge_copy.py" "%~1" --work-dir "%SM_BRIDGE_WORK_DIR%"
pause

@echo off
rem ============================================================
rem  tiaoyige / bayi - one click launcher (Windows)
rem
rem  This file only does three things:
rem    1. switch the console to UTF-8 (chcp 65001) so Chinese shows up
rem    2. hand every argument to scripts\launch.ps1
rem    3. pause on failure so the window does not flash and disappear
rem  All the real logic lives in the ps1 - cmd syntax is a bad fit for
rem  "check python version / detect GPU / probe port".
rem
rem  Encoding rules (do not "fix" them):
rem    * no BOM. cmd.exe would treat the BOM as part of the first command
rem      and print a confusing error.
rem    * CRLF line endings (.gitattributes says so for *.bat).
rem    * everything above the chcp line stays ASCII: cmd re-reads this file
rem      with the *current* code page, so Chinese text before the switch
rem      can desync the parser on some systems.
rem ============================================================

chcp 65001 >nul
setlocal
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo.
    echo [错误] 找不到 powershell.exe —— 这台机器上的 Windows PowerShell 似乎不完整。
    echo        帮你挑一个的启动器是用 PowerShell 写的，没有它没法自动建环境、装依赖、下模型。
    echo        可以手动启动：先装好依赖，再执行
    echo            .venv\Scripts\python.exe -m tiaoyige.server --open-browser
    echo.
    pause
    endlocal
    exit /b 1
)

echo [启动] 正在准备帮你挑一个，第一次启动会比较久，请不要关掉这个窗口...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo [提示] 启动失败（退出码 %CODE%）。上面标着「失败」的那几行就是原因和办法。
    echo [提示] 最常见的三种：没装 Python 3.10 以上、网络慢装不上依赖、端口被占用。
    echo.
    pause
)

rem 必须写成一行：cmd 会先把整行的 %CODE% 展开再执行，
rem 分成两行的话 endlocal 已经把 CODE 清掉了，退出码会永远是 0。
endlocal & exit /b %CODE%

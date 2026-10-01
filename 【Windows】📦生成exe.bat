@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "PROJECT_LAUNCHER=%SCRIPT_DIR%LANFileServer\启动LANFileServer.bat"
if not exist "%PROJECT_LAUNCHER%" set "PROJECT_LAUNCHER=%SCRIPT_DIR%..\LANFileServer\启动LANFileServer.bat"

if not exist "%PROJECT_LAUNCHER%" (
    echo 未找到项目启动器：%PROJECT_LAUNCHER%
    echo Build clears old dist. On success, reveal output and launch the packaged app.
pause
    exit /b 1
)

call "%PROJECT_LAUNCHER%" build-exe %*
exit /b %ERRORLEVEL%

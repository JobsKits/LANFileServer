@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "PROJECT_LAUNCHER=%SCRIPT_DIR%LANFileServer\启动LANFileServer.bat"
if not exist "%PROJECT_LAUNCHER%" set "PROJECT_LAUNCHER=%SCRIPT_DIR%..\LANFileServer\启动LANFileServer.bat"

if not exist "%PROJECT_LAUNCHER%" (
    echo 未找到项目启动器：%PROJECT_LAUNCHER%
    pause
    exit /b 1
)

call "%PROJECT_LAUNCHER%" %*
exit /b %ERRORLEVEL%

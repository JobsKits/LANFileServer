@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem 脚本自述：
rem - 脚本名称：启动LANFileServer.bat
rem - 核心用途：Windows 一键准备 Python 运行环境，并启动 LANFileServer 图形界面；内部保留 EXE 打包能力。
rem - 影响范围：日常启动会创建或复用 .venv，并按 requirements.txt 安装运行依赖；build-exe 模式会生成 dist\YYYY.MM.DD HH-mm-ss\LANFileServer.exe。
rem - 运行提示：双击默认启动程序，不需要手动 cd 或执行其它脚本。

set "SCRIPT_DIR=%~dp0"
set "APP_NAME=LANFileServer"
set "ENTRY_FILE=%SCRIPT_DIR%LANFileServer.py"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "PYTHON_BIN=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS_FILE=%SCRIPT_DIR%requirements.txt"
set "BUILD_REQUIREMENTS_FILE=%SCRIPT_DIR%requirements-build.txt"
set "LOG_FILE=%TEMP%\启动LANFileServer-windows.log"
break > "%LOG_FILE%"

call :show_intro
call :run_requested_mode %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo 日志位置：%LOG_FILE%
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%

:log
echo %~1
echo %~1>> "%LOG_FILE%"
exit /b 0

:show_intro
call :log "============================== 脚本自述 =============================="
call :log "当前脚本：%~f0"
call :log "核心用途：双击 .bat，一键启动 LANFileServer。"
call :log "影响范围：会创建或复用 %VENV_DIR%，首次运行可能通过 pip 安装 PySide6。"
call :log "构建产物按本机年月日时分秒保存到 dist/YYYY.MM.DD HH-mm-ss/（例如 2020.06.04 12-23-21），同次构建共用一个时间目录。"
call :log "内部能力：传入 build-exe 参数时，可用同一个 .bat 生成 Windows EXE。"
call :log "======================================================================="
exit /b 0

:run_requested_mode
if /I "%~1"=="build-exe" (
    call :run_build_flow
) else (
    call :run_app_flow
)
exit /b %ERRORLEVEL%

:run_app_flow
call :check_environment || exit /b 1
call :prepare_virtualenv || exit /b 1
call :install_missing_dependencies || exit /b 1
call :check_python_entry || exit /b 1
call :launch_app
exit /b %ERRORLEVEL%

:run_build_flow
call :check_environment || exit /b 1
call :prepare_virtualenv || exit /b 1
call :install_missing_build_dependencies || exit /b 1
call :check_python_entry || exit /b 1
call :build_windows_exe
exit /b %ERRORLEVEL%

:check_environment
call :find_python || exit /b 1
if not exist "%ENTRY_FILE%" (
    call :log "错误：未找到入口文件：%ENTRY_FILE%"
    exit /b 1
)
if not exist "%REQUIREMENTS_FILE%" (
    call :log "错误：未找到依赖文件：%REQUIREMENTS_FILE%"
    exit /b 1
)
exit /b 0

:find_python
where py >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    set "PYTHON_CMD=py -3"
    exit /b 0
)
where python >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    set "PYTHON_CMD=python"
    exit /b 0
)
call :log "错误：未找到 Python 3，请先安装 Python 3 并加入 PATH。"
exit /b 1

:prepare_virtualenv
if exist "%PYTHON_BIN%" (
    call :log "已检测到虚拟环境：%VENV_DIR%"
    exit /b 0
)
call :log "未检测到虚拟环境，开始创建：%VENV_DIR%"
%PYTHON_CMD% -m venv "%VENV_DIR%" >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:runtime_dependencies_ready
"%PYTHON_BIN%" -c "import PIL, PySide6, pillow_heif, qrcode" >nul 2>nul
exit /b %ERRORLEVEL%

:install_missing_dependencies
call :runtime_dependencies_ready
if "%ERRORLEVEL%"=="0" (
    call :log "运行依赖已就绪。"
    exit /b 0
)
call :confirm_required_install "Missing runtime dependencies" || exit /b 1
call :log "运行依赖缺失，开始安装 requirements.txt。"
"%PYTHON_BIN%" -m pip install -r "%REQUIREMENTS_FILE%" >> "%LOG_FILE%" 2>&1 || exit /b 1
call :runtime_dependencies_ready
if not "%ERRORLEVEL%"=="0" (
    call :log "错误：依赖安装后仍不完整，请查看日志：%LOG_FILE%"
    exit /b 1
)
exit /b 0

:build_dependencies_ready
"%PYTHON_BIN%" -c "import PIL, PySide6, pillow_heif, qrcode, PyInstaller" >nul 2>nul
exit /b %ERRORLEVEL%

:install_missing_build_dependencies
if not exist "%BUILD_REQUIREMENTS_FILE%" (
    call :log "错误：未找到打包依赖文件：%BUILD_REQUIREMENTS_FILE%"
    exit /b 1
)
call :build_dependencies_ready
if "%ERRORLEVEL%"=="0" (
    call :log "打包依赖已就绪。"
    exit /b 0
)
call :confirm_required_install "Missing build dependencies" || exit /b 1
call :log "打包依赖缺失，开始安装 requirements-build.txt。"
"%PYTHON_BIN%" -m pip install -r "%BUILD_REQUIREMENTS_FILE%" >> "%LOG_FILE%" 2>&1 || exit /b 1
call :build_dependencies_ready || exit /b 1
exit /b 0

:check_python_entry
"%PYTHON_BIN%" -m py_compile "%ENTRY_FILE%" >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:launch_app
pushd "%SCRIPT_DIR%" >nul
call :log "准备启动 %APP_NAME%。"
"%PYTHON_BIN%" "%ENTRY_FILE%" >> "%LOG_FILE%" 2>&1
set "APP_EXIT=%ERRORLEVEL%"
popd >nul
exit /b %APP_EXIT%

:build_windows_exe
for %%I in ("%SCRIPT_DIR%..") do set "DELIVERY_DIR=%%~fI"
set "DIST_ROOT=%DELIVERY_DIR%\dist"
set "DIST_DIR=%DIST_ROOT%"
"%PYTHON_BIN%" "%SCRIPT_DIR%scripts\artifact_shortcuts.py" --root "%DELIVERY_DIR%" --clear || exit /b 1
pushd "%SCRIPT_DIR%" >nul
call :log "开始打包 Windows EXE。"
fsutil reparsepoint query "%DIST_ROOT%" >nul 2>nul
if not errorlevel 1 exit /b 1
if exist "%DIST_ROOT%" rmdir /s /q "%DIST_ROOT%"
if exist "%DIST_ROOT%" (popd & exit /b 1)
set "BUILD_STAMP="
for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy.MM.dd HH-mm-ss'"') do set "BUILD_STAMP=%%T"
if not defined BUILD_STAMP (popd & exit /b 1)
set "DIST_DIR=%DIST_ROOT%\%BUILD_STAMP%"
echo Build time (YYYY.MM.DD HH-mm-ss): %BUILD_STAMP%
"%PYTHON_BIN%" -m PyInstaller --noconfirm --clean --distpath "%DIST_DIR%" --windowed --onefile --name "%APP_NAME%" "%ENTRY_FILE%" >> "%LOG_FILE%" 2>&1
set "BUILD_EXIT=%ERRORLEVEL%"
if "%BUILD_EXIT%"=="0" (
    if not exist "%DIST_DIR%\%APP_NAME%.exe" (popd & exit /b 1)
    call :log "EXE 已生成：%DIST_DIR%\%APP_NAME%.exe"
    "%PYTHON_BIN%" "%SCRIPT_DIR%scripts\artifact_shortcuts.py" --root "%DELIVERY_DIR%" "%DIST_DIR%\%APP_NAME%.exe" || exit /b 1
    start "" explorer.exe "%DIST_DIR%"
    start "" /D "%DIST_DIR%" "%DIST_DIR%\%APP_NAME%.exe"
)
popd >nul
exit /b %BUILD_EXIT%

:confirm_required_install
rem ReadLine 保留空格，并把 EOF 当成取消。
powershell -NoProfile -Command "[Console]::Write('%~1 (Enter to install; any character to cancel): '); $answer = [Console]::ReadLine(); if ($null -eq $answer -or $answer.Length -gt 0) { exit 1 }; exit 0"
if errorlevel 1 (
  echo Dependency installation cancelled. Stopping current task.
  exit /b 1
)
exit /b 0

#!/bin/zsh
# 脚本自述：
# - 脚本名称：启动LANFileServer.command
# - 核心用途：一键准备 Python 打包环境，并生成可安装的 LANFileServer.dmg。
# - 影响范围：会创建或复用 .venv / .venv-universal2，安装打包依赖，并生成 dist/*.app 与外层目录的 *.dmg。
# - 运行提示：双击后直接进入 DMG 打包流程，不需要手动 cd 或输入多条命令。

setopt NO_NOMATCH
setopt PIPE_FAIL

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename -- "$0")"
SCRIPT_BASENAME=$(basename "$0" | sed 's/\.[^.]*$//')
LOG_FILE="/tmp/${SCRIPT_BASENAME}.log"
: > "$LOG_FILE"

APP_NAME="LANFileServer"
PROJECT_DIR="${SCRIPT_DIR}"
ENTRY_FILE="${PROJECT_DIR}/LANFileServer.py"
VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
VENV_CREATOR="python3"
UNIVERSAL_VENV_DIR="${PROJECT_DIR}/.venv-universal2"
REQUIREMENTS_FILE="${PROJECT_DIR}/requirements.txt"
BUILD_REQUIREMENTS_FILE="${PROJECT_DIR}/requirements-build.txt"
TARGET_ARCH="${TARGET_ARCH:-universal2}"
DMG_OUTPUT_DIR="${LAN_FILE_SERVER_OUTPUT_DIR:-$(cd "${PROJECT_DIR}/.." && pwd)}"

log()            { echo -e "$1" | tee -a "$LOG_FILE"; }
success_echo()   { log "\033[1;32m✔ $1\033[0m"; }
warn_echo()      { log "\033[1;33m⚠ $1\033[0m"; }
note_echo()      { log "\033[1;35m➤ $1\033[0m"; }
error_echo()     { log "\033[1;31m✖ $1\033[0m"; }
highlight_echo() { log "\033[1;36m🔹 $1\033[0m"; }
gray_echo()      { log "\033[0;90m$1\033[0m"; }

# 打印脚本内置自述，并直接继续启动流程。
show_script_intro() {
  if [[ "${LAN_FILE_SERVER_CONFIRMED:-0}" == "1" ]]; then
    note_echo "已由外层入口确认，继续执行 DMG 打包流程。"
    return 0
  fi
  if [[ -t 1 && -n "${TERM:-}" && "${TERM:-}" != "dumb" ]]; then
    clear
  fi
  highlight_echo "============================== 脚本自述 =============================="
  note_echo "当前脚本：${SCRIPT_PATH}"
  note_echo "核心用途：自动进入项目目录，准备对应架构的虚拟环境，安装缺失依赖，并生成 ${APP_NAME}.dmg。"
  warn_echo "影响范围：会创建或复用 .venv / .venv-universal2，生成 ${PROJECT_DIR}/dist 与 ${DMG_OUTPUT_DIR}/*.dmg。"
  gray_echo "日志位置：${LOG_FILE}"
  highlight_echo "======================================================================="
  echo ""
}
# 检查 Python 和项目入口文件是否存在。
check_environment() {
  if ! command -v python3 >/dev/null 2>&1; then
    error_echo "未找到 python3，请先安装 Python 3。"
    exit 1
  fi
  if [[ ! -f "${ENTRY_FILE}" ]]; then
    error_echo "未找到入口文件：${ENTRY_FILE}"
    exit 1
  fi
  if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
    error_echo "未找到依赖文件：${REQUIREMENTS_FILE}"
    exit 1
  fi
}
# 创建或复用当前项目的 Python 虚拟环境。
prepare_virtualenv() {
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    note_echo "未检测到虚拟环境，开始创建：${VENV_DIR}"
    "${VENV_CREATOR}" -m venv "${VENV_DIR}" 2>&1 | tee -a "$LOG_FILE"
  else
    success_echo "已检测到虚拟环境：${VENV_DIR}"
  fi
}
# 检查候选 Python 及其标准动态扩展是否同时包含 Intel 和 Apple Silicon 架构。
python_supports_universal2() {
  local python_path="$1"
  local extension_path=""
  local binary_info=""
  [[ -x "${python_path}" ]] || return 1
  extension_path="$("${python_path}" -c 'import _bisect; print(_bisect.__file__)' 2>/dev/null)" || return 1
  binary_info="$(file "${python_path}" "${extension_path}" 2>/dev/null)"
  [[ "${binary_info}" == *"x86_64"* && "${binary_info}" == *"arm64"* ]]
}
# 为 universal2 打包切换到系统自带的双架构 Python 和独立虚拟环境。
select_macos_build_python() {
  local universal_python="/usr/bin/python3"
  if [[ "${TARGET_ARCH}" != "universal2" ]]; then
    return 0
  fi
  if ! python_supports_universal2 "${universal_python}"; then
    warn_echo "未找到可用的 universal2 Python，将继续使用当前 Python 并在必要时回退架构。"
    return 0
  fi
  VENV_CREATOR="${universal_python}"
  VENV_DIR="${UNIVERSAL_VENV_DIR}"
  PYTHON_BIN="${VENV_DIR}/bin/python"
  success_echo "已选择 universal2 Python：${universal_python}"
}
# 判断运行依赖是否已经可用。
runtime_dependencies_ready() {
  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import PySide6
PY
}
# 安装缺失的运行依赖。
install_missing_dependencies() {
  if runtime_dependencies_ready; then
    success_echo "运行依赖已就绪。"
    return 0
  fi
  note_echo "运行依赖缺失，开始安装 requirements.txt。"
  "${PYTHON_BIN}" -m pip install --upgrade pip 2>&1 | tee -a "$LOG_FILE"
  "${PYTHON_BIN}" -m pip install -r "${REQUIREMENTS_FILE}" 2>&1 | tee -a "$LOG_FILE"
  if ! runtime_dependencies_ready; then
    error_echo "依赖安装后仍无法导入 PySide6，请查看日志：${LOG_FILE}"
    exit 1
  fi
}
# 判断打包依赖是否已经可用。
build_dependencies_ready() {
  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import PyInstaller
PY
}
# 安装缺失的打包依赖。
install_missing_build_dependencies() {
  if build_dependencies_ready; then
    success_echo "打包依赖已就绪。"
    return 0
  fi
  if [[ ! -f "${BUILD_REQUIREMENTS_FILE}" ]]; then
    error_echo "未找到打包依赖文件：${BUILD_REQUIREMENTS_FILE}"
    exit 1
  fi
  note_echo "打包依赖缺失，开始安装 requirements-build.txt。"
  "${PYTHON_BIN}" -m pip install --upgrade pip 2>&1 | tee -a "$LOG_FILE" || exit 1
  "${PYTHON_BIN}" -m pip install -r "${BUILD_REQUIREMENTS_FILE}" 2>&1 | tee -a "$LOG_FILE" || exit 1
}
# 检查 Python 入口文件语法。
check_python_entry() {
  "${PYTHON_BIN}" -m py_compile "${ENTRY_FILE}" 2>&1 | tee -a "$LOG_FILE"
}
# 检查 macOS 打包所需环境。
check_macos_build_environment() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    error_echo "DMG 打包只能在 macOS 上执行。"
    exit 1
  fi
  if ! command -v hdiutil >/dev/null 2>&1; then
    error_echo "未找到 hdiutil，无法生成 DMG。"
    exit 1
  fi
}
# 启动 LANFileServer 图形界面。
launch_app() {
  cd "${PROJECT_DIR}" || exit 1
  success_echo "准备启动 ${APP_NAME}。"
  "${PYTHON_BIN}" "${ENTRY_FILE}" 2>&1 | tee -a "$LOG_FILE"
}
# 使用 PyInstaller 生成 macOS .app。
build_macos_app_with_arch() {
  local build_arch="$1"
  cd "${PROJECT_DIR}" || exit 1
  note_echo "开始打包 macOS .app，目标架构：${build_arch}"
  "${PYTHON_BIN}" -m PyInstaller --noconfirm --clean --windowed --name "${APP_NAME}" --target-arch "${build_arch}" "${ENTRY_FILE}" 2>&1 | tee -a "$LOG_FILE"
}
# 获取当前机器原生架构。
get_native_arch() {
  [[ "$(uname -m)" == "arm64" ]] && echo "arm64" || echo "x86_64"
}
# 使用 PyInstaller 生成 macOS .app，必要时从 universal2 回退到原生架构。
build_macos_app() {
  if build_macos_app_with_arch "${TARGET_ARCH}"; then
    return 0
  fi
  if [[ "${TARGET_ARCH}" == "universal2" ]]; then
    TARGET_ARCH="$(get_native_arch)"
    warn_echo "当前 Python 环境不支持 universal2，已自动回退为 ${TARGET_ARCH}。"
    build_macos_app_with_arch "${TARGET_ARCH}" || exit 1
    return 0
  fi
  exit 1
}
# 使用 hdiutil 把 .app 封装成 DMG。
create_macos_dmg() {
  local app_path="${PROJECT_DIR}/dist/${APP_NAME}.app"
  local staging_dir="${PROJECT_DIR}/dist/dmg-staging"
  local dmg_path="${DMG_OUTPUT_DIR}/${APP_NAME}-macOS-${TARGET_ARCH}.dmg"
  if [[ ! -d "${app_path}" ]]; then
    error_echo "未找到 .app：${app_path}"
    exit 1
  fi
  mkdir -p "${DMG_OUTPUT_DIR}"
  rm -rf "${staging_dir}"
  mkdir -p "${staging_dir}"
  cp -R "${app_path}" "${staging_dir}/"
  ln -s /Applications "${staging_dir}/Applications"
  rm -f "${dmg_path}"
  hdiutil create -volname "${APP_NAME}" -srcfolder "${staging_dir}" -ov -format UDZO "${dmg_path}" 2>&1 | tee -a "$LOG_FILE" || exit 1
  success_echo "DMG 已生成：${dmg_path}"
}
# 在 Finder 中定位生成的 DMG。
reveal_dmg_in_finder() {
  local dmg_path="${DMG_OUTPUT_DIR}/${APP_NAME}-macOS-${TARGET_ARCH}.dmg"
  if [[ -f "${dmg_path}" ]]; then
    open -R "${dmg_path}" >/dev/null 2>&1 || true
  fi
}
# 执行日常一键启动流程。
run_app_flow() {
  check_environment
  prepare_virtualenv
  install_missing_dependencies
  check_python_entry
  launch_app
}
# 执行内部 macOS DMG 打包流程。
run_macos_dmg_flow() {
  check_environment
  check_macos_build_environment
  select_macos_build_python
  prepare_virtualenv
  install_missing_build_dependencies
  check_python_entry
  build_macos_app
  create_macos_dmg
  reveal_dmg_in_finder
}
# 根据入口参数选择日常启动或内部打包流程。
run_requested_mode() {
  case "${1:-build-dmg}" in
    run-app) run_app_flow ;;
    build-dmg) run_macos_dmg_flow ;;
    *) run_macos_dmg_flow ;;
  esac
}
# 编排一键启动流程。
main() {
  show_script_intro "$@" # 打印内置自述后直接继续，满足双击一键生成 DMG。
  run_requested_mode "$@" # 默认生成 DMG，内部保留 run-app 调试入口。
}

main "$@"

#!/bin/zsh
# 脚本自述：
# - 脚本名称：【MacOS】📦生成dmg.command
# - 核心用途：从外层目录一键生成 LANFileServer.dmg，不需要手动 cd 或输入多条命令。
# - 影响范围：会转交给 LANFileServer 目录内的启动器，由它准备双架构打包环境、安装依赖并生成 DMG。
# - 运行提示：双击后直接进入 DMG 打包流程；项目内启动器会记录完整日志。

setopt NO_NOMATCH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename -- "$0")"
SCRIPT_BASENAME=$(basename "$0" | sed 's/\.[^.]*$//')
LOG_FILE="/tmp/${SCRIPT_BASENAME}-desktop.log"
: > "$LOG_FILE"

PROJECT_LAUNCHER=""

log()            { echo -e "$1" | tee -a "$LOG_FILE"; }
success_echo()   { log "\033[1;32m✔ $1\033[0m"; }
warn_echo()      { log "\033[1;33m⚠ $1\033[0m"; }
note_echo()      { log "\033[1;35m➤ $1\033[0m"; }
error_echo()     { log "\033[1;31m✖ $1\033[0m"; }
highlight_echo() { log "\033[1;36m🔹 $1\033[0m"; }
gray_echo()      { log "\033[0;90m$1\033[0m"; }

# 打印桌面入口自述，不再额外要求用户输入。
show_script_intro() {
  if [[ -t 1 && -n "${TERM:-}" && "${TERM:-}" != "dumb" ]]; then
    clear
  fi
  highlight_echo "============================== 脚本自述 =============================="
  note_echo "当前脚本：${SCRIPT_PATH}"
  note_echo "核心用途：双击脚本，一键生成 LANFileServer.dmg。"
  warn_echo "影响范围：会自动寻找 LANFileServer 项目目录，由项目启动器准备双架构环境、打包 .app 并生成 DMG。"
  gray_echo "日志位置：${LOG_FILE}"
  highlight_echo "======================================================================="
  echo ""
}
# 自动寻找项目内启动器，兼容外层脚本被移动到子目录的情况。
resolve_project_launcher() {
  local candidates=(
    "${SCRIPT_DIR}/LANFileServer/启动LANFileServer.command"
    "${SCRIPT_DIR}/../LANFileServer/启动LANFileServer.command"
    "/Users/jobs/Desktop/LANFileServer/启动LANFileServer.command"
  )
  local candidate=""
  for candidate in "${candidates[@]}"; do
    if [[ -f "${candidate}" ]]; then
      PROJECT_LAUNCHER="$(cd "$(dirname "${candidate}")" && pwd)/$(basename "${candidate}")"
      return 0
    fi
  done
  return 1
}
# 检查项目内启动器是否存在并可执行。
check_environment() {
  if ! resolve_project_launcher; then
    error_echo "未找到项目启动器。请确认启动脚本旁边存在 LANFileServer 文件夹。"
    exit 1
  fi
  if [[ ! -x "${PROJECT_LAUNCHER}" ]]; then
    error_echo "项目启动器没有执行权限，请先执行：chmod +x '${PROJECT_LAUNCHER}'"
    exit 1
  fi
}
# 转交给项目内启动器执行真实启动流程。
run_project_launcher() {
  success_echo "已确认，开始生成 LANFileServer.dmg。"
  LAN_FILE_SERVER_CONFIRMED=1 LAN_FILE_SERVER_OUTPUT_DIR="${SCRIPT_DIR}" "${PROJECT_LAUNCHER}" build-dmg "$@"
}
# 编排桌面一键启动流程。
main() {
  show_script_intro # 打印外层入口自述，保持双击后直接生成 DMG。
  check_environment # 自动定位项目内启动器，并确认它有执行权限。
  run_project_launcher "$@" # 转交给项目内启动器准备环境并生成 DMG。
}

main "$@"

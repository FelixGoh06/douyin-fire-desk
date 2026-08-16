#!/usr/bin/env bash
# Interactive entry point for Douyin Fire Desk administration and installation.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/douyin-fire-desk"
ENV_FILE="/etc/douyin-fire-desk.env"
DEFAULT_PORT="8787"

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && tput sgr0 >/dev/null 2>&1; then
  BOLD="$(tput bold 2>/dev/null || true)"
  DIM="$(tput dim 2>/dev/null || true)"
  RESET="$(tput sgr0 2>/dev/null || true)"
  CYAN="$(tput setaf 6 2>/dev/null || true)"
  BLUE="$(tput setaf 4 2>/dev/null || true)"
  GREEN="$(tput setaf 2 2>/dev/null || true)"
  YELLOW="$(tput setaf 3 2>/dev/null || true)"
  RED="$(tput setaf 1 2>/dev/null || true)"
else
  BOLD=""; DIM=""; RESET=""; CYAN=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

say() { printf '\n%s==>%s %s\n' "$CYAN$BOLD" "$RESET" "$*"; }
note() { printf '%s\n' "$*"; }
warn() { printf '%s%s%s\n' "$YELLOW" "$*" "$RESET"; }
error() { printf '%s%s%s\n' "$RED" "$*" "$RESET" >&2; }

draw_header() {
  if [[ -t 1 ]]; then clear 2>/dev/null || true; fi
  printf '%s' "$CYAN$BOLD"
  cat <<'EOF'

   ____  ___  _   _  ____ __   ___   _
  / ___|/ _ \| \ | |/ ___|\ \ / / | | |
 | |  _| | | |  \| | |  _ \ V /| | | |
 | |_| | |_| | |\  | |_| | | | | |_| |
  \____|\___/|_| \_|\____| |_|  \___/

EOF
  printf '%s' "$RESET"
  printf '  %s抖音火花运营台%s  |  脚本控制中心\n' "$BOLD" "$RESET"
  printf '  %s安装、管理后台、OpenClaw、账号密码与诊断统一入口%s\n\n' "$DIM" "$RESET"
}

pause() {
  printf '\n%s按 Enter 返回脚本主菜单...%s' "$DIM" "$RESET"
  read -r _ || true
}

confirm() {
  local prompt="$1" answer
  read -r -p "$prompt [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]]
}

ensure_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      exec sudo -E bash "$0" "$@"
    fi
    error "请使用 root 运行，或先安装 sudo。"
    exit 1
  fi
}

ensure_supported_os() {
  [[ -f /etc/os-release ]] || { error "无法识别 Linux 发行版。"; exit 1; }
  [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1 || {
    error "Web 管理平台需要 systemd。请在服务器主机的 SSH 终端运行，不要在 Docker 容器终端中运行。"
    exit 1
  }
  if command -v apt-get >/dev/null 2>&1 || command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
    return
  fi
  error "暂不支持当前系统的包管理器。已支持 apt、dnf 和 yum 系统。"
  exit 1
}

installed_project_dir() {
  if [[ -f "$APP_DIR/install.sh" ]]; then
    printf '%s\n' "$APP_DIR"
  else
    printf '%s\n' "$PROJECT_DIR"
  fi
}

nginx_config_present() {
  [[ -f "/etc/nginx/sites-available/douyin-fire-desk" || -f "/etc/nginx/conf.d/douyin-fire-desk.conf" ]]
}

project_is_installed() {
  [[ -f "$ENV_FILE" && -x "$APP_DIR/.venv/bin/python" ]] || return 1
  nginx_config_present || return 1
  systemctl is-enabled --quiet douyin-fire-desk.service 2>/dev/null && systemctl is-active --quiet douyin-fire-desk.service 2>/dev/null
}

web_files_present() {
  [[ -f "$ENV_FILE" || -d "$APP_DIR" || -f "/etc/systemd/system/douyin-fire-desk.service" ]] && return 0
  nginx_config_present
}

valid_port() {
  [[ "$1" =~ ^[0-9]{2,5}$ ]] && (( $1 >= 1 && $1 <= 65535 ))
}

install_full() {
  say "一键安装"
  if project_is_installed && openclaw_available && openclaw_configured && openclaw_gateway_healthy && skill_installed && wechat_channel_connected && wechat_recipient_configured; then
    note "Web 管理平台、OpenClaw、Skill、微信和通知接收者均已配置完成，无需重复安装。"
    return
  fi
  note "系统会自动跳过已安装的组件，只补齐缺失或未完成配置的部分。"
  note "首次接入 OpenClaw 时，只需要配置模型、微信扫码和接收号配对。"
  if confirm "现在开始完整安装？"; then
    if ! project_is_installed; then
      bash "$PROJECT_DIR/install.sh" --with-openclaw
    elif ! openclaw_available; then
      note "Web 管理平台已安装，跳过 Web 重装；正在补装 OpenClaw 集成。"
      bash "$PROJECT_DIR/scripts/install-openclaw-runtime.sh"
      bash "$APP_DIR/scripts/setup-openclaw.sh" --wechat --auto
    elif ! openclaw_configured || ! openclaw_gateway_healthy || ! skill_installed || ! wechat_channel_connected || ! wechat_recipient_configured; then
      note "Web 管理平台已安装，正在补齐 OpenClaw、Skill、微信或通知接收者配置。"
      bash "$APP_DIR/scripts/setup-openclaw.sh" --wechat --auto
    fi
  fi
}

install_web_only() {
  local port
  say "仅安装 Web 管理平台"
  if project_is_installed; then
    note "Web 管理平台已安装，已跳过重复安装。"
    bash "$APP_DIR/scripts/show-admin-credentials.sh"
    return
  fi
  read -r -p "公网端口 [$DEFAULT_PORT]: " port
  port="${port:-$DEFAULT_PORT}"
  if ! valid_port "$port"; then
    error "端口必须在 1 到 65535 之间。"
    return
  fi
  note "安装完成后会显示管理员账号、密码和公网访问地址。"
  warn "请在云安全组和防火墙中放行 TCP $port。"
  if confirm "在端口 $port 安装 Web 管理平台？"; then
    bash "$PROJECT_DIR/install.sh" --without-openclaw --port "$port"
  fi
}

openclaw_user() {
  printf '%s\n' "${SUDO_USER:-${USER:-root}}"
}

openclaw_command() {
  local user home candidate
  user="$(openclaw_user)"
  home="$(getent passwd "$user" 2>/dev/null | cut -d: -f6 || true)"
  for candidate in "$(command -v openclaw 2>/dev/null || true)" "$home/.local/share/pnpm/openclaw" "$home/.npm-global/bin/openclaw"; do
    [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

openclaw_available() {
  [[ -n "$(openclaw_command || true)" ]]
}

run_openclaw() {
  local user home command uid runtime
  local -a environment
  user="$(openclaw_user)"
  home="$(getent passwd "$user" 2>/dev/null | cut -d: -f6 || true)"
  command="$(openclaw_command)"
  environment=("HOME=$home" "PATH=$home/.local/share/pnpm:$home/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
  uid="$(id -u "$user")"
  runtime="/run/user/$uid"
  if [[ -S "$runtime/bus" ]]; then
    environment+=("XDG_RUNTIME_DIR=$runtime" "DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime/bus")
  fi
  runuser -u "$user" -- env "${environment[@]}" "$command" "$@"
}

openclaw_configured() {
  local home
  home="$(getent passwd "$(openclaw_user)" 2>/dev/null | cut -d: -f6 || true)"
  [[ -n "$home" && -f "$home/.openclaw/openclaw.json" ]]
}

openclaw_gateway_healthy() {
  local status
  openclaw_available || return 1
  status="$(run_openclaw gateway status 2>&1 || true)"
  printf '%s\n' "$status" | grep -q 'Connectivity probe: ok'
}

skill_installed() {
  local home
  home="$(getent passwd "$(openclaw_user)" 2>/dev/null | cut -d: -f6 || true)"
  [[ -n "$home" && -d "$home/.openclaw/workspace/skills/douyin-fire-admin" ]]
}

wechat_channel_connected() {
  local status
  openclaw_available || return 1
  status="$(run_openclaw channels status --probe 2>&1 || true)"
  printf '%s\n' "$status" | grep -Eq '^[-[:space:]]*openclaw-weixin .*enabled, configured, running'
}

wechat_recipient_configured() {
  [[ -f /etc/douyin-fire-desk-openclaw.env ]] || return 1
  grep -q '^OPENCLAW_CHANNEL=openclaw-weixin$' /etc/douyin-fire-desk-openclaw.env && grep -q '^OPENCLAW_NOTIFY_TARGET=.' /etc/douyin-fire-desk-openclaw.env
}

install_openclaw() {
  say "安装 OpenClaw"
  if openclaw_available && openclaw_configured && openclaw_gateway_healthy; then
    note "OpenClaw、模型配置和 Gateway 均已正常，无需重复安装。"
    return
  fi
  if openclaw_available; then
    note "已检测到 OpenClaw，不会重复下载；只补齐模型配置或 Gateway。"
  else
    note "将从 OpenClaw 官方安装器部署；仅保留模型配置向导需要手动操作。"
  fi
  if confirm "现在安装或配置 OpenClaw？"; then
    bash "$PROJECT_DIR/scripts/install-openclaw-runtime.sh"
    if project_is_installed; then
      say "连接 OpenClaw 与抖音火花运营台"
      bash "$APP_DIR/scripts/setup-openclaw.sh" --auto
    else
      warn "OpenClaw 已就绪。安装 Web 管理平台后再添加抖音火花运营台 Skill。"
    fi
  fi
}

openclaw_plugin_menu() {
  local choice source
  if ! openclaw_available; then
    warn "尚未安装 OpenClaw，请先在主菜单选择 4。"
    pause
    return
  fi
  if ! project_is_installed; then
    warn "请先安装 Web 管理平台，内置 Skill 需要本机 API 和授权令牌。"
    pause
    return
  fi
  source="$APP_DIR"
  while true; do
    draw_header
    printf '%sOpenClaw 插件菜单%s\n\n' "$BOLD" "$RESET"
    printf '  1. 安装或刷新 douyin-fire-admin Skill\n'
    printf '  2. 安装并连接微信插件\n'
    printf '  3. 检查 Gateway 与通道状态\n'
    printf '  0. 返回脚本主菜单\n\n'
    read -r -p '请选择编号: ' choice
    case "$choice" in
      1)
        if skill_installed; then
          note "douyin-fire-admin Skill 已安装，已跳过重复安装。"
        else
          bash "$source/scripts/setup-openclaw.sh" --auto
        fi
        pause
        ;;
      2)
        if wechat_channel_connected && wechat_recipient_configured; then
          note "微信插件、登录状态和通知接收者均已配置完成，已跳过重复连接。"
        elif wechat_channel_connected; then
          note "微信已登录；仅继续等待接收微信号发消息完成配对，不会再次扫码。"
          bash "$source/scripts/setup-openclaw.sh" --wechat --auto
        else
          bash "$source/scripts/setup-openclaw.sh" --wechat --auto
        fi
        pause
        ;;
      3)
        run_openclaw gateway status || true
        run_openclaw channels status --probe || true
        pause
        ;;
      0) return ;;
      *) warn "请输入菜单中的数字。"; pause ;;
    esac
  done
}

credentials() {
  if ! project_is_installed; then
    warn "Web 管理平台尚未安装。"
    return
  fi
  bash "$APP_DIR/scripts/show-admin-credentials.sh"
}

install_dependencies() {
  say "检查并安装必备依赖"
  bash "$PROJECT_DIR/scripts/install-dependencies.sh" --with-runtime
}

uninstall_menu() {
  local choice source
  source="$(installed_project_dir)"
  while true; do
    draw_header
    printf '%s卸载菜单%s\n\n' "$BOLD" "$RESET"
    printf '  1. 仅移除 Web 服务（保留数据和账号密码）\n'
    printf '  2. 删除 Web 平台与全部 Web 数据\n'
    printf '  3. 仅移除本项目的 OpenClaw 集成\n'
    printf '  4. 删除抖音火花运营台全部组件（保留独立 OpenClaw）\n'
    printf '  0. 返回脚本主菜单\n\n'
    read -r -p '请选择编号: ' choice
    case "$choice" in
      1)
        if ! project_is_installed; then
          warn "未检测到正在安装的 Web 服务，无需移除。"
        elif confirm "移除 Web 服务但保留数据？"; then bash "$source/scripts/uninstall.sh"; fi
        pause
        ;;
      2)
        if ! web_files_present; then
          warn "未检测到 Web 平台文件，无需删除。"
        elif confirm "删除 Web 平台、数据库、浏览器 Profile 和账号密码？"; then bash "$source/scripts/uninstall.sh" --purge; fi
        pause
        ;;
      3)
        if [[ ! -f /etc/douyin-fire-desk-openclaw.env ]] && ! skill_installed; then
          warn "未检测到本项目的 OpenClaw 集成，无需移除。"
        elif confirm "移除内置 Skill、通知服务和通知目标？"; then bash "$source/scripts/uninstall-openclaw.sh"; fi
        pause
        ;;
      4)
        if ! web_files_present && [[ ! -f /etc/douyin-fire-desk-openclaw.env ]] && ! skill_installed; then
          warn "未检测到抖音火花运营台组件，无需删除。"
        elif confirm "删除抖音火花运营台的全部数据和 OpenClaw 集成？"; then
          bash "$source/scripts/uninstall-openclaw.sh"
          bash "$source/scripts/uninstall.sh" --purge
        fi
        pause
        ;;
      0) return ;;
      *) warn "请输入菜单中的数字。"; pause ;;
    esac
  done
}

doctor() {
  local source
  source="$(installed_project_dir)"
  if [[ -x "$source/scripts/doctor.sh" ]]; then
    bash "$source/scripts/doctor.sh"
  else
    warn "未找到已安装的项目。"
  fi
}

main_menu() {
  local choice
  while true; do
    draw_header
    printf '%s脚本主菜单%s\n\n' "$BOLD" "$RESET"
    printf '  %s1.%s 一键安装（Web + OpenClaw + 微信）\n' "$GREEN" "$RESET"
    printf '  %s2.%s 仅安装 Web 管理平台\n' "$GREEN" "$RESET"
    printf '  %s3.%s 卸载程序组件\n' "$GREEN" "$RESET"
    printf '  %s4.%s 安装或配置 OpenClaw\n' "$GREEN" "$RESET"
    printf '  %s5.%s 安装 OpenClaw 插件与 Skill\n' "$GREEN" "$RESET"
    printf '  %s6.%s 查看当前管理员账号和密码\n' "$GREEN" "$RESET"
    printf '  %s7.%s 检查并安装必备依赖\n' "$GREEN" "$RESET"
    printf '  %s8.%s 运行服务诊断\n' "$GREEN" "$RESET"
    printf '  %s0.%s 退出\n\n' "$GREEN" "$RESET"
    read -r -p '请选择编号: ' choice
    case "$choice" in
      1) install_full; pause ;;
      2) install_web_only; pause ;;
      3) uninstall_menu ;;
      4) install_openclaw; pause ;;
      5) openclaw_plugin_menu ;;
      6) credentials; pause ;;
      7) install_dependencies; pause ;;
      8) doctor; pause ;;
      0) note "已退出 GONGYU。"; return ;;
      *) warn "请输入菜单中的数字。"; pause ;;
    esac
  done
}

case "${1:-}" in
  -h|--help)
    printf '用法: gongyu\n打开抖音火花运营台交互式管理菜单。\n'
    exit 0
    ;;
esac

ensure_root "$@"
ensure_supported_os
main_menu

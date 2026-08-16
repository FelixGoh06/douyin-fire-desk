#!/usr/bin/env bash
# Install only missing packages required by Douyin Fire Desk.
set -euo pipefail

WITH_RUNTIME=0
BROWSER_ONLY=0
case "${1:-}" in
  "") ;;
  --with-runtime) WITH_RUNTIME=1 ;;
  --browser-only) BROWSER_ONLY=1 ;;
  -h|--help)
    printf '用法：sudo bash scripts/install-dependencies.sh [--with-runtime|--browser-only]\n'
    exit 0
    ;;
  *) printf '未知选项：%s\n' "$1" >&2; exit 1 ;;
esac
[[ "$EUID" -eq 0 ]] || { printf '请使用 sudo 或 root 运行。\n' >&2; exit 1; }

detect_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    printf 'apt\n'
  elif command -v dnf >/dev/null 2>&1; then
    printf 'dnf\n'
  elif command -v yum >/dev/null 2>&1; then
    printf 'yum\n'
  else
    printf 'unsupported\n'
  fi
}

PACKAGE_MANAGER="$(detect_package_manager)"
[[ "$PACKAGE_MANAGER" != unsupported ]] || {
  printf '暂不支持当前系统的包管理器。已支持 apt、dnf 和 yum 系统。\n' >&2
  exit 1
}

rpm_package_available() {
  "$PACKAGE_MANAGER" -q info "$1" >/dev/null 2>&1
}

python_venv_available() {
  python3 -m venv --help >/dev/null 2>&1 || \
    command -v virtualenv >/dev/null 2>&1 || \
    python3 -m virtualenv --help >/dev/null 2>&1
}

install_base_dependencies() {
  local package
  local -a packages missing
  case "$PACKAGE_MANAGER" in
    apt)
      packages=(ca-certificates curl git nginx openssl python3 python3-pip python3-venv rsync sudo xvfb)
      missing=()
      for package in "${packages[@]}"; do
        dpkg-query -W -f='${db:Status-Status}\n' "$package" 2>/dev/null | grep -qx installed || missing+=("$package")
      done
      if (( ${#missing[@]} )); then
        printf '正在安装缺失的系统依赖：%s\n' "${missing[*]}"
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y "${missing[@]}"
      else
        printf '全部必备系统依赖均已安装。\n'
      fi
      ;;
    dnf|yum)
      packages=(ca-certificates curl git nginx openssl python3 python3-pip rsync sudo xorg-x11-server-Xvfb)
      printf '正在检查 %s 系统依赖。\n' "$PACKAGE_MANAGER"
      "$PACKAGE_MANAGER" install -y "${packages[@]}"
      if ! python_venv_available; then
        if rpm_package_available python3-virtualenv; then
          "$PACKAGE_MANAGER" install -y python3-virtualenv
        fi
        python_venv_available || {
          printf 'Python 缺少虚拟环境组件。请安装系统对应的 python3-venv 或 python3-virtualenv 软件包后重试。\n' >&2
          exit 1
        }
      fi
      ;;
  esac
}

install_available_rpm_packages() {
  local package
  local -a requested=("$@") available=()
  for package in "${requested[@]}"; do
    rpm_package_available "$package" && available+=("$package")
  done
  if (( ${#available[@]} )); then
    "$PACKAGE_MANAGER" install -y "${available[@]}"
  fi
}

install_chromium_runtime() {
  local app_dir="$1"
  local package
  local -a browser_packages available_packages

  case "$PACKAGE_MANAGER" in
    apt)
      # Do not use Playwright's --with-deps here. It assumes an Ubuntu package
      # set and asks Debian 13 for removed ttf-* packages.
      browser_packages=(
        libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcairo2 libcups2
        libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3
        libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6
        libxfixes3 libxkbcommon0 libxrandr2 libxshmfence1 libxss1 libxtst6
        fonts-liberation fonts-noto-color-emoji fonts-unifont fonts-ubuntu
      )
      available_packages=()
      for package in "${browser_packages[@]}"; do
        apt-cache show "$package" >/dev/null 2>&1 && available_packages+=("$package")
      done
      if (( ${#available_packages[@]} )); then
        printf '正在安装 Chromium 所需的系统库。\n'
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y "${available_packages[@]}"
      fi
      ;;
    dnf|yum)
      printf '正在安装 Chromium 所需的系统库。\n'
      install_available_rpm_packages \
        alsa-lib atk at-spi2-atk cairo cups-libs dbus-libs libdrm mesa-libgbm \
        glib2 gtk3 libX11 libxcb libXcomposite libXdamage libXext libXfixes \
        libXrandr libXScrnSaver libXtst libxkbcommon pango nspr nss fontconfig \
        liberation-fonts google-noto-color-emoji-fonts
      ;;
  esac
  printf '正在下载 Chromium 浏览器。\n'
  PLAYWRIGHT_BROWSERS_PATH="$app_dir/.playwright" "$app_dir/.venv/bin/python" -m playwright install chromium
}

install_base_dependencies

app_dir="/opt/douyin-fire-desk"
if [[ "$BROWSER_ONLY" -eq 1 ]]; then
  [[ -x "$app_dir/.venv/bin/python" ]] || { printf '尚未创建 Python 运行时，无法安装 Chromium。\n' >&2; exit 1; }
  install_chromium_runtime "$app_dir"
elif [[ "$WITH_RUNTIME" -eq 1 && -x "$app_dir/.venv/bin/python" ]]; then
  runtime_ok=1
  "$app_dir/.venv/bin/python" -c 'import apscheduler, cryptography, fastapi, httpx, jinja2, multipart, playwright, uvicorn' >/dev/null 2>&1 || runtime_ok=0
  "$app_dir/.venv/bin/pip" check >/dev/null 2>&1 || runtime_ok=0
  compgen -G "$app_dir/.playwright/chromium-*" >/dev/null || runtime_ok=0
  if [[ "$runtime_ok" -eq 1 ]]; then
    printf 'Python 依赖和 Chromium 运行时均已完整，已跳过重复安装。\n'
  else
    printf '检测到 Python 依赖或 Chromium 运行时缺失，正在补齐。\n'
    "$app_dir/.venv/bin/pip" install -r "$app_dir/requirements.txt"
    install_chromium_runtime "$app_dir"
  fi
elif [[ "$WITH_RUNTIME" -eq 1 ]]; then
  printf '系统依赖已就绪。安装 Web 管理平台后会自动创建独立的 Python 与 Chromium 运行时。\n'
fi

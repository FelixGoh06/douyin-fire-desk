#!/usr/bin/env bash
# Install only missing packages required by Douyin Fire Desk.
set -euo pipefail

WITH_RUNTIME=0
case "${1:-}" in
  "") ;;
  --with-runtime) WITH_RUNTIME=1 ;;
  -h|--help)
    printf '用法：sudo bash scripts/install-dependencies.sh [--with-runtime]\n'
    exit 0
    ;;
  *) printf '未知选项：%s\n' "$1" >&2; exit 1 ;;
esac
[[ "$EUID" -eq 0 ]] || { printf '请使用 sudo 或 root 运行。\n' >&2; exit 1; }

# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  debian|ubuntu) ;;
  *) printf '仅支持 Debian 和 Ubuntu。\n' >&2; exit 1 ;;
esac

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

if [[ "$WITH_RUNTIME" -eq 1 && -x /opt/douyin-fire-desk/.venv/bin/python ]]; then
  app_dir="/opt/douyin-fire-desk"
  runtime_ok=1
  "$app_dir/.venv/bin/python" -c 'import apscheduler, cryptography, fastapi, httpx, jinja2, multipart, playwright, uvicorn' >/dev/null 2>&1 || runtime_ok=0
  "$app_dir/.venv/bin/pip" check >/dev/null 2>&1 || runtime_ok=0
  compgen -G "$app_dir/.playwright/chromium-*" >/dev/null || runtime_ok=0
  if [[ "$runtime_ok" -eq 1 ]]; then
    printf 'Python 依赖和 Chromium 运行时均已完整，已跳过重复安装。\n'
  else
    printf '检测到 Python 依赖或 Chromium 运行时缺失，正在补齐。\n'
    "$app_dir/.venv/bin/pip" install -r "$app_dir/requirements.txt"
    PLAYWRIGHT_BROWSERS_PATH="$app_dir/.playwright" "$app_dir/.venv/bin/python" -m playwright install --with-deps chromium
  fi
elif [[ "$WITH_RUNTIME" -eq 1 ]]; then
  printf '系统依赖已就绪。安装 Web 管理平台后会自动创建独立的 Python 与 Chromium 运行时。\n'
fi

#!/usr/bin/env bash
# Install only missing packages required by Douyin Fire Desk.
set -euo pipefail

WITH_RUNTIME=0
case "${1:-}" in
  "") ;;
  --with-runtime) WITH_RUNTIME=1 ;;
  -h|--help)
    printf 'Usage: sudo bash scripts/install-dependencies.sh [--with-runtime]\n'
    exit 0
    ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
esac
[[ "$EUID" -eq 0 ]] || { printf 'Run with sudo or as root.\n' >&2; exit 1; }

# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  debian|ubuntu) ;;
  *) printf 'Only Debian and Ubuntu are supported.\n' >&2; exit 1 ;;
esac

packages=(ca-certificates curl git nginx openssl python3 python3-pip python3-venv rsync sudo xvfb)
missing=()
for package in "${packages[@]}"; do
  dpkg-query -W -f='${db:Status-Status}\n' "$package" 2>/dev/null | grep -qx installed || missing+=("$package")
done

if (( ${#missing[@]} )); then
  printf 'Installing missing system packages: %s\n' "${missing[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y "${missing[@]}"
else
  printf 'All required system packages are already installed.\n'
fi

if [[ "$WITH_RUNTIME" -eq 1 && -x /opt/douyin-fire-desk/.venv/bin/python ]]; then
  printf 'Refreshing installed Python dependencies and Chromium runtime.\n'
  app_dir="/opt/douyin-fire-desk"
  "$app_dir/.venv/bin/pip" install -r "$app_dir/requirements.txt"
  PLAYWRIGHT_BROWSERS_PATH="$app_dir/.playwright" "$app_dir/.venv/bin/python" -m playwright install --with-deps chromium
elif [[ "$WITH_RUNTIME" -eq 1 ]]; then
  printf 'System dependencies are ready. Install the Web platform to create its isolated Python and Chromium runtime.\n'
fi

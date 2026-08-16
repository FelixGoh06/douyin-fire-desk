#!/usr/bin/env bash
# One-command bootstrap for a clean Debian/Ubuntu host.
set -euo pipefail

REPO_NAME="douyin-fire-desk"
GITEE_URL="https://gitee.com/gongyu2006/douyin-fire-desk.git"
GITHUB_URL="https://github.com/FelixGoh06/douyin-fire-desk.git"
SOURCE="auto"

usage() {
  cat <<'EOF'
Usage: bash bootstrap.sh [--gitee|--github]

The default source tries Gitee first, then GitHub, then opens the GONGYU menu.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gitee) SOURCE="gitee"; shift ;;
    --github) SOURCE="github"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 1 ;;
  esac
done

[[ -f /etc/os-release ]] || { printf 'Only Debian/Ubuntu hosts are supported.\n' >&2; exit 1; }
. /etc/os-release
case "${ID:-}" in debian|ubuntu) ;; *) printf 'Only Debian/Ubuntu hosts are supported.\n' >&2; exit 1 ;; esac

[[ "$EUID" -eq 0 ]] || { printf 'Run this bootstrap as root: curl ... | sudo bash\n' >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git

target="/root/${REPO_NAME}"
[[ ! -e "$target" ]] || { printf 'Directory already exists: %s\nUpdate it there, then rerun install.sh.\n' "$target" >&2; exit 1; }

clone() {
  local url="$1"
  git clone --depth 1 "$url" "$target"
}

case "$SOURCE" in
  gitee) clone "$GITEE_URL" ;;
  github) clone "$GITHUB_URL" ;;
  auto) clone "$GITEE_URL" || { rm -rf "$target"; clone "$GITHUB_URL"; } ;;
esac

cd "$target"
# `curl ... | sudo bash` gives this bootstrap script a pipe as stdin. Reconnect
# the interactive GONGYU menu to the caller's terminal before opening it.
# Some cloud terminal implementations expose /dev/tty without reporting it as
# readable to `[[ -r ]]`, so test opening it rather than inspecting permissions.
if { true </dev/tty; } 2>/dev/null; then
  exec bash gongyu.sh </dev/tty
fi
printf '\nGONGYU was downloaded, but this terminal does not expose interactive input.\n'
printf 'Open the menu manually with:\n  cd %s && bash gongyu.sh\n' "$target"

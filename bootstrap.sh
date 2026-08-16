#!/usr/bin/env bash
# One-command bootstrap for a clean Debian/Ubuntu host.
set -euo pipefail

REPO_NAME="douyin-fire-desk"
GITEE_URL="https://gitee.com/gongyu2006/douyin-fire-desk.git"
GITHUB_URL="https://github.com/FelixGoh06/douyin-fire-desk.git"
SOURCE="auto"
INSTALL_ARGS=(--with-openclaw)

usage() {
  cat <<'EOF'
Usage: bash bootstrap.sh [--gitee|--github] [--without-openclaw] [--port PORT]

The default source tries Gitee first, then GitHub. OpenClaw + WeChat are enabled
by default; the only interactive steps are model configuration and WeChat pairing.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gitee) SOURCE="gitee"; shift ;;
    --github) SOURCE="github"; shift ;;
    --without-openclaw) INSTALL_ARGS=(--without-openclaw); shift ;;
    --port) INSTALL_ARGS+=(--port "${2:-}"); shift 2 ;;
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
exec bash install.sh "${INSTALL_ARGS[@]}"

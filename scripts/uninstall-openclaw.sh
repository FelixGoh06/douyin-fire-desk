#!/usr/bin/env bash
# Remove only the Douyin Fire Desk integration from an existing OpenClaw setup.
set -euo pipefail

APP_NAME="douyin-fire-desk"
ENV_FILE="/etc/${APP_NAME}-openclaw.env"
SERVICE_NAME="${APP_NAME}-openclaw-notify"
OPENCLAW_USER="${SUDO_USER:-${USER:-root}}"
OPENCLAW_HOME="$(getent passwd "$OPENCLAW_USER" 2>/dev/null | cut -d: -f6 || true)"

[[ "$EUID" -eq 0 ]] || { printf 'Run with sudo or as root.\n' >&2; exit 1; }

systemctl disable --now "${SERVICE_NAME}.timer" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.timer" "$ENV_FILE"
systemctl daemon-reload 2>/dev/null || true

if [[ -n "$OPENCLAW_HOME" && -d "$OPENCLAW_HOME/.openclaw/workspace/skills/douyin-fire-admin" ]]; then
  rm -rf "$OPENCLAW_HOME/.openclaw/workspace/skills/douyin-fire-admin"
fi

printf 'Removed Douyin Fire Desk OpenClaw integration. The OpenClaw runtime, model configuration, and any unrelated plugins were kept.\n'

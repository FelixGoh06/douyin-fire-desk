#!/usr/bin/env bash
# Remove only the Douyin Fire Desk integration from an existing OpenClaw setup.
set -euo pipefail

APP_NAME="douyin-fire-desk"
ENV_FILE="/etc/${APP_NAME}-openclaw.env"
SERVICE_NAME="${APP_NAME}-openclaw-notify"
GATEWAY_SERVICE_NAME="${APP_NAME}-openclaw-gateway"
OPENCLAW_USER="${SUDO_USER:-${USER:-root}}"
OPENCLAW_HOME="$(getent passwd "$OPENCLAW_USER" 2>/dev/null | cut -d: -f6 || true)"

[[ "$EUID" -eq 0 ]] || { printf '请使用 sudo 或 root 运行。\n' >&2; exit 1; }

systemctl disable --now "${SERVICE_NAME}.timer" 2>/dev/null || true
systemctl disable --now "${GATEWAY_SERVICE_NAME}.service" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.timer" "/etc/systemd/system/${GATEWAY_SERVICE_NAME}.service" "$ENV_FILE"
systemctl daemon-reload 2>/dev/null || true

if [[ -n "$OPENCLAW_HOME" && -d "$OPENCLAW_HOME/.openclaw/workspace/skills/douyin-fire-admin" ]]; then
  rm -rf "$OPENCLAW_HOME/.openclaw/workspace/skills/douyin-fire-admin"
fi

printf '已移除抖音火花运营台的 OpenClaw 集成。OpenClaw 本体、模型配置和无关插件均已保留。\n'

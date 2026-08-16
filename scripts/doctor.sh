#!/usr/bin/env bash
set -euo pipefail

APP_NAME="douyin-fire-desk"
APP_DIR="/opt/${APP_NAME}"
RUNTIME_DIR="/var/lib/${APP_NAME}/openclaw-runtime"
has_systemd=0
[[ -d /run/systemd/system ]] && systemctl show-environment >/dev/null 2>&1 && has_systemd=1
printf '== Douyin Fire Desk doctor ==\n'
if [[ "$has_systemd" -eq 1 ]]; then
  printf '\n[Application service]\n'
  systemctl --no-pager --full status "${APP_NAME}.service" || true
  printf '\n[Nginx]\n'
  nginx -t || true
  systemctl --no-pager --full status nginx || true
else
  printf '\n[Runtime]\n'
  printf 'No systemd detected. This is likely a container; check its process supervisor and Docker port mapping.\n'
fi
printf '\n[Local web response]\n'
curl --max-time 10 -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:7788/login || true
printf '\n[OpenClaw notifier]\n'
if [[ "$has_systemd" -eq 1 ]]; then
  systemctl --no-pager --full status douyin-fire-openclaw-notify.timer || true
  printf '\n[Recent application logs]\n'
  journalctl -u "${APP_NAME}.service" -n 30 --no-pager || true
else
  openclaw gateway status 2>/dev/null || true
  tail -n 30 "$RUNTIME_DIR/gateway.log" 2>/dev/null || true
  tail -n 30 "$RUNTIME_DIR/notifier.log" 2>/dev/null || true
fi
printf '\nPaths: %s (code), /var/lib/%s (data), /etc/%s.env (secrets)\n' "$APP_DIR" "$APP_NAME" "$APP_NAME"

#!/usr/bin/env bash
set -euo pipefail

APP_NAME="douyin-fire-desk"
APP_DIR="/opt/${APP_NAME}"
printf '== Douyin Fire Desk doctor ==\n'
printf '\n[Application service]\n'
systemctl --no-pager --full status "${APP_NAME}.service" || true
printf '\n[Nginx]\n'
nginx -t || true
systemctl --no-pager --full status nginx || true
printf '\n[Local web response]\n'
curl --max-time 10 -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:7788/login || true
printf '\n[OpenClaw notifier]\n'
systemctl --no-pager --full status douyin-fire-openclaw-notify.timer || true
printf '\n[Recent application logs]\n'
journalctl -u "${APP_NAME}.service" -n 30 --no-pager || true
printf '\nPaths: %s (code), /var/lib/%s (data), /etc/%s.env (secrets)\n' "$APP_DIR" "$APP_NAME" "$APP_NAME"

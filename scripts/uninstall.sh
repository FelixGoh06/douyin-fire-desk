#!/usr/bin/env bash
set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1
[[ "$EUID" -eq 0 ]] || { printf 'Run with sudo.\n' >&2; exit 1; }

systemctl disable --now douyin-fire-openclaw-notify.timer 2>/dev/null || true
systemctl disable --now douyin-fire-desk.service 2>/dev/null || true
rm -f /etc/systemd/system/douyin-fire-openclaw-notify.service /etc/systemd/system/douyin-fire-openclaw-notify.timer
rm -f /etc/systemd/system/douyin-fire-desk.service /etc/nginx/sites-enabled/douyin-fire-desk /etc/nginx/sites-available/douyin-fire-desk
systemctl daemon-reload
systemctl reload nginx 2>/dev/null || true
if [[ "$PURGE" -eq 1 ]]; then
  rm -rf /opt/douyin-fire-desk /var/lib/douyin-fire-desk /var/lib/douyin-fire-profiles
  rm -f /etc/douyin-fire-desk.env /etc/douyin-fire-desk-openclaw.env
  printf 'Application, profiles, database, and configuration removed.\n'
else
  printf 'Service removed. Data and secrets were kept. Use --purge to delete them too.\n'
fi

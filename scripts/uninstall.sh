#!/usr/bin/env bash
set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1
[[ "$EUID" -eq 0 ]] || { printf '请使用 sudo 或 root 运行。\n' >&2; exit 1; }

systemctl disable --now douyin-fire-openclaw-notify.timer 2>/dev/null || true
systemctl disable --now douyin-fire-desk.service 2>/dev/null || true
if [[ -f /var/lib/douyin-fire-desk/openclaw-runtime/notifier.pid ]]; then
  kill "$(cat /var/lib/douyin-fire-desk/openclaw-runtime/notifier.pid)" 2>/dev/null || true
fi
if [[ -f /var/lib/douyin-fire-desk/openclaw-runtime/gateway.pid ]]; then
  kill "$(cat /var/lib/douyin-fire-desk/openclaw-runtime/gateway.pid)" 2>/dev/null || true
fi
rm -f /etc/systemd/system/douyin-fire-openclaw-notify.service /etc/systemd/system/douyin-fire-openclaw-notify.timer
rm -f /etc/systemd/system/douyin-fire-desk.service /etc/nginx/sites-enabled/douyin-fire-desk /etc/nginx/sites-available/douyin-fire-desk
systemctl daemon-reload
systemctl reload nginx 2>/dev/null || true
if [[ "$PURGE" -eq 1 ]]; then
  rm -rf /opt/douyin-fire-desk /var/lib/douyin-fire-desk /var/lib/douyin-fire-profiles
  rm -f /etc/douyin-fire-desk.env /etc/douyin-fire-desk-agent.env /etc/douyin-fire-desk-openclaw.env
  rm -f /etc/sudoers.d/douyin-fire-desk-password /usr/local/bin/gongyu
  rm -rf /usr/local/lib/douyin-fire-desk
  printf '应用文件、浏览器 Profile、数据库和配置已删除。\n'
else
  printf '服务已移除，数据和密钥已保留。使用 --purge 可一并删除。\n'
fi

#!/usr/bin/env bash
set -euo pipefail

APP_NAME="douyin-fire-desk"
APP_DIR="/opt/${APP_NAME}"
RUNTIME_DIR="/var/lib/${APP_NAME}/openclaw-runtime"
has_systemd=0
[[ -d /run/systemd/system ]] && systemctl show-environment >/dev/null 2>&1 && has_systemd=1
printf '== 抖音火花运营台诊断 ==\n'
if [[ "$has_systemd" -eq 1 ]]; then
  printf '\n[应用服务]\n'
  systemctl --no-pager --full status "${APP_NAME}.service" || true
  printf '\n[Nginx 服务]\n'
  nginx -t || true
  systemctl --no-pager --full status nginx || true
else
  printf '\n[运行环境]\n'
  printf '未检测到 systemd。当前可能是容器环境，请检查进程守护和 Docker 端口映射。\n'
fi
printf '\n[本机 Web 响应]\n'
curl --max-time 10 -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:7788/login || true
printf '\n[OpenClaw 通知进程]\n'
if [[ "$has_systemd" -eq 1 ]]; then
  systemctl --no-pager --full status douyin-fire-openclaw-notify.timer || true
  printf '\n[最近应用日志]\n'
  journalctl -u "${APP_NAME}.service" -n 30 --no-pager || true
else
  openclaw gateway status 2>/dev/null || true
  tail -n 30 "$RUNTIME_DIR/gateway.log" 2>/dev/null || true
  tail -n 30 "$RUNTIME_DIR/notifier.log" 2>/dev/null || true
fi
printf '\n路径：%s（代码），/var/lib/%s（数据），/etc/%s.env（密钥）\n' "$APP_DIR" "$APP_NAME" "$APP_NAME"

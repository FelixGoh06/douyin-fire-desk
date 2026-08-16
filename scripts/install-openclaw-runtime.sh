#!/usr/bin/env bash
# Install and start OpenClaw while leaving model configuration to its own wizard.
set -euo pipefail

OPENCLAW_USER="${SUDO_USER:-${USER:-root}}"
GATEWAY_SERVICE_NAME="douyin-fire-openclaw-gateway"
case "${1:-}" in
  "") ;;
  -h|--help)
    printf '用法：sudo bash scripts/install-openclaw-runtime.sh\n'
    exit 0
    ;;
  *) printf '未知选项：%s\n' "$1" >&2; exit 1 ;;
esac
[[ "$EUID" -eq 0 ]] || { printf '请使用 sudo 或 root 运行。\n' >&2; exit 1; }
if ! command -v curl >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl
fi
id "$OPENCLAW_USER" >/dev/null 2>&1 || { printf 'OpenClaw 用户不存在：%s\n' "$OPENCLAW_USER" >&2; exit 1; }
OPENCLAW_HOME="$(getent passwd "$OPENCLAW_USER" | cut -d: -f6)"
[[ -d "$OPENCLAW_HOME" ]] || { printf '无法找到用户 %s 的主目录。\n' "$OPENCLAW_USER" >&2; exit 1; }

run_as_openclaw() {
  local uid runtime
  local -a environment
  uid="$(id -u "$OPENCLAW_USER")"
  runtime="/run/user/$uid"
  environment=("HOME=$OPENCLAW_HOME" "PATH=$OPENCLAW_HOME/.local/share/pnpm:$OPENCLAW_HOME/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
  if [[ -S "$runtime/bus" ]]; then
    environment+=("XDG_RUNTIME_DIR=$runtime" "DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime/bus")
  fi
  runuser -u "$OPENCLAW_USER" -- env "${environment[@]}" "$@"
}

systemd_available() {
  [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1
}

find_openclaw() {
  local candidate
  for candidate in "$(command -v openclaw 2>/dev/null || true)" "$OPENCLAW_HOME/.local/share/pnpm/openclaw" "$OPENCLAW_HOME/.npm-global/bin/openclaw"; do
    [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

OPENCLAW_COMMAND="$(find_openclaw || true)"
if [[ -z "$OPENCLAW_COMMAND" ]]; then
  printf '\n==> 正在通过 OpenClaw 官方安装器安装\n'
  run_as_openclaw bash -lc 'curl --proto "=https" --tlsv1.2 -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard --no-prompt'
  OPENCLAW_COMMAND="$(find_openclaw || true)"
  [[ -n "$OPENCLAW_COMMAND" ]] || { printf '安装后未找到 OpenClaw 命令。\n' >&2; exit 1; }
else
  printf '已检测到 OpenClaw，已跳过重复下载安装。\n'
fi

if [[ ! -f "$OPENCLAW_HOME/.openclaw/openclaw.json" ]]; then
  printf '\n==> 请配置模型服务商\n'
  printf '只有模型配置向导需要手动输入。\n'
  onboarding=(onboard --accept-risk --flow quickstart --skip-channels --skip-ui --skip-hooks --skip-search --skip-skills)
  onboarding+=(--skip-daemon --skip-health)
  run_as_openclaw env OPENCLAW_LOCALE=zh-CN "$OPENCLAW_COMMAND" "${onboarding[@]}"
else
  printf '模型配置已存在，已跳过重复配置。\n'
fi

if systemd_available; then
  systemctl stop "${GATEWAY_SERVICE_NAME}.service" 2>/dev/null || true
  run_as_openclaw systemctl --user disable --now openclaw-gateway.service >/dev/null 2>&1 || true
  pkill -TERM -u "$OPENCLAW_USER" -f '(^|/)openclaw-gateway($| )' 2>/dev/null || true
  sleep 1
  cat > "/etc/systemd/system/${GATEWAY_SERVICE_NAME}.service" <<EOF
[Unit]
Description=Douyin Fire Desk OpenClaw Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${OPENCLAW_USER}
Environment=HOME=${OPENCLAW_HOME}
Environment=PATH=${OPENCLAW_HOME}/.local/share/pnpm:${OPENCLAW_HOME}/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${OPENCLAW_COMMAND} gateway
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now "${GATEWAY_SERVICE_NAME}.service"
else
  run_as_openclaw bash -lc "nohup $(printf '%q' "$OPENCLAW_COMMAND") gateway >/tmp/openclaw-gateway.log 2>&1 &"
fi

for _ in 1 2 3 4 5 6; do
  sleep 5
  status="$(run_as_openclaw "$OPENCLAW_COMMAND" gateway status 2>&1 || true)"
  if printf '%s\n' "$status" | grep -q 'Connectivity probe: ok'; then
    printf '\nOpenClaw Gateway 已正常运行。\n'
    run_as_openclaw "$OPENCLAW_COMMAND" gateway status
    exit 0
  fi
done

printf 'OpenClaw 已安装，但 Gateway 状态异常。请执行：systemctl status %s.service --no-pager\n' "$GATEWAY_SERVICE_NAME" >&2
exit 1

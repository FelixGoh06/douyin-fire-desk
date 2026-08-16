#!/usr/bin/env bash
# Install the bundled Skill, optional WeChat channel, and notification runtime.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="/etc/douyin-fire-desk.env"
AGENT_ENV_FILE="/etc/douyin-fire-desk-agent.env"
AGENT_GROUP="douyin-fire-agent"
OPENCLAW_ENV_FILE="/etc/douyin-fire-desk-openclaw.env"
SERVICE_NAME="douyin-fire-openclaw-notify"
RUNTIME_DIR="/var/lib/douyin-fire-desk/openclaw-runtime"
INSTALL_OPENCLAW=0
NON_INTERACTIVE=0
AUTO_SETUP=0
WITH_WECHAT=0
NOTIFY_TARGET=""
OPENCLAW_USER="${SUDO_USER:-${USER:-root}}"

say() { printf '\n==> %s\n' "$*"; }
note() { printf '%s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: sudo bash scripts/setup-openclaw.sh [options]

Options:
  --install-openclaw  Install OpenClaw from the official installer when absent
  --wechat            Install the Tencent WeChat plugin and open QR login
  --auto              Use the guided model setup, then complete safe local steps automatically
  --notify-target ID  Set an already-known notification recipient id
  --user USER         Linux user that owns OpenClaw (default: invoking user)
  --non-interactive   Do not ask generic channel questions
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-openclaw) INSTALL_OPENCLAW=1; shift ;;
    --wechat) WITH_WECHAT=1; shift ;;
    --auto) AUTO_SETUP=1; shift ;;
    --notify-target) NOTIFY_TARGET="${2:-}"; shift 2 ;;
    --user) OPENCLAW_USER="${2:-}"; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

[[ "$EUID" -eq 0 ]] || fail "Run this script with sudo or as root."
[[ -f "$ENV_FILE" ]] || fail "Install Douyin Fire Desk first: sudo bash install.sh"
[[ -f "$AGENT_ENV_FILE" ]] || fail "Agent configuration is missing. Re-run sudo bash install.sh first."
id "$OPENCLAW_USER" >/dev/null 2>&1 || fail "User does not exist: $OPENCLAW_USER"
OPENCLAW_HOME="$(getent passwd "$OPENCLAW_USER" | cut -d: -f6)"
[[ -n "$OPENCLAW_HOME" && -d "$OPENCLAW_HOME" ]] || fail "Could not locate the home directory for $OPENCLAW_USER"

systemd_available() {
  [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1
}

run_as_openclaw() {
  runuser -u "$OPENCLAW_USER" -- env HOME="$OPENCLAW_HOME" PATH="$OPENCLAW_HOME/.local/share/pnpm:$OPENCLAW_HOME/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "$@"
}

find_openclaw() {
  local candidate
  for candidate in "$(command -v openclaw 2>/dev/null || true)" "$OPENCLAW_HOME/.local/share/pnpm/openclaw" "$OPENCLAW_HOME/.npm-global/bin/openclaw"; do
    [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

gateway_status() {
  run_as_openclaw "$OPENCLAW_COMMAND" gateway status >/dev/null 2>&1
}

wechat_channel_connected() {
  local status
  status="$(run_as_openclaw "$OPENCLAW_COMMAND" channels status --probe 2>&1 || true)"
  printf '%s\n' "$status" | grep -Eq '^[-[:space:]]*openclaw-weixin .*enabled, configured, running'
}

install_gateway_service() {
  if systemd_available; then
    run_as_openclaw "$OPENCLAW_COMMAND" gateway install >/dev/null 2>&1 || true
  fi
}

start_container_gateway() {
  local pid_file="$RUNTIME_DIR/gateway.pid"
  local log_file="$RUNTIME_DIR/gateway.log"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    return 0
  fi
  install -d -o "$OPENCLAW_USER" -g "$OPENCLAW_USER" -m 0750 "$RUNTIME_DIR"
  say "Starting the OpenClaw Gateway without systemd"
  run_as_openclaw bash -lc "nohup $(printf '%q' "$OPENCLAW_COMMAND") gateway > $(printf '%q' "$log_file") 2>&1 & echo \$! > $(printf '%q' "$pid_file")"
  sleep 3
  gateway_status || fail "Gateway did not start. Read $log_file"
}

ensure_gateway() {
  gateway_status && return 0
  if systemd_available; then
    say "Starting the managed OpenClaw Gateway"
    install_gateway_service
    run_as_openclaw "$OPENCLAW_COMMAND" gateway start >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6; do
      sleep 5
      gateway_status && return 0
    done
    fail "Gateway is unavailable. Run: sudo -u $OPENCLAW_USER HOME=$OPENCLAW_HOME $OPENCLAW_COMMAND gateway status"
  else
    start_container_gateway
  fi
}

restart_gateway_after_channel_login() {
  if systemd_available; then
    say "Reloading the Gateway after WeChat login"
    run_as_openclaw "$OPENCLAW_COMMAND" gateway restart >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6; do
      sleep 5
      gateway_status && return 0
    done
    fail "Gateway did not recover after WeChat login. Run: sudo -u $OPENCLAW_USER HOME=$OPENCLAW_HOME $OPENCLAW_COMMAND gateway status"
  else
    start_container_gateway
  fi
}

start_container_notifier() {
  local pid_file="$RUNTIME_DIR/notifier.pid"
  local log_file="$RUNTIME_DIR/notifier.log"
  local loop_script="$SKILL_DIR/scripts/notify-openclaw-loop.sh"
  [[ -n "$channel" && -n "$target" ]] || { note "Notifications are waiting for a verified recipient."; return 0; }
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    return 0
  fi
  install -d -o "$OPENCLAW_USER" -g "$OPENCLAW_USER" -m 0750 "$RUNTIME_DIR"
  run_as_openclaw bash -lc "nohup $(printf '%q' "$loop_script") > $(printf '%q' "$log_file") 2>&1 & echo \$! > $(printf '%q' "$pid_file")"
  note "Container notifier started; log: $log_file"
}

install_notification_runtime() {
  if systemd_available; then
    sed \
      -e "s|__OPENCLAW_USER__|$OPENCLAW_USER|g" \
      -e "s|__OPENCLAW_HOME__|$OPENCLAW_HOME|g" \
      -e "s|__SKILL_DIR__|$SKILL_DIR|g" \
      "$SKILL_DIR/scripts/douyin-fire-openclaw-notify.service.template" > "/etc/systemd/system/${SERVICE_NAME}.service"
    install -m 0644 "$SKILL_DIR/scripts/douyin-fire-openclaw-notify.timer" "/etc/systemd/system/${SERVICE_NAME}.timer"
    systemctl daemon-reload
    systemctl enable --now "${SERVICE_NAME}.timer"
  else
    start_container_notifier
  fi
}

discover_wechat_recipient() {
  local pairing_output candidate code
  pairing_output="$(run_as_openclaw "$OPENCLAW_COMMAND" pairing list openclaw-weixin 2>&1 || true)"
  candidate="$(printf '%s\n' "$pairing_output" | grep -Eo '[[:alnum:]_.-]+@im\.wechat' | head -n 1 || true)"
  code="$(printf '%s\n' "$pairing_output" | grep -Eo '[A-Z2-9]{8}' | head -n 1 || true)"
  [[ -n "$candidate" ]] || return 1
  if [[ -n "$code" ]]; then
    run_as_openclaw "$OPENCLAW_COMMAND" pairing approve openclaw-weixin "$code" --notify >/dev/null 2>&1 || true
  fi
  NOTIFY_TARGET="$candidate"
  return 0
}

wait_for_wechat_recipient() {
  local attempt
  for attempt in $(seq 1 18); do
    if discover_wechat_recipient; then
      return 0
    fi
    sleep 5
  done
  return 1
}

get_env_value() {
  local key="$1" file="$2"
  [[ -f "$file" ]] || return 0
  grep -m1 "^${key}=" "$file" | cut -d= -f2- || true
}

getent group "$AGENT_GROUP" >/dev/null 2>&1 || groupadd --system "$AGENT_GROUP"
usermod -a -G "$AGENT_GROUP" "$OPENCLAW_USER"
chown root:"$AGENT_GROUP" "$AGENT_ENV_FILE"
chmod 0640 "$AGENT_ENV_FILE"

OPENCLAW_COMMAND="$(find_openclaw || true)"
if [[ -z "$OPENCLAW_COMMAND" ]]; then
  [[ "$INSTALL_OPENCLAW" -eq 1 || "$AUTO_SETUP" -eq 1 ]] || fail "OpenClaw is not installed. Re-run with --install-openclaw."
  say "Installing OpenClaw with the official installer"
  # Skip the installer's unrestricted onboarding. The guided `onboard` call below
  # is deliberately limited to model configuration; this script owns channel setup.
  run_as_openclaw bash -lc 'curl --proto "=https" --tlsv1.2 -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard --no-prompt'
  OPENCLAW_COMMAND="$(find_openclaw || true)"
  [[ -n "$OPENCLAW_COMMAND" ]] || fail "OpenClaw installation finished but its command was not found. Log in as $OPENCLAW_USER and rerun this script."
fi

if [[ ! -f "$OPENCLAW_HOME/.openclaw/openclaw.json" ]]; then
  [[ "$NON_INTERACTIVE" -eq 0 ]] || fail "Model configuration requires an interactive terminal. Rerun without --non-interactive."
  say "Configure the model provider"
  note "Only the model provider/key screens require your input. Do not paste API keys into chat."
  onboarding=(onboard --accept-risk --flow quickstart --skip-channels --skip-ui --skip-hooks --skip-search --skip-skills)
  if systemd_available; then
    onboarding+=(--install-daemon)
  else
    onboarding+=(--skip-daemon --skip-health)
  fi
  run_as_openclaw env OPENCLAW_LOCALE=zh-CN "$OPENCLAW_COMMAND" "${onboarding[@]}"
fi

SKILL_SOURCE="$APP_DIR/openclaw-skill/douyin-fire-admin"
SKILL_DIR="$OPENCLAW_HOME/.openclaw/workspace/skills/douyin-fire-admin"
[[ -d "$SKILL_SOURCE" ]] || fail "Bundled skill is missing: $SKILL_SOURCE"
say "Installing the douyin-fire-admin Skill"
install -d -o "$OPENCLAW_USER" -g "$OPENCLAW_USER" -m 0755 "$(dirname "$SKILL_DIR")"
rsync -a --delete --exclude '__pycache__/' "$SKILL_SOURCE/" "$SKILL_DIR/"
chown -R "$OPENCLAW_USER:$OPENCLAW_USER" "$SKILL_DIR"
chmod 0755 "$SKILL_DIR/scripts/notify-openclaw-loop.sh"

channel="$(get_env_value OPENCLAW_CHANNEL "$OPENCLAW_ENV_FILE")"
target="${NOTIFY_TARGET:-$(get_env_value OPENCLAW_NOTIFY_TARGET "$OPENCLAW_ENV_FILE")}"
if [[ "$WITH_WECHAT" -eq 1 ]]; then
  say "Installing and connecting WeChat"
  run_as_openclaw npx -y @tencent-weixin/openclaw-weixin-cli install
  run_as_openclaw "$OPENCLAW_COMMAND" config set plugins.entries.openclaw-weixin.enabled true
  ensure_gateway
  if wechat_channel_connected; then
    note "WeChat is already connected; skipping the QR login."
  else
    note "Scan the QR code with the dedicated OpenClaw WeChat account and confirm on the phone."
    run_as_openclaw "$OPENCLAW_COMMAND" channels login --channel openclaw-weixin
    restart_gateway_after_channel_login
  fi
  channel="openclaw-weixin"
  if [[ -z "$target" && "$NON_INTERACTIVE" -eq 0 ]]; then
    note "From the receiving WeChat account, send any message to the account just connected."
    read -r -p "After sending the message, press Enter to bind that receiver automatically: " _
    note "Waiting up to 90 seconds for the receiver pairing request."
    if wait_for_wechat_recipient; then
      note "WeChat receiver bound automatically."
    else
      note "Receiver was not found yet. The Skill works, but automatic reports will stay off until you rerun this script after the receiver sends a pairing message."
    fi
  fi
elif [[ "$NON_INTERACTIVE" -eq 0 && "$AUTO_SETUP" -eq 0 ]]; then
  read -r -p "OpenClaw notification channel${channel:+ [$channel]} (leave blank to configure later): " entered_channel
  read -r -p "Notification recipient / target${target:+ [$target]} (leave blank to configure later): " entered_target
  channel="${entered_channel:-$channel}"
  target="${entered_target:-$target}"
fi

if [[ "$channel" == *$'\n'* || "$target" == *$'\n'* ]]; then
  fail "Channel and target cannot contain a newline."
fi
umask 077
printf 'DOUYIN_FIRE_ENV_FILE=%s\nOPENCLAW_COMMAND=%s\nOPENCLAW_CHANNEL=%s\nOPENCLAW_NOTIFY_TARGET=%s\n' \
  "$AGENT_ENV_FILE" "$OPENCLAW_COMMAND" "$channel" "$target" > "$OPENCLAW_ENV_FILE"
chmod 0600 "$OPENCLAW_ENV_FILE"

ensure_gateway
install_notification_runtime

say "OpenClaw integration is ready"
note "Skill: douyin-fire-admin"
note "Verify: sudo -u $OPENCLAW_USER HOME=$OPENCLAW_HOME $OPENCLAW_COMMAND skills info douyin-fire-admin"
if [[ -n "$channel" && -n "$target" ]]; then
  note "Reports: enabled through $channel"
else
  note "Reports: waiting for a recipient. For WeChat, rerun this script with --wechat after the receiver sends a pairing message."
fi
if ! systemd_available; then
  note "Container notice: Gateway and notifier are running with nohup. Configure your container to restart automatically, then rerun this script after a container rebuild."
fi

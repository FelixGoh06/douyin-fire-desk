#!/usr/bin/env bash
# Install the bundled skill and optional notification timer for an OpenClaw user.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="/etc/douyin-fire-desk.env"
AGENT_ENV_FILE="/etc/douyin-fire-desk-agent.env"
AGENT_GROUP="douyin-fire-agent"
OPENCLAW_ENV_FILE="/etc/douyin-fire-desk-openclaw.env"
SERVICE_NAME="douyin-fire-openclaw-notify"
INSTALL_OPENCLAW=0
NON_INTERACTIVE=0
OPENCLAW_USER="${SUDO_USER:-${USER:-root}}"

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-openclaw) INSTALL_OPENCLAW=1; shift ;;
    --user) OPENCLAW_USER="${2:-}"; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    -h|--help)
      printf 'Usage: sudo bash scripts/setup-openclaw.sh [--install-openclaw] [--user USER] [--non-interactive]\n'
      exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

[[ "$EUID" -eq 0 ]] || fail "Run this script with sudo or as root."
[[ -f "$ENV_FILE" ]] || fail "Install Douyin Fire Desk first: sudo bash install.sh"
[[ -f "$AGENT_ENV_FILE" ]] || fail "Agent configuration is missing. Re-run sudo bash install.sh first."
id "$OPENCLAW_USER" >/dev/null 2>&1 || fail "User does not exist: $OPENCLAW_USER"
OPENCLAW_HOME="$(getent passwd "$OPENCLAW_USER" | cut -d: -f6)"
[[ -n "$OPENCLAW_HOME" && -d "$OPENCLAW_HOME" ]] || fail "Could not locate the home directory for $OPENCLAW_USER"
getent group "$AGENT_GROUP" >/dev/null 2>&1 || groupadd --system "$AGENT_GROUP"
usermod -a -G "$AGENT_GROUP" "$OPENCLAW_USER"
chown root:"$AGENT_GROUP" "$AGENT_ENV_FILE"
chmod 0640 "$AGENT_ENV_FILE"

find_openclaw() {
  local candidate
  for candidate in "$(command -v openclaw 2>/dev/null || true)" "$OPENCLAW_HOME/.local/share/pnpm/openclaw" "$OPENCLAW_HOME/.npm-global/bin/openclaw"; do
    [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

OPENCLAW_COMMAND="$(find_openclaw || true)"
if [[ -z "$OPENCLAW_COMMAND" ]]; then
  if [[ "$INSTALL_OPENCLAW" -eq 0 && "$NON_INTERACTIVE" -eq 0 ]]; then
    read -r -p "OpenClaw is not installed. Install it from openclaw.ai now? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] && INSTALL_OPENCLAW=1
  fi
  [[ "$INSTALL_OPENCLAW" -eq 1 ]] || fail "OpenClaw is not installed. Re-run with --install-openclaw, or see https://docs.openclaw.ai/install"
  say "Installing OpenClaw with the official installer"
  runuser -u "$OPENCLAW_USER" -- env HOME="$OPENCLAW_HOME" bash -lc 'curl -fsSL https://openclaw.ai/install.sh | bash'
  OPENCLAW_COMMAND="$(find_openclaw || true)"
  [[ -n "$OPENCLAW_COMMAND" ]] || fail "OpenClaw installation finished but its command was not found. Log in as $OPENCLAW_USER, then rerun this script."
  say "Finish official OpenClaw onboarding in this terminal"
  runuser -u "$OPENCLAW_USER" -- env HOME="$OPENCLAW_HOME" "$OPENCLAW_COMMAND" onboard --install-daemon
fi

SKILL_SOURCE="$APP_DIR/openclaw-skill/douyin-fire-admin"
SKILL_DIR="$OPENCLAW_HOME/.openclaw/workspace/skills/douyin-fire-admin"
[[ -d "$SKILL_SOURCE" ]] || fail "Bundled skill is missing: $SKILL_SOURCE"
say "Installing the douyin-fire-admin skill for $OPENCLAW_USER"
install -d -o "$OPENCLAW_USER" -g "$OPENCLAW_USER" -m 0755 "$(dirname "$SKILL_DIR")"
rsync -a --delete --exclude '__pycache__/' "$SKILL_SOURCE/" "$SKILL_DIR/"
chown -R "$OPENCLAW_USER:$OPENCLAW_USER" "$SKILL_DIR"

channel=""
target=""
if [[ -f "$OPENCLAW_ENV_FILE" ]]; then
  channel="$(grep -m1 '^OPENCLAW_CHANNEL=' "$OPENCLAW_ENV_FILE" | cut -d= -f2- || true)"
  target="$(grep -m1 '^OPENCLAW_NOTIFY_TARGET=' "$OPENCLAW_ENV_FILE" | cut -d= -f2- || true)"
fi
if [[ "$NON_INTERACTIVE" -eq 0 ]]; then
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

sed \
  -e "s|__OPENCLAW_USER__|$OPENCLAW_USER|g" \
  -e "s|__OPENCLAW_HOME__|$OPENCLAW_HOME|g" \
  -e "s|__SKILL_DIR__|$SKILL_DIR|g" \
  "$SKILL_DIR/scripts/douyin-fire-openclaw-notify.service.template" > "/etc/systemd/system/${SERVICE_NAME}.service"
install -m 0644 "$SKILL_DIR/scripts/douyin-fire-openclaw-notify.timer" "/etc/systemd/system/${SERVICE_NAME}.timer"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.timer"

say "OpenClaw integration is installed"
printf 'Skill: douyin-fire-admin\n'
printf 'The OpenClaw user was added to %s. Restart its gateway/session once so the new group takes effect.\n' "$AGENT_GROUP"
printf 'Verification: sudo -u %s HOME=%s %s skills info douyin-fire-admin\n' "$OPENCLAW_USER" "$OPENCLAW_HOME" "$OPENCLAW_COMMAND"
if [[ -z "$channel" || -z "$target" ]]; then
  printf 'Notifications are waiting for a channel and recipient. Rerun: sudo bash %s/scripts/setup-openclaw.sh --user %s\n' "$APP_DIR" "$OPENCLAW_USER"
else
  printf 'Notifications are enabled through channel %s.\n' "$channel"
fi

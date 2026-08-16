#!/usr/bin/env bash
# Douyin Fire Desk v1.0 installer for Debian/Ubuntu.
set -euo pipefail

APP_NAME="douyin-fire-desk"
APP_DIR="/opt/${APP_NAME}"
DATA_DIR="/var/lib/${APP_NAME}"
PROFILE_DIR="/var/lib/douyin-fire-profiles"
SERVICE_USER="douyin-fire"
ENV_FILE="/etc/${APP_NAME}.env"
AGENT_ENV_FILE="/etc/${APP_NAME}-agent.env"
AGENT_GROUP="douyin-fire-agent"
PORT="8787"
OPENCLAW_MODE="ask"
INSTALL_OPENCLAW=0
NON_INTERACTIVE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_ARGS=("$@")

usage() {
  cat <<'EOF'
Usage: sudo bash install.sh [options]

Options:
  --port PORT           Public web port (default: 8787)
  --with-openclaw       Automatically install OpenClaw, WeChat, Skill, and reports
  --without-openclaw    Skip OpenClaw integration
  --install-openclaw    Install OpenClaw through its official installer when absent
  --non-interactive     Do not ask questions; OpenClaw is skipped unless requested
  -h, --help            Show this help
EOF
}

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:-}"; shift 2 ;;
    --with-openclaw) OPENCLAW_MODE="yes"; INSTALL_OPENCLAW=1; shift ;;
    --without-openclaw) OPENCLAW_MODE="no"; shift ;;
    --install-openclaw) OPENCLAW_MODE="yes"; INSTALL_OPENCLAW=1; shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

[[ "$PORT" =~ ^[0-9]{2,5}$ ]] && (( PORT >= 1 && PORT <= 65535 )) || fail "--port must be 1-65535"
[[ -f "${SCRIPT_DIR}/run.py" ]] || fail "Run this script from the cloned project directory."

if [[ "${EUID}" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || fail "Please run as root, or install sudo first."
  exec sudo -E bash "$0" "${ORIGINAL_ARGS[@]}"
fi

source /etc/os-release
case "${ID:-}" in
  debian|ubuntu) ;;
  *) fail "Only Debian and Ubuntu are supported by this installer. See docs/INSTALL.md for manual deployment." ;;
esac

say "Checking required system packages"
bash "$SCRIPT_DIR/scripts/install-dependencies.sh"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
if ! getent group "$AGENT_GROUP" >/dev/null 2>&1; then
  groupadd --system "$AGENT_GROUP"
fi

say "Installing application files"
install -d -m 0755 "$APP_DIR"
if [[ "$(readlink -f "$SCRIPT_DIR")" != "$(readlink -f "$APP_DIR")" ]]; then
  rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude '.playwright/' --exclude '__pycache__/' \
    --exclude '.pytest_cache/' --exclude 'data/' --exclude '*.db' \
    "${SCRIPT_DIR}/" "${APP_DIR}/"
else
  say "Using the installed application files"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR" "$PROFILE_DIR"

say "Installing Python dependencies and Chromium"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.playwright" "$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium

if [[ ! -f "$ENV_FILE" ]]; then
  say "Generating first-run secrets"
  admin_password="$(openssl rand -base64 24 | tr -d '\n')"
  session_secret="$(openssl rand -hex 32)"
  cookie_key="$("$APP_DIR/.venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  agent_token="$(openssl rand -hex 32)"
  umask 077
  cat > "$ENV_FILE" <<EOF
APP_NAME=Douyin Fire Desk
HOST=127.0.0.1
PORT=7788
BASE_PATH=
APP_TIMEZONE=Asia/Shanghai
DATABASE_PATH=${DATA_DIR}/admin.db
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${admin_password}
SESSION_SECRET=${session_secret}
COOKIE_ENCRYPTION_KEY=${cookie_key}
SESSION_SECURE=0
RUNNER_ENABLED=1
BROWSER_BIN=
BROWSER_HEADLESS=1
PLAYWRIGHT_BROWSERS_PATH=${APP_DIR}/.playwright
USE_XVFB=1
CALLBACK_ONLY_LOOPBACK=1
AGENT_API_TOKEN=${agent_token}
ADMIN_PASSWORD_UPDATE_COMMAND=/usr/local/lib/douyin-fire-desk/update-admin-password
EOF
  chmod 0600 "$ENV_FILE"
  printf 'OPENCLAW_BASE_URL=http://127.0.0.1:7788\nAGENT_API_TOKEN=%s\n' "$agent_token" > "$AGENT_ENV_FILE"
  chown root:"$AGENT_GROUP" "$AGENT_ENV_FILE"
  chmod 0640 "$AGENT_ENV_FILE"
else
  admin_password=""
  say "Keeping existing configuration at ${ENV_FILE}"
fi

install -d -m 0755 /usr/local/lib/douyin-fire-desk
install -m 0700 "$APP_DIR/deploy/update-admin-password.py" /usr/local/lib/douyin-fire-desk/update-admin-password
install -m 0755 "$APP_DIR/deploy/gongyu" /usr/local/bin/gongyu
printf '%s ALL=(root) NOPASSWD: /usr/local/lib/douyin-fire-desk/update-admin-password\n' "$SERVICE_USER" > /etc/sudoers.d/douyin-fire-desk-password
chmod 0440 /etc/sudoers.d/douyin-fire-desk-password
visudo -cf /etc/sudoers.d/douyin-fire-desk-password

if [[ ! -f "$AGENT_ENV_FILE" ]]; then
  agent_token="$(grep -m1 '^AGENT_API_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)"
  [[ -n "$agent_token" ]] || fail "AGENT_API_TOKEN is missing from ${ENV_FILE}"
  printf 'OPENCLAW_BASE_URL=http://127.0.0.1:7788\nAGENT_API_TOKEN=%s\n' "$agent_token" > "$AGENT_ENV_FILE"
  chown root:"$AGENT_GROUP" "$AGENT_ENV_FILE"
  chmod 0640 "$AGENT_ENV_FILE"
fi

if ! grep -q '^ADMIN_PASSWORD_UPDATE_COMMAND=' "$ENV_FILE"; then
  printf 'ADMIN_PASSWORD_UPDATE_COMMAND=/usr/local/lib/douyin-fire-desk/update-admin-password\n' >> "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
fi

install -m 0644 "$APP_DIR/deploy/douyin-fire-desk.service" "/etc/systemd/system/${APP_NAME}.service"
sed "s/__PUBLIC_PORT__/${PORT}/g" "$APP_DIR/deploy/nginx-ip.conf.template" > "/etc/nginx/sites-available/${APP_NAME}"
ln -sfn "/etc/nginx/sites-available/${APP_NAME}" "/etc/nginx/sites-enabled/${APP_NAME}"
nginx -t

chown -R root:root "$APP_DIR"
chmod -R a+rX "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" "$PROFILE_DIR"
systemctl daemon-reload
systemctl enable --now "${APP_NAME}.service"
systemctl enable --now nginx
systemctl reload nginx

if [[ "$OPENCLAW_MODE" == "ask" && "$NON_INTERACTIVE" -eq 0 ]]; then
  read -r -p "Connect OpenClaw now? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] && OPENCLAW_MODE="yes" || OPENCLAW_MODE="no"
fi
if [[ "$OPENCLAW_MODE" == "yes" ]]; then
  args=(--wechat --auto)
  [[ "$INSTALL_OPENCLAW" -eq 1 ]] && args+=(--install-openclaw)
  [[ "$NON_INTERACTIVE" -eq 1 ]] && args+=(--non-interactive)
  bash "$APP_DIR/scripts/setup-openclaw.sh" "${args[@]}"
fi

say "Installation complete"
bash "$APP_DIR/scripts/show-admin-credentials.sh"
printf 'Show the credentials again: sudo bash %s/scripts/show-admin-credentials.sh\n' "$APP_DIR"
printf 'Open the management script: gongyu\n'
printf 'Service check: systemctl status %s\n' "$APP_NAME"
printf 'Cloud security groups/firewalls must allow TCP %s.\n' "$PORT"

#!/usr/bin/env bash
# Display the locally stored administrator credentials without changing them.
set -euo pipefail

ENV_FILE="/etc/douyin-fire-desk.env"
NGINX_FILE="/etc/nginx/sites-enabled/douyin-fire-desk"

[[ "$EUID" -eq 0 ]] || { printf 'Run with sudo: sudo bash scripts/show-admin-credentials.sh\n' >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { printf 'Configuration not found: %s\n' "$ENV_FILE" >&2; exit 1; }

read_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | head -n 1
}

username="$(read_value ADMIN_USERNAME)"
password="$(read_value ADMIN_PASSWORD)"
port="$(awk '/^[[:space:]]*listen[[:space:]]+[0-9]+/{gsub(";", "", $2); print $2; exit}' "$NGINX_FILE" 2>/dev/null || true)"
port="${port:-8787}"
ip_address="$(hostname -I 2>/dev/null | awk '{print $1}')"

printf 'Admin username: %s\n' "${username:-admin}"
printf 'Admin password: %s\n' "$password"
if [[ -n "$ip_address" ]]; then
  printf 'Web address (verify this is your public IP): http://%s:%s\n' "$ip_address" "$port"
else
  printf 'Web address: http://YOUR_SERVER_PUBLIC_IP:%s\n' "$port"
fi
printf '\nKeep this output private. Do not send the password in screenshots, chat, or Issues.\n'

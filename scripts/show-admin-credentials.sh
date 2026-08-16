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

valid_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

detect_public_ipv4() {
  local endpoint value
  # Tencent Cloud metadata works without requiring an outbound Internet route.
  for endpoint in \
    "http://metadata.tencentyun.com/latest/meta-data/public-ipv4" \
    "https://api.ipify.org" \
    "https://ip.3322.net"; do
    value="$(curl -4 -fsSL --connect-timeout 3 --max-time 5 "$endpoint" 2>/dev/null || true)"
    value="${value//$'\r'/}"
    value="${value//$'\n'/}"
    if valid_ipv4 "$value"; then
      printf '%s\n' "$value"
      return 0
    fi
  done
  return 1
}

username="$(read_value ADMIN_USERNAME)"
password="$(read_value ADMIN_PASSWORD)"
port="$(awk '/^[[:space:]]*listen[[:space:]]+[0-9]+/{gsub(";", "", $2); print $2; exit}' "$NGINX_FILE" 2>/dev/null || true)"
port="${port:-8787}"
public_ip="$(detect_public_ipv4 || true)"
local_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"

printf 'Admin username: %s\n' "${username:-admin}"
printf 'Admin password: %s\n' "$password"
if [[ -n "$public_ip" ]]; then
  printf 'Web address: http://%s:%s\n' "$public_ip" "$port"
elif [[ -n "$local_ip" ]]; then
  printf 'Web address: http://YOUR_SERVER_PUBLIC_IP:%s\n' "$port"
  printf 'Local address detected: http://%s:%s (do not use this from outside the server)\n' "$local_ip" "$port"
else
  printf 'Web address: http://YOUR_SERVER_PUBLIC_IP:%s\n' "$port"
fi
printf '\nKeep this output private. Do not send the password in screenshots, chat, or Issues.\n'

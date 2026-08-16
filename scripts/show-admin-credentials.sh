#!/usr/bin/env bash
# Display the locally stored administrator credentials without changing them.
set -euo pipefail

ENV_FILE="/etc/douyin-fire-desk.env"
NGINX_FILE="/etc/nginx/sites-enabled/douyin-fire-desk"

[[ "$EUID" -eq 0 ]] || { printf '请使用 sudo 运行：sudo bash scripts/show-admin-credentials.sh\n' >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { printf '未找到配置文件：%s\n' "$ENV_FILE" >&2; exit 1; }

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

printf '管理员用户名：%s\n' "${username:-admin}"
printf '管理员密码：%s\n' "$password"
if [[ -n "$public_ip" ]]; then
  printf '网页访问地址：http://%s:%s\n' "$public_ip" "$port"
elif [[ -n "$local_ip" ]]; then
  printf '网页访问地址：http://你的服务器公网IP:%s\n' "$port"
  printf '检测到内网地址：http://%s:%s（不能在服务器外部直接使用）\n' "$local_ip" "$port"
else
  printf '网页访问地址：http://你的服务器公网IP:%s\n' "$port"
fi
printf '\n请妥善保存以上信息，不要在截图、聊天记录或 Issues 中泄露管理员密码。\n'

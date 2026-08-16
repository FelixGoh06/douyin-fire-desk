#!/usr/bin/env bash
# Douyin Fire Desk v1.0 installer for common systemd Linux servers.
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
FORCE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_ARGS=("$@")

usage() {
  cat <<'EOF'
用法：sudo bash install.sh [选项]

选项：
  --port PORT           公网 Web 端口（默认 8787）
  --with-openclaw       自动安装 OpenClaw、微信、Skill 与通知功能
  --without-openclaw    跳过 OpenClaw 集成
  --install-openclaw    未安装时通过官网安装 OpenClaw
  --force               强制刷新 Web 平台文件和运行时（保留账号、Cookie 与数据库）
  --non-interactive     不询问交互问题；除非指定，否则跳过 OpenClaw
  -h, --help            显示此帮助
EOF
}

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\n错误：%s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:-}"; shift 2 ;;
    --with-openclaw) OPENCLAW_MODE="yes"; INSTALL_OPENCLAW=1; shift ;;
    --without-openclaw) OPENCLAW_MODE="no"; shift ;;
    --install-openclaw) OPENCLAW_MODE="yes"; INSTALL_OPENCLAW=1; shift ;;
    --force) FORCE=1; shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "未知选项：$1" ;;
  esac
done

[[ "$PORT" =~ ^[0-9]{2,5}$ ]] && (( PORT >= 1 && PORT <= 65535 )) || fail "--port 必须在 1 到 65535 之间。"
[[ -f "${SCRIPT_DIR}/run.py" ]] || fail "请在克隆后的项目目录中运行此脚本。"

if [[ "${EUID}" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || fail "请使用 root 运行，或先安装 sudo。"
  exec sudo -E bash "$0" "${ORIGINAL_ARGS[@]}"
fi

[[ -f /etc/os-release ]] || fail "无法识别 Linux 发行版。"
[[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1 || \
  fail "Web 管理平台需要 systemd。请在服务器主机的 SSH 终端运行，不要在 Docker 容器终端中运行。"
if command -v apt-get >/dev/null 2>&1; then
  PACKAGE_MANAGER="apt"
elif command -v dnf >/dev/null 2>&1; then
  PACKAGE_MANAGER="dnf"
elif command -v yum >/dev/null 2>&1; then
  PACKAGE_MANAGER="yum"
else
  fail "暂不支持当前系统的包管理器。已支持 apt、dnf 和 yum 系统。"
fi

nginx_config_present() {
  [[ -f "/etc/nginx/sites-available/${APP_NAME}" || -f "/etc/nginx/conf.d/${APP_NAME}.conf" ]]
}

create_virtualenv() {
  if python3 -m venv "$APP_DIR/.venv"; then
    return
  fi
  if command -v virtualenv >/dev/null 2>&1; then
    virtualenv -p python3 "$APP_DIR/.venv"
    return
  fi
  if python3 -m virtualenv "$APP_DIR/.venv"; then
    return
  fi
  fail "无法创建 Python 虚拟环境，请先运行菜单中的“安装必备依赖”后重试。"
}

web_already_installed() {
  [[ -f "$ENV_FILE" && -x "$APP_DIR/.venv/bin/python" ]] || return 1
  nginx_config_present || return 1
  systemctl is-enabled --quiet "${APP_NAME}.service" 2>/dev/null && systemctl is-active --quiet "${APP_NAME}.service" 2>/dev/null
}

if web_already_installed && [[ "$FORCE" -eq 0 ]]; then
  say "检测到 Web 管理平台已安装，已跳过重复安装"
  if [[ "$OPENCLAW_MODE" == "yes" ]]; then
    say "仅检查并补齐 OpenClaw 集成"
    args=(--wechat --auto)
    [[ "$INSTALL_OPENCLAW" -eq 1 ]] && args+=(--install-openclaw)
    [[ "$NON_INTERACTIVE" -eq 1 ]] && args+=(--non-interactive)
    bash "$APP_DIR/scripts/setup-openclaw.sh" "${args[@]}"
  fi
  bash "$APP_DIR/scripts/show-admin-credentials.sh"
  printf '需要刷新 Web 程序时可显式执行：sudo bash %s/install.sh --force\n' "$APP_DIR"
  exit 0
fi

say "正在检查必备系统依赖"
bash "$SCRIPT_DIR/scripts/install-dependencies.sh"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
if ! getent group "$AGENT_GROUP" >/dev/null 2>&1; then
  groupadd --system "$AGENT_GROUP"
fi

say "正在安装应用文件"
install -d -m 0755 "$APP_DIR"
if [[ "$(readlink -f "$SCRIPT_DIR")" != "$(readlink -f "$APP_DIR")" ]]; then
  rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude '.playwright/' --exclude '__pycache__/' \
    --exclude '.pytest_cache/' --exclude 'data/' --exclude '*.db' \
    "${SCRIPT_DIR}/" "${APP_DIR}/"
else
  say "正在使用已安装的应用文件"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR" "$PROFILE_DIR"

say "正在安装 Python 依赖与 Chromium"
create_virtualenv
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
bash "$APP_DIR/scripts/install-dependencies.sh" --browser-only

if [[ ! -f "$ENV_FILE" ]]; then
  say "正在生成首次运行密钥"
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
  say "保留已有配置：${ENV_FILE}"
fi

install -d -m 0755 /usr/local/lib/douyin-fire-desk
install -m 0700 "$APP_DIR/deploy/update-admin-password.py" /usr/local/lib/douyin-fire-desk/update-admin-password
install -m 0755 "$APP_DIR/deploy/gongyu" /usr/local/bin/gongyu
printf '%s ALL=(root) NOPASSWD: /usr/local/lib/douyin-fire-desk/update-admin-password\n' "$SERVICE_USER" > /etc/sudoers.d/douyin-fire-desk-password
chmod 0440 /etc/sudoers.d/douyin-fire-desk-password
visudo -cf /etc/sudoers.d/douyin-fire-desk-password

if [[ ! -f "$AGENT_ENV_FILE" ]]; then
  agent_token="$(grep -m1 '^AGENT_API_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)"
  [[ -n "$agent_token" ]] || fail "${ENV_FILE} 中缺少 AGENT_API_TOKEN"
  printf 'OPENCLAW_BASE_URL=http://127.0.0.1:7788\nAGENT_API_TOKEN=%s\n' "$agent_token" > "$AGENT_ENV_FILE"
  chown root:"$AGENT_GROUP" "$AGENT_ENV_FILE"
  chmod 0640 "$AGENT_ENV_FILE"
fi

if ! grep -q '^ADMIN_PASSWORD_UPDATE_COMMAND=' "$ENV_FILE"; then
  printf 'ADMIN_PASSWORD_UPDATE_COMMAND=/usr/local/lib/douyin-fire-desk/update-admin-password\n' >> "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
fi

install -m 0644 "$APP_DIR/deploy/douyin-fire-desk.service" "/etc/systemd/system/${APP_NAME}.service"
if [[ -d /etc/nginx/sites-available ]]; then
  sed "s/__PUBLIC_PORT__/${PORT}/g" "$APP_DIR/deploy/nginx-ip.conf.template" > "/etc/nginx/sites-available/${APP_NAME}"
  ln -sfn "/etc/nginx/sites-available/${APP_NAME}" "/etc/nginx/sites-enabled/${APP_NAME}"
else
  install -d -m 0755 /etc/nginx/conf.d
  sed "s/__PUBLIC_PORT__/${PORT}/g" "$APP_DIR/deploy/nginx-ip.conf.template" > "/etc/nginx/conf.d/${APP_NAME}.conf"
fi
nginx -t

if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" == "Enforcing" ]]; then
  if command -v setsebool >/dev/null 2>&1; then
    setsebool -P httpd_can_network_connect on || fail "无法配置 SELinux 的 Nginx 反向代理权限。"
  else
    fail "SELinux 正在强制执行，请安装 policycoreutils 后重新运行。"
  fi
fi

chown -R root:root "$APP_DIR"
chmod -R a+rX "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" "$PROFILE_DIR"
systemctl daemon-reload
systemctl enable --now "${APP_NAME}.service"
systemctl enable --now nginx
systemctl reload nginx

if [[ "$OPENCLAW_MODE" == "ask" && "$NON_INTERACTIVE" -eq 0 ]]; then
  read -r -p "现在接入 OpenClaw？[y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] && OPENCLAW_MODE="yes" || OPENCLAW_MODE="no"
fi
if [[ "$OPENCLAW_MODE" == "yes" ]]; then
  args=(--wechat --auto)
  [[ "$INSTALL_OPENCLAW" -eq 1 ]] && args+=(--install-openclaw)
  [[ "$NON_INTERACTIVE" -eq 1 ]] && args+=(--non-interactive)
  bash "$APP_DIR/scripts/setup-openclaw.sh" "${args[@]}"
fi

say "安装完成"
bash "$APP_DIR/scripts/show-admin-credentials.sh"
printf '再次查看账号密码：sudo bash %s/scripts/show-admin-credentials.sh\n' "$APP_DIR"
printf '打开管理脚本：gongyu\n'
printf '检查服务状态：systemctl status %s\n' "$APP_NAME"
printf '请在云安全组和防火墙中放行 TCP %s。\n' "$PORT"

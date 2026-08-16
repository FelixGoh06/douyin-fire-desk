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
LOCK_FILE="/run/lock/douyin-fire-desk-openclaw-setup.lock"
INSTALL_OPENCLAW=0
NON_INTERACTIVE=0
AUTO_SETUP=0
WITH_WECHAT=0
NOTIFY_TARGET=""
OPENCLAW_USER="${SUDO_USER:-${USER:-root}}"

say() { printf '\n==> %s\n' "$*"; }
note() { printf '%s\n' "$*"; }
fail() { printf '\n错误：%s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
用法：sudo bash scripts/setup-openclaw.sh [选项]

选项：
  --install-openclaw  未安装时通过官网安装 OpenClaw
  --wechat            安装腾讯微信插件并显示扫码登录
  --auto              使用引导式模型配置，其余本地步骤自动完成
  --notify-target ID  设置已知的通知接收者 ID
  --user USER         OpenClaw 所属 Linux 用户（默认当前调用用户）
  --non-interactive   不询问通用频道配置问题
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
    *) fail "未知选项：$1" ;;
  esac
done

[[ "$EUID" -eq 0 ]] || fail "请使用 sudo 或 root 运行此脚本。"
[[ -f "$ENV_FILE" ]] || fail "请先安装抖音火花运营台：sudo bash install.sh"
[[ -f "$AGENT_ENV_FILE" ]] || fail "缺少 Agent 配置，请先重新运行 sudo bash install.sh。"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || fail "已有另一项 OpenClaw 配置任务正在运行，请等待其结束后重试。"
fi
id "$OPENCLAW_USER" >/dev/null 2>&1 || fail "User does not exist: $OPENCLAW_USER"
OPENCLAW_HOME="$(getent passwd "$OPENCLAW_USER" | cut -d: -f6)"
[[ -n "$OPENCLAW_HOME" && -d "$OPENCLAW_HOME" ]] || fail "无法找到用户 $OPENCLAW_USER 的主目录。"

systemd_available() {
  [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1
}

run_as_openclaw() {
  runuser -u "$OPENCLAW_USER" -- env HOME="$OPENCLAW_HOME" PATH="$OPENCLAW_HOME/.local/share/pnpm:$OPENCLAW_HOME/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "$@"
}

run_as_openclaw_timeout() {
  local duration="$1"
  shift
  timeout "$duration" runuser -u "$OPENCLAW_USER" -- env HOME="$OPENCLAW_HOME" PATH="$OPENCLAW_HOME/.local/share/pnpm:$OPENCLAW_HOME/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "$@"
}

find_openclaw() {
  local candidate
  for candidate in "$(command -v openclaw 2>/dev/null || true)" "$OPENCLAW_HOME/.local/share/pnpm/openclaw" "$OPENCLAW_HOME/.npm-global/bin/openclaw"; do
    [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

gateway_status() {
  local status
  status="$(run_as_openclaw "$OPENCLAW_COMMAND" gateway status 2>&1 || true)"
  printf '%s\n' "$status" | grep -q 'Runtime: running' && printf '%s\n' "$status" | grep -q 'Connectivity probe: ok'
}

wechat_channel_connected() {
  local status
  status="$(run_as_openclaw "$OPENCLAW_COMMAND" channels status --probe 2>&1 || true)"
  printf '%s\n' "$status" | grep -Eq '^[-[:space:]]*openclaw-weixin .*enabled, configured, running'
}

wechat_plugin_installed() {
  run_as_openclaw "$OPENCLAW_COMMAND" plugins inspect openclaw-weixin >/dev/null 2>&1
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
  say "当前环境没有 systemd，正在启动 OpenClaw Gateway 后台进程"
  run_as_openclaw bash -lc "nohup $(printf '%q' "$OPENCLAW_COMMAND") gateway > $(printf '%q' "$log_file") 2>&1 & echo \$! > $(printf '%q' "$pid_file")"
  sleep 3
  gateway_status || fail "Gateway 启动失败，请查看日志：$log_file"
}

ensure_gateway() {
  gateway_status && return 0
  if systemd_available; then
    say "正在启动受 systemd 管理的 OpenClaw Gateway"
    install_gateway_service
    run_as_openclaw "$OPENCLAW_COMMAND" gateway start >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6; do
      sleep 5
      gateway_status && return 0
    done
    fail "Gateway 不可用。请执行：sudo -u $OPENCLAW_USER HOME=$OPENCLAW_HOME $OPENCLAW_COMMAND gateway status"
  else
    start_container_gateway
  fi
}

restart_gateway_after_channel_login() {
  if systemd_available; then
    say "微信登录完成，正在重载 Gateway"
    run_as_openclaw "$OPENCLAW_COMMAND" gateway restart >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6; do
      sleep 5
      gateway_status && return 0
    done
    fail "微信登录后 Gateway 未恢复。请执行：sudo -u $OPENCLAW_USER HOME=$OPENCLAW_HOME $OPENCLAW_COMMAND gateway status"
  else
    start_container_gateway
  fi
}

start_container_notifier() {
  local pid_file="$RUNTIME_DIR/notifier.pid"
  local log_file="$RUNTIME_DIR/notifier.log"
  local loop_script="$SKILL_DIR/scripts/notify-openclaw-loop.sh"
  [[ -n "$channel" && -n "$target" ]] || { note "通知功能正在等待已验证的接收者。"; return 0; }
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    return 0
  fi
  install -d -o "$OPENCLAW_USER" -g "$OPENCLAW_USER" -m 0750 "$RUNTIME_DIR"
  run_as_openclaw bash -lc "nohup $(printf '%q' "$loop_script") > $(printf '%q' "$log_file") 2>&1 & echo \$! > $(printf '%q' "$pid_file")"
  note "容器通知进程已启动，日志：$log_file"
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
  pairing_output="$(run_as_openclaw_timeout 12s "$OPENCLAW_COMMAND" pairing list openclaw-weixin 2>&1 || true)"
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
  local deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
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
  [[ "$INSTALL_OPENCLAW" -eq 1 || "$AUTO_SETUP" -eq 1 ]] || fail "尚未安装 OpenClaw，请携带 --install-openclaw 参数重新运行。"
  say "正在通过 OpenClaw 官方安装器安装"
  # Skip the installer's unrestricted onboarding. The guided `onboard` call below
  # is deliberately limited to model configuration; this script owns channel setup.
  run_as_openclaw bash -lc 'curl --proto "=https" --tlsv1.2 -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard --no-prompt'
  OPENCLAW_COMMAND="$(find_openclaw || true)"
  [[ -n "$OPENCLAW_COMMAND" ]] || fail "OpenClaw 安装完成但未找到命令。请以用户 $OPENCLAW_USER 登录后重新运行脚本。"
fi

if [[ ! -f "$OPENCLAW_HOME/.openclaw/openclaw.json" ]]; then
  [[ "$NON_INTERACTIVE" -eq 0 ]] || fail "模型配置需要交互式终端，请不要使用 --non-interactive 重新运行。"
  say "请配置模型服务商"
  note "只有模型服务商和 API Key 页面需要手动输入。请勿把 API Key 发到聊天记录中。"
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
[[ -d "$SKILL_SOURCE" ]] || fail "缺少内置 Skill：$SKILL_SOURCE"
say "正在安装 douyin-fire-admin Skill"
install -d -o "$OPENCLAW_USER" -g "$OPENCLAW_USER" -m 0755 "$(dirname "$SKILL_DIR")"
rsync -a --delete --exclude '__pycache__/' "$SKILL_SOURCE/" "$SKILL_DIR/"
chown -R "$OPENCLAW_USER:$OPENCLAW_USER" "$SKILL_DIR"
chmod 0755 "$SKILL_DIR/scripts/notify-openclaw-loop.sh"

channel="$(get_env_value OPENCLAW_CHANNEL "$OPENCLAW_ENV_FILE")"
target="${NOTIFY_TARGET:-$(get_env_value OPENCLAW_NOTIFY_TARGET "$OPENCLAW_ENV_FILE")}"
if [[ "$WITH_WECHAT" -eq 1 ]]; then
  say "正在安装并连接微信"
  if wechat_channel_connected; then
    note "微信已连接，跳过重复扫码。"
  elif wechat_plugin_installed; then
    note "微信插件已安装，请使用专用 OpenClaw 微信号扫描二维码。"
    run_as_openclaw "$OPENCLAW_COMMAND" channels login --channel openclaw-weixin
    restart_gateway_after_channel_login
  else
    note "正在安装微信插件，随后请使用专用 OpenClaw 微信号扫描唯一的一张二维码。"
    # The official WeChat plugin installer performs the initial QR login itself.
    # Calling `channels login` after it would prompt for a second QR code.
    run_as_openclaw npx -y @tencent-weixin/openclaw-weixin-cli install
    run_as_openclaw "$OPENCLAW_COMMAND" config set plugins.entries.openclaw-weixin.enabled true
    restart_gateway_after_channel_login
  fi
  channel="openclaw-weixin"
  if [[ -z "$target" && "$NON_INTERACTIVE" -eq 0 ]]; then
    note "请使用接收通知的微信号，向刚连接的机器人微信号发送任意私聊消息。"
    note "正在等待接收号配对请求，最长 3 分钟；不需要在终端输入任何内容。"
    if wait_for_wechat_recipient; then
      note "微信接收号已自动完成配对。"
    else
      note "暂未发现接收号。Skill 可以正常使用，但自动汇报会保持关闭；请让接收号发消息后重新运行此脚本。"
    fi
  fi
elif [[ "$NON_INTERACTIVE" -eq 0 && "$AUTO_SETUP" -eq 0 ]]; then
  read -r -p "OpenClaw 通知频道${channel:+ [$channel]}（留空稍后配置）：" entered_channel
  read -r -p "通知接收者 / 目标${target:+ [$target]}（留空稍后配置）：" entered_target
  channel="${entered_channel:-$channel}"
  target="${entered_target:-$target}"
fi

if [[ "$channel" == *$'\n'* || "$target" == *$'\n'* ]]; then
  fail "频道和接收者不能包含换行符。"
fi
umask 077
printf 'DOUYIN_FIRE_ENV_FILE=%s\nOPENCLAW_COMMAND=%s\nOPENCLAW_CHANNEL=%s\nOPENCLAW_NOTIFY_TARGET=%s\n' \
  "$AGENT_ENV_FILE" "$OPENCLAW_COMMAND" "$channel" "$target" > "$OPENCLAW_ENV_FILE"
chmod 0600 "$OPENCLAW_ENV_FILE"

ensure_gateway
install_notification_runtime

say "OpenClaw 集成已就绪"
note "已安装 Skill：douyin-fire-admin"
note "验证命令：sudo -u $OPENCLAW_USER HOME=$OPENCLAW_HOME $OPENCLAW_COMMAND skills info douyin-fire-admin"
if [[ -n "$channel" && -n "$target" ]]; then
  note "自动汇报：已通过 $channel 启用"
else
  note "自动汇报：正在等待接收者。微信接收号发送配对消息后，请携带 --wechat 重新运行此脚本。"
fi
if ! systemd_available; then
  note "容器提示：Gateway 和通知进程由 nohup 运行。请配置容器自动重启，并在容器重建后重新运行此脚本。"
fi

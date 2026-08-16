#!/usr/bin/env bash
# Install and start OpenClaw while leaving model configuration to its own wizard.
set -euo pipefail

OPENCLAW_USER="${SUDO_USER:-${USER:-root}}"
case "${1:-}" in
  "") ;;
  -h|--help)
    printf 'Usage: sudo bash scripts/install-openclaw-runtime.sh\n'
    exit 0
    ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
esac
[[ "$EUID" -eq 0 ]] || { printf 'Run with sudo or as root.\n' >&2; exit 1; }
if ! command -v curl >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl
fi
id "$OPENCLAW_USER" >/dev/null 2>&1 || { printf 'OpenClaw user does not exist: %s\n' "$OPENCLAW_USER" >&2; exit 1; }
OPENCLAW_HOME="$(getent passwd "$OPENCLAW_USER" | cut -d: -f6)"
[[ -d "$OPENCLAW_HOME" ]] || { printf 'Could not locate the home directory for %s.\n' "$OPENCLAW_USER" >&2; exit 1; }

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

OPENCLAW_COMMAND="$(find_openclaw || true)"
if [[ -z "$OPENCLAW_COMMAND" ]]; then
  printf '\n==> Installing OpenClaw from the official installer\n'
  run_as_openclaw bash -lc 'curl --proto "=https" --tlsv1.2 -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard --no-prompt'
  OPENCLAW_COMMAND="$(find_openclaw || true)"
  [[ -n "$OPENCLAW_COMMAND" ]] || { printf 'OpenClaw command was not found after installation.\n' >&2; exit 1; }
fi

if [[ ! -f "$OPENCLAW_HOME/.openclaw/openclaw.json" ]]; then
  printf '\n==> Configure your model provider\n'
  printf 'Only the model configuration wizard requires input.\n'
  onboarding=(onboard --accept-risk --flow quickstart --skip-channels --skip-ui --skip-hooks --skip-search --skip-skills)
  if [[ -d /run/systemd/system ]] && systemctl show-environment >/dev/null 2>&1; then
    onboarding+=(--install-daemon)
  else
    onboarding+=(--skip-daemon --skip-health)
  fi
  run_as_openclaw env OPENCLAW_LOCALE=zh-CN "$OPENCLAW_COMMAND" "${onboarding[@]}"
fi

if [[ -d /run/systemd/system ]] && systemctl show-environment >/dev/null 2>&1; then
  run_as_openclaw "$OPENCLAW_COMMAND" gateway install >/dev/null 2>&1 || true
  run_as_openclaw "$OPENCLAW_COMMAND" gateway start >/dev/null 2>&1 || true
else
  run_as_openclaw bash -lc "nohup $(printf '%q' "$OPENCLAW_COMMAND") gateway >/tmp/openclaw-gateway.log 2>&1 &"
fi

for _ in 1 2 3 4 5 6; do
  sleep 5
  if run_as_openclaw "$OPENCLAW_COMMAND" gateway status >/dev/null 2>&1; then
    printf '\nOpenClaw Gateway is running.\n'
    run_as_openclaw "$OPENCLAW_COMMAND" gateway status
    exit 0
  fi
done

printf 'OpenClaw was installed but the Gateway is not healthy. Run: sudo -u %s HOME=%s %s gateway status\n' "$OPENCLAW_USER" "$OPENCLAW_HOME" "$OPENCLAW_COMMAND" >&2
exit 1

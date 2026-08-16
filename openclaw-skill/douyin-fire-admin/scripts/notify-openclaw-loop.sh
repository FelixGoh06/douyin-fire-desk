#!/usr/bin/env bash
# Fallback for containers without systemd: deliver pending reports once a minute.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="/etc/douyin-fire-desk-openclaw.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # This file is root-created and mode 0600; it only contains local integration settings.
  source "$ENV_FILE"
  set +a
fi

while true; do
  python3 "$SCRIPT_DIR/notify_openclaw.py" || true
  sleep 60
done

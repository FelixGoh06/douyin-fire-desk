#!/usr/bin/env python3
"""Root-only helper used by the web app to rotate ADMIN_PASSWORD safely."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ENV_FILE = Path("/etc/douyin-fire-desk.env")
PASSWORD_RE = re.compile(r"^[A-Za-z0-9!%+,\-./:=?@^_~]{12,128}$")


def main() -> int:
    password = sys.stdin.buffer.read().decode("utf-8").rstrip("\r\n")
    if not PASSWORD_RE.fullmatch(password):
        return 2
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    replacement = f"ADMIN_PASSWORD={password}"
    found = False
    updated: list[str] = []
    for line in lines:
        if line.startswith("ADMIN_PASSWORD="):
            updated.append(replacement)
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(replacement)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".douyin-fire-desk-", dir=ENV_FILE.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(updated) + "\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, ENV_FILE)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    subprocess.Popen(
        ["/bin/sh", "-c", "sleep 1; /bin/systemctl restart douyin-fire-desk.service"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import subprocess
import time

from .config import settings


SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


class PasswordUpdateError(RuntimeError):
    """Raised when the narrowly scoped privileged password helper fails."""


def verify_password(password: str) -> bool:
    return hmac.compare_digest(password.encode("utf-8"), settings.admin_password.encode("utf-8"))


def update_admin_password(password: str) -> None:
    command = settings.admin_password_update_command.strip()
    if not command:
        raise PasswordUpdateError("密码修改服务尚未配置")
    try:
        result = subprocess.run(
            ["sudo", "-n", command],
            input=f"{password}\n",
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PasswordUpdateError("密码修改服务不可用") from exc
    if result.returncode != 0:
        raise PasswordUpdateError("密码修改失败，请检查系统服务权限")


def create_session_token(username: str) -> str:
    issued_at = str(int(time.time()))
    nonce = secrets.token_urlsafe(12)
    payload = f"{username}|{issued_at}|{nonce}"
    signature = hmac.new(
        settings.session_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def read_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        username, issued_at, nonce, signature = raw.split("|", 3)
        payload = f"{username}|{issued_at}|{nonce}"
        expected = hmac.new(
            settings.session_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(time.time()) - int(issued_at) > SESSION_TTL_SECONDS:
            return None
        return username
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return None


def csrf_token(session_token: str) -> str:
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        f"csrf|{session_token}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_csrf(session_token: str | None, submitted: str | None) -> bool:
    if not session_token or not submitted:
        return False
    return hmac.compare_digest(csrf_token(session_token), submitted)

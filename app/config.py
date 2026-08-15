from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "续火管理后台")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "7788"))
    database_path: Path = Path(
        os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "admin.db"))
    )
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "change-me")
    session_secret: str = os.getenv("SESSION_SECRET", "development-secret-change-me")
    cookie_encryption_key: str = os.getenv("COOKIE_ENCRYPTION_KEY", "")
    session_secure: bool = _bool_env("SESSION_SECURE", False)
    runner_enabled: bool = _bool_env("RUNNER_ENABLED", False)
    browser_bin: str = os.getenv("BROWSER_BIN", "")
    browser_headless: bool = _bool_env("BROWSER_HEADLESS", True)
    use_xvfb: bool = _bool_env("USE_XVFB", True)
    callback_only_loopback: bool = _bool_env("CALLBACK_ONLY_LOOPBACK", True)
    agent_api_token: str = os.getenv("AGENT_API_TOKEN", "")
    admin_password_update_command: str = os.getenv("ADMIN_PASSWORD_UPDATE_COMMAND", "")
    timezone: str = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    base_path: str = os.getenv("BASE_PATH", "").rstrip("/")


settings = Settings()

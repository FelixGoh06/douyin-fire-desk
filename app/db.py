from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    send_time TEXT NOT NULL DEFAULT '09:00',
    night_check_time TEXT NOT NULL DEFAULT '23:20',
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    profile_path TEXT NOT NULL DEFAULT '',
    cookie_ciphertext TEXT NOT NULL DEFAULT '',
    cookie_updated_at TEXT,
    cookie_status TEXT NOT NULL DEFAULT 'missing',
    cookie_check_enabled INTEGER NOT NULL DEFAULT 1,
    cookie_check_time TEXT NOT NULL DEFAULT '08:45',
    openclaw_cookie_report_enabled INTEGER NOT NULL DEFAULT 1,
    target_url TEXT NOT NULL DEFAULT 'https://creator.douyin.com/creator-micro/data/following/chat',
    message_template TEXT NOT NULL DEFAULT '续火',
    retry_count INTEGER NOT NULL DEFAULT 3,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    login_status TEXT NOT NULL DEFAULT 'unknown',
    last_login_check TEXT,
    last_success_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    douyin_user_id TEXT NOT NULL DEFAULT '',
    last_resolved_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    message_template TEXT NOT NULL DEFAULT '',
    last_fire_days INTEGER,
    last_counterpart_at TEXT,
    renewal_status TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, name)
);

CREATE TABLE IF NOT EXISTS automation_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    send_time TEXT NOT NULL DEFAULT '09:00',
    night_check_enabled INTEGER NOT NULL DEFAULT 0,
    night_check_time TEXT NOT NULL DEFAULT '23:20',
    openclaw_send_report_enabled INTEGER NOT NULL DEFAULT 1,
    openclaw_night_report_enabled INTEGER NOT NULL DEFAULT 1,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    message_template TEXT NOT NULL DEFAULT '续火',
    retry_count INTEGER NOT NULL DEFAULT 3,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, name)
);

CREATE TABLE IF NOT EXISTS task_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES automation_tasks(id) ON DELETE CASCADE,
    nickname TEXT NOT NULL,
    douyin_user_id TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    message_template TEXT NOT NULL DEFAULT '',
    last_fire_days INTEGER,
    last_counterpart_at TEXT,
    renewal_status TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, nickname)
);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    automation_task_id INTEGER REFERENCES automation_tasks(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'scheduler',
    scheduled_for TEXT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    automation_task_id INTEGER REFERENCES automation_tasks(id) ON DELETE SET NULL,
    task_target_id INTEGER REFERENCES task_targets(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS openclaw_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_runs_created_at ON task_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_runs_account_id ON task_runs(account_id);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_automation_tasks_account_id ON automation_tasks(account_id);
CREATE INDEX IF NOT EXISTS idx_task_targets_task_id ON task_targets(task_id);
CREATE INDEX IF NOT EXISTS idx_openclaw_notifications_id ON openclaw_notifications(id);
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path: Path = settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15, check_same_thread=False)
    connection.row_factory = _row_factory
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        _ensure_column(connection, "accounts", "cookie_ciphertext", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "accounts", "cookie_updated_at", "TEXT")
        _ensure_column(connection, "accounts", "cookie_status", "TEXT NOT NULL DEFAULT 'missing'")
        _ensure_column(connection, "accounts", "cookie_check_enabled", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(connection, "accounts", "cookie_check_time", "TEXT NOT NULL DEFAULT '08:45'")
        _ensure_column(
            connection,
            "accounts",
            "openclaw_cookie_report_enabled",
            "INTEGER NOT NULL DEFAULT 1",
        )
        _ensure_column(connection, "contacts", "douyin_user_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "contacts", "last_resolved_at", "TEXT")
        _ensure_column(connection, "task_runs", "automation_task_id", "INTEGER")
        _ensure_column(connection, "events", "automation_task_id", "INTEGER")
        _ensure_column(connection, "events", "task_target_id", "INTEGER")
        _ensure_column(
            connection,
            "automation_tasks",
            "openclaw_send_report_enabled",
            "INTEGER NOT NULL DEFAULT 1",
        )
        _ensure_column(
            connection,
            "automation_tasks",
            "openclaw_night_report_enabled",
            "INTEGER NOT NULL DEFAULT 1",
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_runs_automation_task_id "
            "ON task_runs(automation_task_id)"
        )
        _migrate_legacy_tasks(connection)


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_legacy_tasks(connection: sqlite3.Connection) -> None:
    marker = connection.execute(
        "SELECT value FROM app_settings WHERE key = 'legacy_tasks_migrated'"
    ).fetchone()
    if marker:
        return
    timestamp = now_iso()
    accounts = connection.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    for account in accounts:
        task_id = connection.execute(
            """
            INSERT INTO automation_tasks(
                account_id, name, enabled, send_time, night_check_enabled, night_check_time,
                timezone, message_template, retry_count, timeout_seconds, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account["id"], f"{account['name']} 默认续火", account["enabled"], account["send_time"],
                account["night_check_time"], account["timezone"], account["message_template"],
                account["retry_count"], account["timeout_seconds"], "由原账号配置自动迁移",
                timestamp, timestamp,
            ),
        ).lastrowid
        contacts = connection.execute(
            "SELECT * FROM contacts WHERE account_id = ? ORDER BY id", (account["id"],)
        ).fetchall()
        for contact in contacts:
            connection.execute(
                """
                INSERT INTO task_targets(
                    task_id, nickname, douyin_user_id, enabled, message_template,
                    last_fire_days, last_counterpart_at, renewal_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, contact["name"], contact["douyin_user_id"], contact["enabled"],
                    contact["message_template"], contact["last_fire_days"], contact["last_counterpart_at"],
                    contact["renewal_status"], timestamp, timestamp,
                ),
            )
    connection.execute(
        "INSERT INTO app_settings(key, value, updated_at) VALUES ('legacy_tasks_migrated', '1', ?)",
        (timestamp,),
    )


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as connection:
        return list(connection.execute(query, params).fetchall())


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connect() as connection:
        return connection.execute(query, params).fetchone()


def execute(query: str, params: tuple[Any, ...] = ()) -> int:
    with connect() as connection:
        cursor = connection.execute(query, params)
        return int(cursor.lastrowid or 0)


def json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def create_event(
    event_type: str,
    message: str,
    *,
    severity: str = "info",
    account_id: int | None = None,
    contact_id: int | None = None,
    automation_task_id: int | None = None,
    task_target_id: int | None = None,
    payload: Any = None,
) -> int:
    return execute(
        """
        INSERT INTO events(
            account_id, contact_id, automation_task_id, task_target_id,
            event_type, severity, message, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id, contact_id, automation_task_id, task_target_id,
            event_type, severity, message, json_text(payload or {}), now_iso(),
        ),
    )


def create_openclaw_notification(
    notification_type: str,
    message: str,
    *,
    payload: Any = None,
) -> int:
    return execute(
        """
        INSERT INTO openclaw_notifications(notification_type, message, payload_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (notification_type, message, json_text(payload or {}), now_iso()),
    )


def get_setting(key: str, default: str = "") -> str:
    row = fetch_one("SELECT value FROM app_settings WHERE key = ?", (key,))
    return str(row["value"]) if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        """
        INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now_iso()),
    )

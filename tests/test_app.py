import os
import importlib.util
import re
import sqlite3
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


TEST_DIR = Path(tempfile.mkdtemp(prefix="douyin-fire-admin-test-"))
os.environ["DATABASE_PATH"] = str(TEST_DIR / "test.db")
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SESSION_SECRET"] = "test-session-secret-with-enough-length"
os.environ["RUNNER_ENABLED"] = "0"
os.environ["AGENT_API_TOKEN"] = "test-openclaw-token"

from fastapi.testclient import TestClient

import app.db as db_module
import app.main as main_module
import app.openclaw_api as openclaw_api_module
from app.main import app
from app.cookies import decrypt_cookies
from app.db import SCHEMA, _migrate_legacy_tasks, fetch_all, fetch_one
from app.douyin_executor import _select_renewal_status, _summarize_renewal_timeline
from app.scheduler import schedule_manager


SKILL_SCRIPT = Path(__file__).resolve().parents[1] / "openclaw-skill" / "douyin-fire-admin" / "scripts" / "fire_admin.py"
skill_spec = importlib.util.spec_from_file_location("douyin_fire_admin_skill", SKILL_SCRIPT)
assert skill_spec and skill_spec.loader
skill_module = importlib.util.module_from_spec(skill_spec)
skill_spec.loader.exec_module(skill_module)
sys.modules.setdefault("fire_admin", skill_module)
NOTIFY_SCRIPT = SKILL_SCRIPT.with_name("notify_openclaw.py")
notify_spec = importlib.util.spec_from_file_location("douyin_fire_admin_notify", NOTIFY_SCRIPT)
assert notify_spec and notify_spec.loader
notify_module = importlib.util.module_from_spec(notify_spec)
notify_spec.loader.exec_module(notify_module)


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_admin_workflow():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        unauthenticated = client.get("/accounts", follow_redirects=False)
        assert unauthenticated.status_code == 303
        assert unauthenticated.headers["location"] == "/login"

        login = client.post(
            "/login",
            data={"username": "admin", "password": "test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        form_page = client.get("/accounts/new")
        assert 'class="task-editor account-editor"' in form_page.text
        token = csrf_from(form_page.text)
        created = client.post(
            "/accounts",
            data={
                "csrf": token,
                "name": "测试账号",
                "enabled": "on",
                "timezone": "Asia/Shanghai",
                "profile_path": "/tmp/test-profile",
                "cookie_value": "sessionid=test-session; ttwid=test-ttwid",
                "target_url": "https://www.douyin.com/chat",
                "notes": "",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert created.headers["location"].startswith("/accounts/1")

        stored = fetch_one(
            """
            SELECT cookie_ciphertext, cookie_status, cookie_check_enabled,
                   cookie_check_time, openclaw_cookie_report_enabled
            FROM accounts WHERE id = 1
            """
        )
        assert stored
        assert "test-session" not in stored["cookie_ciphertext"]
        assert {item["name"] for item in decrypt_cookies(stored["cookie_ciphertext"])} == {"sessionid", "ttwid"}
        assert stored["cookie_check_enabled"] == 1
        assert stored["cookie_check_time"] == "08:45"
        assert stored["openclaw_cookie_report_enabled"] == 1
        assert "cookie" in schedule_manager.jobs_for_account(1)

        task_form = client.get("/tasks/new?account_id=1")
        token = csrf_from(task_form.text)
        task = client.post(
            "/tasks",
            data={
                "csrf": token,
                "account_id": "1",
                "name": "每日续火",
                "enabled": "on",
                "send_time": "09:15",
                "night_check_enabled": "on",
                "night_check_time": "23:10",
                "timezone": "Asia/Shanghai",
                "message_template": "晚上好 [天数]",
                "retry_count": "3",
                "timeout_seconds": "300",
                "target_nicknames": "好友甲\n好友乙",
                "notes": "",
            },
            follow_redirects=False,
        )
        assert task.status_code == 303
        assert task.headers["location"].startswith("/tasks/1")
        stored_task = fetch_one(
            """
            SELECT openclaw_send_report_enabled, openclaw_night_report_enabled
            FROM automation_tasks WHERE id = 1
            """
        )
        assert stored_task == {
            "openclaw_send_report_enabled": 1,
            "openclaw_night_report_enabled": 1,
        }

        openclaw_page = client.get("/openclaw")
        assert openclaw_page.status_code == 200
        assert "每日续火结果" in openclaw_page.text
        assert "晚间检查结果" in openclaw_page.text
        assert "Cookie 健康检查" in openclaw_page.text
        assert "Cookie 健康回复" in openclaw_page.text

        agent_config = client.get(
            "/api/agent/config/1",
            headers={"X-Agent-Token": "test-openclaw-token"},
        )
        assert agent_config.status_code == 200
        assert "cookie_ciphertext" not in agent_config.json()["account"]
        assert agent_config.json()["account"]["has_cookie"] is True
        assert agent_config.json()["tasks"][0]["targets"][0]["nickname"] == "好友甲"

        assert "每日续火" in client.get("/tasks").text
        assert "好友甲" in client.get("/tasks/1").text
        assert "关联任务" in client.get("/accounts/1").text
        assert client.get("/").status_code == 200

        task_edit = client.get("/tasks/1/edit")
        assert task_edit.status_code == 200
        targets = fetch_all("SELECT id, nickname FROM task_targets WHERE task_id = 1 ORDER BY id")
        assert len(targets) == 2
        updated = client.post(
            "/tasks/1",
            content=urlencode([
                ("csrf", token),
                ("account_id", "1"),
                ("name", "每日续火（已编辑）"),
                ("enabled", "on"),
                ("send_time", "09:15"),
                ("night_check_enabled", "on"),
                ("night_check_time", "23:10"),
                ("timezone", "Asia/Shanghai"),
                ("message_template", "晚上好[天数]"),
                ("retry_count", "3"),
                ("timeout_seconds", "300"),
                ("notes", ""),
                ("target_id", str(targets[0]["id"])),
                ("target_nickname", targets[1]["nickname"]),
                ("target_id", str(targets[1]["id"])),
                ("target_nickname", targets[0]["nickname"]),
            ]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert updated.status_code == 303
        renamed_targets = fetch_all("SELECT id, nickname FROM task_targets WHERE task_id = 1 ORDER BY id")
        assert renamed_targets[0]["nickname"] == targets[1]["nickname"]
        assert renamed_targets[1]["nickname"] == targets[0]["nickname"]

        task_list = client.get("/tasks")
        assert '/tasks/1/run/night_check' in task_list.text
        assert '/tasks/1/delete' in task_list.text
        assert 'data-task-log-open' in task_list.text
        logs = client.get("/api/tasks/1/logs")
        assert logs.status_code == 200
        assert any(event["event_type"] == "automation_task_updated" for event in logs.json()["events"])

        json_run = client.post(
            "/tasks/1/run/night_check",
            data={"csrf": token},
            headers={"Accept": "application/json"},
        )
        assert json_run.status_code == 202
        assert json_run.json()["status"] == "queued"
        assert json_run.json()["task_type"] == "night_check"

        manual = client.post(
            "/tasks/1/run/send",
            data={"csrf": token},
            follow_redirects=False,
        )
        assert manual.status_code == 303


def test_night_check_requires_openclaw(monkeypatch):
    monkeypatch.setattr(main_module, "settings", replace(main_module.settings, agent_api_token=""))
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        form_page = client.get("/tasks/new?account_id=1")
        assert 'name="night_check_enabled"' in form_page.text
        assert 'disabled aria-disabled="true"' in form_page.text
        assert 'name="cookie_check_enabled"' in client.get("/openclaw").text
        token = csrf_from(form_page.text)
        response = client.post(
            "/tasks",
            data={
                "csrf": token,
                "account_id": "1",
                "name": "不应创建的晚间任务",
                "enabled": "on",
                "send_time": "10:00",
                "night_check_enabled": "on",
                "night_check_time": "23:00",
                "timezone": "Asia/Shanghai",
            },
        )
        assert response.status_code == 422
        assert "OpenClaw" in response.text


def test_openclaw_report_settings_update():
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        page = client.get("/openclaw")
        token = csrf_from(page.text)
        response = client.post(
            "/openclaw/tasks/1",
            data={"csrf": token, "night_report_enabled": "on"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        task = fetch_one(
            """
            SELECT openclaw_send_report_enabled, openclaw_night_report_enabled
            FROM automation_tasks WHERE id = 1
            """
        )
        assert task["openclaw_send_report_enabled"] == 0
        assert task["openclaw_night_report_enabled"] == 1

        cookie_response = client.post(
            "/openclaw/accounts/1",
            data={
                "csrf": token,
                "cookie_check_enabled": "on",
                "cookie_check_time": "07:30",
                "cookie_report_enabled": "on",
            },
            follow_redirects=False,
        )
        assert cookie_response.status_code == 303
        account = fetch_one(
            """
            SELECT cookie_check_enabled, cookie_check_time, openclaw_cookie_report_enabled
            FROM accounts WHERE id = 1
            """
        )
        assert account == {
            "cookie_check_enabled": 1,
            "cookie_check_time": "07:30",
            "openclaw_cookie_report_enabled": 1,
        }

        runs = client.get("/runs")
        assert "浏览器执行器尚未启用" in runs.text or "queued" in runs.text


def test_rejects_bad_time():
    with TestClient(app) as client:
        client.post("/login", data={"username": "admin", "password": "test-password"})
        token = csrf_from(client.get("/accounts/new").text)
        account = client.post(
            "/accounts",
            data={
                "csrf": token,
                "name": "错误时间账号",
                "enabled": "on",
                "timezone": "Asia/Shanghai",
                "profile_path": "",
                "cookie_value": "sessionid=test-session",
                "target_url": "https://www.douyin.com/chat",
                "notes": "",
            },
        )
        assert account.status_code == 200
        token = csrf_from(client.get("/tasks/new?account_id=1").text)
        response = client.post(
            "/tasks",
            data={
                "csrf": token,
                "account_id": "1",
                "name": "错误时间任务",
                "enabled": "on",
                "send_time": "25:99",
                "night_check_time": "23:10",
                "timezone": "Asia/Shanghai",
                "message_template": "续火",
                "retry_count": "3",
                "timeout_seconds": "300",
                "target_nicknames": "好友甲",
                "notes": "",
            },
        )
        assert response.status_code == 422


def test_openclaw_control_api(monkeypatch):
    monkeypatch.setattr(
        openclaw_api_module,
        "settings",
        SimpleNamespace(agent_api_token="test-openclaw-token", timezone="Asia/Shanghai"),
    )
    headers = {"X-Agent-Token": "test-openclaw-token"}
    monkeypatch.setattr(
        openclaw_api_module.schedule_manager,
        "enqueue_batch",
        lambda task_ids, task_type, source: {
            "status": "queued",
            "batch_id": "test-batch",
            "task_type": task_type,
            "runs": [{"run_id": 88, "task_id": task_ids[0]}] if task_ids else [],
        },
    )
    monkeypatch.setattr(
        openclaw_api_module.schedule_manager,
        "enqueue_account_batch",
        lambda account_ids, source: {
            "status": "queued",
            "batch_id": "cookie-batch",
            "task_type": "login_check",
            "runs": [{"run_id": 99, "account_id": account_ids[0]}] if account_ids else [],
        },
    )
    with TestClient(app) as client:
        assert client.get("/api/openclaw/overview").status_code == 401
        overview = client.get("/api/openclaw/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["accounts"]
        assert "cookie_ciphertext" not in overview.json()["accounts"][0]

        report = client.get("/api/openclaw/report?hours=24", headers=headers)
        assert report.status_code == 200
        assert "runs" in report.json()
        assert "last_checked_at" in report.json()["targets"][0]

        latest_run = fetch_one("SELECT id FROM task_runs ORDER BY id DESC LIMIT 1")
        run_result = client.get(f"/api/openclaw/runs/{latest_run['id']}", headers=headers)
        assert run_result.status_code == 200
        assert isinstance(run_result.json()["contacts"], list)
        assert "terminal" in run_result.json()

        command = client.post(
            "/api/openclaw/command",
            headers=headers,
            json={"action": "task.update", "data": {"task_id": 1, "send_time": "10:05"}},
        )
        assert command.status_code == 200
        assert command.json()["status"] == "updated"
        assert fetch_one("SELECT send_time FROM automation_tasks WHERE id = 1")["send_time"] == "10:05"

        notifications = client.get("/api/openclaw/notifications", headers=headers)
        assert notifications.status_code == 200
        assert "latest_id" in notifications.json()

        batch = client.post(
            "/api/openclaw/command",
            headers=headers,
            json={"action": "task.check-all", "data": {}},
        )
        assert batch.status_code == 200
        assert batch.json()["batch_id"] == "test-batch"
        assert batch.json()["task_type"] == "night_check"

        cookie_batch = client.post(
            "/api/openclaw/command",
            headers=headers,
            json={"action": "cookie.check-all", "data": {}},
        )
        assert cookie_batch.status_code == 200
        assert cookie_batch.json()["batch_id"] == "cookie-batch"
        assert cookie_batch.json()["task_type"] == "login_check"


def test_skill_check_target_waits_for_fresh_result(monkeypatch):
    calls = []

    def fake_api_request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/api/openclaw/overview":
            return {
                "tasks": [{
                    "id": 3,
                    "name": "宝贝",
                    "enabled": 1,
                    "targets": [{"id": 2, "nickname": "宝贝", "enabled": 1}],
                }]
            }
        if method == "POST" and payload and payload.get("action") == "task.check-all":
            return {
                "status": "queued",
                "batch_id": "batch-29",
                "runs": [{"run_id": 29, "task_id": 3, "task_name": "宝贝"}],
            }
        if method == "POST":
            return {"status": "queued", "run_id": 29}
        return {
            "terminal": True,
            "server_time": "2026-08-15T18:14:31+08:00",
            "run": {
                "id": 29,
                "status": "success",
                "finished_at": "2026-08-15T18:14:31+08:00",
            },
            "contacts": [{
                "target_id": 2,
                "nickname": "宝贝",
                "renewal_status": "renewed",
                "fire_days": 347,
                "last_counterpart_at": "2026-08-15T12:24:00+08:00",
            }],
        }

    monkeypatch.setattr(skill_module, "api_request", fake_api_request)
    result = skill_module.check_target("宝贝", timeout_seconds=2, poll_seconds=0.01)
    assert result["fresh_check"] is True
    assert result["result"]["renewal_status"] == "renewed"
    assert result["checked_at"] == "2026-08-15T18:14:31+08:00"
    assert calls[1][2]["action"] == "task.check"

    calls.clear()
    all_result = skill_module.check_all_targets(timeout_seconds=2, poll_seconds=0.01)
    assert all_result["fresh_check"] is True
    assert all_result["expected_count"] == all_result["returned_count"] == 1
    assert len(all_result["answer_rows"]) == 1
    assert all_result["results"][0]["nickname"] == "宝贝"
    assert all_result["results"][0]["result"]["renewal_status"] == "renewed"
    assert all_result["batch_id"] == "batch-29"
    assert calls[1][2]["action"] == "task.check-all"


def test_openclaw_batch_message_orders_attention_first():
    message = notify_module.format_message([{
        "notification_type": "task_batch_completed",
        "payload": {
            "task_type": "night_check",
            "counts": {"not_renewed": 1, "unknown": 1, "renewed": 1},
            "contacts": [
                {"nickname": "已续好友", "renewal_status": "renewed", "fire_days": 8},
                {"nickname": "未知好友", "renewal_status": "unknown"},
                {"nickname": "未续好友", "renewal_status": "not_renewed", "fire_days": 3},
            ],
            "runs": [],
        },
    }])
    assert message.index("未续：未续好友") < message.index("未知：未知好友") < message.index("已续：已续好友")

    send_message = notify_module.format_message([{
        "notification_type": "task_batch_completed",
        "payload": {
            "task_type": "send",
            "counts": {"failed": 1, "success": 1},
            "contacts": [
                {"nickname": "成功好友", "status": "success"},
                {"nickname": "失败好友", "status": "failed"},
            ],
            "runs": [],
        },
    }])
    assert send_message.index("失败：失败好友") < send_message.index("成功：成功好友")

    cookie_message = notify_module.format_message([{
        "notification_type": "task_batch_completed",
        "payload": {
            "task_type": "login_check",
            "counts": {"missing": 1, "expired": 1, "unknown": 1, "valid": 1},
            "accounts": [
                {"account_name": "有效账号", "cookie_status": "valid"},
                {"account_name": "未知账号", "cookie_status": "unknown"},
                {"account_name": "失效账号", "cookie_status": "expired"},
                {"account_name": "未保存账号", "cookie_status": "missing"},
            ],
            "runs": [],
        },
    }])
    assert cookie_message.index("未保存：未保存账号") < cookie_message.index("失效：失效账号")
    assert cookie_message.index("失效：失效账号") < cookie_message.index("未知：未知账号")
    assert cookie_message.index("未知：未知账号") < cookie_message.index("有效：有效账号")


def test_migrates_legacy_account_configuration():
    migration_db = TEST_DIR / "migration.db"
    connection = sqlite3.connect(migration_db)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO accounts(name, send_time, message_template, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("旧账号", "08:30", "旧模板", "2026-01-01T00:00:00+08:00", "2026-01-01T00:00:00+08:00"),
    )
    connection.execute(
        "INSERT INTO contacts(account_id, name, created_at, updated_at) VALUES (1, ?, ?, ?)",
        ("旧好友", "2026-01-01T00:00:00+08:00", "2026-01-01T00:00:00+08:00"),
    )
    _migrate_legacy_tasks(connection)
    task = connection.execute("SELECT * FROM automation_tasks WHERE account_id = 1").fetchone()
    target = connection.execute("SELECT * FROM task_targets WHERE task_id = ?", (task["id"],)).fetchone()
    assert task["send_time"] == "08:30"
    assert task["message_template"] == "旧模板"
    assert task["night_check_enabled"] == 0
    assert target["nickname"] == "旧好友"
    connection.close()


def test_init_db_upgrades_legacy_task_runs_before_creating_index(monkeypatch):
    legacy_db = TEST_DIR / "legacy-startup.db"
    connection = sqlite3.connect(legacy_db)
    connection.executescript(
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            send_time TEXT NOT NULL DEFAULT '09:00',
            night_check_time TEXT NOT NULL DEFAULT '23:20',
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
            profile_path TEXT NOT NULL DEFAULT '',
            target_url TEXT NOT NULL DEFAULT '',
            message_template TEXT NOT NULL DEFAULT '',
            retry_count INTEGER NOT NULL DEFAULT 3,
            timeout_seconds INTEGER NOT NULL DEFAULT 300,
            login_status TEXT NOT NULL DEFAULT 'unknown',
            last_login_check TEXT,
            last_success_at TEXT,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            message_template TEXT NOT NULL DEFAULT '',
            last_fire_days INTEGER,
            last_counterpart_at TEXT,
            renewal_status TEXT NOT NULL DEFAULT 'unknown',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, name)
        );
        CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
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
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            contact_id INTEGER,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.close()

    monkeypatch.setattr(db_module, "settings", SimpleNamespace(database_path=legacy_db))
    db_module.init_db()

    connection = sqlite3.connect(legacy_db)
    task_run_columns = {row[1] for row in connection.execute("PRAGMA table_info(task_runs)")}
    indexes = {row[1] for row in connection.execute("PRAGMA index_list(task_runs)")}
    assert "automation_task_id" in task_run_columns
    assert "idx_task_runs_automation_task_id" in indexes
    connection.close()


def test_detects_counterpart_renewal_from_today_timeline():
    result = _summarize_renewal_timeline(
        [
            {"y": 10, "outgoing": True, "time_label": "昨天 19:13"},
            {"y": 20, "outgoing": False, "time_label": "09:36"},
            {"y": 30, "outgoing": True, "time_label": "13分钟前"},
        ],
        "Asia/Shanghai",
        now=datetime(2026, 8, 15, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert result["renewal_status"] == "renewed"
    assert result["last_counterpart_at"] == "2026-08-15T09:36:00+08:00"
    assert _select_renewal_status(
        "https://lf3-static.bytednsdoc.com/flame_icon/normal/gray_normal.png",
        result["renewal_status"],
    ) == "not_renewed"


def test_admin_password_change_requires_current_password_and_logs_out(monkeypatch):
    updated_passwords: list[str] = []
    monkeypatch.setattr(main_module, "update_admin_password", updated_passwords.append)
    with TestClient(app) as client:
        client.post("/login", data={"username": "admin", "password": "test-password"})
        token = csrf_from(client.get("/system").text)
        changed = client.post(
            "/system/password",
            data={
                "csrf": token,
                "current_password": "test-password",
                "new_password": "NewPassword2026!",
                "confirm_password": "NewPassword2026!",
            },
            follow_redirects=False,
        )
        assert changed.status_code == 303
        assert changed.headers["location"].startswith("/login?message=")
        assert updated_passwords == ["NewPassword2026!"]
        assert "douyin_admin_session=" in changed.headers["set-cookie"]

        client.post("/login", data={"username": "admin", "password": "test-password"})
        token = csrf_from(client.get("/system").text)
        rejected = client.post(
            "/system/password",
            data={
                "csrf": token,
                "current_password": "wrong-password",
                "new_password": "OtherPassword2026!",
                "confirm_password": "OtherPassword2026!",
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        assert "/system?error=" in rejected.headers["location"]
        assert updated_passwords == ["NewPassword2026!"]

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from .config import settings
from .cookies import CookieError, encrypt_cookie_input
from .db import create_event, execute, fetch_all, fetch_one, now_iso
from .scheduler import schedule_manager


router = APIRouter(prefix="/api/openclaw", tags=["openclaw"])


def require_openclaw_token(x_agent_token: str | None = Header(None)) -> None:
    if not settings.agent_api_token or x_agent_token != settings.agent_api_token:
        raise HTTPException(status_code=401, detail="invalid OpenClaw token")


def _time_value(value: Any, field: str) -> str:
    text = str(value or "").strip()
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must use HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(status_code=422, detail=f"{field} must use HH:MM")
    return f"{hour:02d}:{minute:02d}"


def _bool_value(value: Any, default: bool = False) -> int:
    if value is None:
        return 1 if default else 0
    if isinstance(value, bool):
        return 1 if value else 0
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"} else 0


def _required_id(payload: dict[str, Any], key: str) -> int:
    try:
        value = int(payload.get(key) or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} is required") from exc
    if value <= 0:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value


def _target_values(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
    result: list[dict[str, Any]] = []
    for item in value or []:
        result.append({"nickname": item} if isinstance(item, str) else dict(item))
    return result


def _safe_account(row: dict[str, Any]) -> dict[str, Any]:
    safe = dict(row)
    safe["has_cookie"] = bool(safe.pop("cookie_ciphertext", ""))
    return safe


@router.get("/overview", dependencies=[Depends(require_openclaw_token)])
def openclaw_overview() -> dict[str, Any]:
    accounts = fetch_all("SELECT * FROM accounts ORDER BY id")
    tasks = fetch_all(
        """
        SELECT t.*, a.name AS account_name,
               (SELECT COUNT(*) FROM task_targets x WHERE x.task_id = t.id) AS target_count,
               (SELECT status FROM task_runs r WHERE r.automation_task_id = t.id ORDER BY r.id DESC LIMIT 1) AS last_run_status,
               (SELECT summary FROM task_runs r WHERE r.automation_task_id = t.id ORDER BY r.id DESC LIMIT 1) AS last_run_summary
        FROM automation_tasks t JOIN accounts a ON a.id = t.account_id ORDER BY t.id
        """
    )
    for task in tasks:
        task["targets"] = fetch_all("SELECT * FROM task_targets WHERE task_id = ? ORDER BY id", (task["id"],))
        task["next_jobs"] = schedule_manager.jobs_for_task(int(task["id"]))
    stats = fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM accounts) AS accounts,
          (SELECT COUNT(*) FROM accounts WHERE enabled = 1) AS enabled_accounts,
          (SELECT COUNT(*) FROM automation_tasks) AS tasks,
          (SELECT COUNT(*) FROM automation_tasks WHERE enabled = 1) AS enabled_tasks,
          (SELECT COUNT(*) FROM task_targets WHERE enabled = 1) AS enabled_targets,
          (SELECT COUNT(*) FROM task_runs WHERE date(created_at) = date('now', 'localtime')) AS today_runs,
          (SELECT COUNT(*) FROM task_runs WHERE date(created_at) = date('now', 'localtime') AND status IN ('failed','blocked','timeout')) AS today_failures
        """
    )
    return {
        "server_time": now_iso(),
        "stats": stats or {},
        "accounts": [_safe_account(account) for account in accounts],
        "tasks": tasks,
    }


@router.get("/report", dependencies=[Depends(require_openclaw_token)])
def openclaw_report(hours: int = Query(24, ge=1, le=168)) -> dict[str, Any]:
    since = (datetime.now().astimezone() - timedelta(hours=hours)).isoformat(timespec="seconds")
    runs = fetch_all(
        """
        SELECT r.id, r.task_type, r.source, r.status, r.summary, r.started_at, r.finished_at, r.created_at,
               a.id AS account_id, a.name AS account_name, t.id AS task_id, t.name AS task_name
        FROM task_runs r
        LEFT JOIN accounts a ON a.id = r.account_id
        LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
        WHERE r.created_at >= ? ORDER BY r.id
        """,
        (since,),
    )
    accounts = fetch_all(
        """
        SELECT id, name, enabled, cookie_status, login_status, last_login_check, last_success_at,
               CASE WHEN cookie_ciphertext <> '' THEN 1 ELSE 0 END AS has_cookie
        FROM accounts ORDER BY id
        """
    )
    target_status = fetch_all(
        """
        SELECT x.id, x.nickname, x.renewal_status, x.last_fire_days, x.last_counterpart_at,
               x.updated_at, t.id AS task_id, t.name AS task_name,
               (SELECT e.created_at FROM events e
                WHERE e.task_target_id = x.id AND e.event_type = 'contact_night_check'
                ORDER BY e.id DESC LIMIT 1) AS last_checked_at,
               (SELECT json_extract(e.payload_json, '$.renewal_evidence') FROM events e
                WHERE e.task_target_id = x.id AND e.event_type = 'contact_night_check'
                ORDER BY e.id DESC LIMIT 1) AS renewal_evidence,
               (SELECT json_extract(e.payload_json, '$.today_window_observed') FROM events e
                WHERE e.task_target_id = x.id AND e.event_type = 'contact_night_check'
                ORDER BY e.id DESC LIMIT 1) AS today_window_observed
        FROM task_targets x JOIN automation_tasks t ON t.id = x.task_id
        WHERE x.enabled = 1 ORDER BY t.id, x.id
        """
    )
    return {
        "period": {"hours": hours, "since": since, "until": now_iso()},
        "summary": {
            "total": len(runs),
            "success": sum(run["status"] == "success" for run in runs),
            "partial": sum(run["status"] == "partial" for run in runs),
            "failed": sum(run["status"] in {"failed", "blocked", "timeout"} for run in runs),
        },
        "accounts": accounts,
        "runs": runs,
        "targets": target_status,
    }


@router.get("/runs/{run_id}", dependencies=[Depends(require_openclaw_token)])
def openclaw_run(run_id: int) -> dict[str, Any]:
    run = fetch_one(
        """
        SELECT r.id, r.task_type, r.source, r.status, r.summary, r.scheduled_for,
               r.started_at, r.finished_at, r.created_at, r.payload_json,
               a.id AS account_id, a.name AS account_name,
               t.id AS task_id, t.name AS task_name
        FROM task_runs r
        LEFT JOIN accounts a ON a.id = r.account_id
        LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
        WHERE r.id = ?
        """,
        (run_id,),
    )
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        payload = json.loads(run.pop("payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    terminal_statuses = {"success", "partial", "failed", "blocked", "timeout"}
    return {
        "run": run,
        "payload": payload,
        "contacts": payload.get("contacts") or [],
        "terminal": run["status"] in terminal_statuses,
        "server_time": now_iso(),
    }


@router.get("/notifications", dependencies=[Depends(require_openclaw_token)])
def openclaw_notifications(after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    rows = fetch_all(
        """
        SELECT id, notification_type, message, payload_json, created_at
        FROM openclaw_notifications WHERE id > ? ORDER BY id LIMIT ?
        """,
        (after_id, limit),
    )
    for row in rows:
        try:
            row["payload"] = json.loads(row.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            row["payload"] = {}
    latest = fetch_one("SELECT COALESCE(MAX(id), 0) AS id FROM openclaw_notifications") or {"id": after_id}
    return {"notifications": rows, "latest_id": int(latest["id"]), "server_time": now_iso()}


@router.post("/command", dependencies=[Depends(require_openclaw_token)])
async def openclaw_command(request: Request) -> dict[str, Any]:
    payload = await request.json()
    action = str(payload.get("action") or "").strip().lower()
    data = dict(payload.get("data") or {})
    timestamp = now_iso()

    if action in {"task.run-all", "task.check-all"}:
        task_type = "night_check" if action == "task.check-all" else str(data.get("task_type") or "send")
        if task_type not in {"send", "night_check"}:
            raise HTTPException(status_code=422, detail="task_type must be send or night_check")
        tasks = fetch_all(
            """
            SELECT t.id FROM automation_tasks t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.enabled = 1 AND a.enabled = 1
              AND EXISTS (SELECT 1 FROM task_targets x WHERE x.task_id = t.id AND x.enabled = 1)
            ORDER BY t.id
            """
        )
        return schedule_manager.enqueue_batch(
            [int(task["id"]) for task in tasks],
            task_type,
            "openclaw",
        )

    if action in {"task.run", "task.check"}:
        task_id = _required_id(data, "task_id")
        task_type = "night_check" if action == "task.check" else str(data.get("task_type") or "send")
        if task_type not in {"send", "night_check"}:
            raise HTTPException(status_code=422, detail="task_type must be send or night_check")
        run_id = schedule_manager.enqueue_task(task_id, task_type, "openclaw")
        return {"status": "queued", "run_id": run_id, "task_id": task_id, "task_type": task_type}

    if action in {"account.check", "cookie.check"}:
        account_id = _required_id(data, "account_id")
        run_id = schedule_manager.enqueue_account_check(account_id, "openclaw")
        return {"status": "queued", "run_id": run_id, "account_id": account_id, "task_type": "login_check"}

    if action == "cookie.check-all":
        accounts = fetch_all("SELECT id, name FROM accounts WHERE enabled = 1 ORDER BY id")
        return schedule_manager.enqueue_account_batch(
            [int(account["id"]) for account in accounts],
            "openclaw",
        )

    if action == "account.create":
        name = str(data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name is required")
        cookie_value = str(data.get("cookie_value") or "").strip()
        cookie_ciphertext = ""
        cookie_count = 0
        if cookie_value:
            try:
                cookie_ciphertext, cookie_count = encrypt_cookie_input(cookie_value)
            except CookieError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        account_id = execute(
            """
            INSERT INTO accounts(name, enabled, timezone, profile_path, cookie_ciphertext, cookie_updated_at,
                cookie_status, cookie_check_enabled, cookie_check_time, openclaw_cookie_report_enabled,
                target_url, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, _bool_value(data.get("enabled"), True), str(data.get("timezone") or settings.timezone),
                str(data.get("profile_path") or ""), cookie_ciphertext, timestamp if cookie_value else None,
                "unknown" if cookie_value else "missing", _bool_value(data.get("cookie_check_enabled"), True),
                _time_value(data.get("cookie_check_time", "08:45"), "cookie_check_time"),
                _bool_value(data.get("openclaw_cookie_report_enabled"), True),
                str(data.get("target_url") or "https://www.douyin.com/chat"),
                str(data.get("notes") or ""), timestamp, timestamp,
            ),
        )
        create_event("account_created", f"OpenClaw 已添加账号 {name}", account_id=account_id, payload={"cookie_count": cookie_count})
        schedule_manager.reload()
        return {"status": "created", "account_id": account_id, "cookie_count": cookie_count}

    if action in {"account.update", "cookie.update"}:
        account_id = _required_id(data, "account_id")
        account = fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if not account:
            raise HTTPException(status_code=404, detail="account not found")
        values = {
            "name": str(data.get("name", account["name"])).strip(),
            "enabled": _bool_value(data.get("enabled"), bool(account["enabled"])) if "enabled" in data else account["enabled"],
            "timezone": str(data.get("timezone", account["timezone"])),
            "profile_path": str(data.get("profile_path", account["profile_path"])),
            "target_url": str(data.get("target_url", account["target_url"])),
            "notes": str(data.get("notes", account["notes"])),
            "cookie_ciphertext": account["cookie_ciphertext"],
            "cookie_status": account["cookie_status"],
            "cookie_updated_at": account["cookie_updated_at"],
            "cookie_check_enabled": _bool_value(data["cookie_check_enabled"]) if "cookie_check_enabled" in data else account["cookie_check_enabled"],
            "cookie_check_time": _time_value(data.get("cookie_check_time", account["cookie_check_time"]), "cookie_check_time"),
            "openclaw_cookie_report_enabled": _bool_value(data["openclaw_cookie_report_enabled"]) if "openclaw_cookie_report_enabled" in data else account["openclaw_cookie_report_enabled"],
        }
        cookie_count = 0
        if "cookie_value" in data:
            try:
                values["cookie_ciphertext"], cookie_count = encrypt_cookie_input(str(data.get("cookie_value") or ""))
            except CookieError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            values["cookie_status"] = "unknown"
            values["cookie_updated_at"] = timestamp
        if data.get("clear_cookie"):
            values["cookie_ciphertext"] = ""
            values["cookie_status"] = "missing"
            values["cookie_updated_at"] = timestamp
        execute(
            """
            UPDATE accounts SET name = ?, enabled = ?, timezone = ?, profile_path = ?, target_url = ?, notes = ?,
                cookie_ciphertext = ?, cookie_status = ?, cookie_updated_at = ?,
                cookie_check_enabled = ?, cookie_check_time = ?, openclaw_cookie_report_enabled = ?,
                login_status = CASE WHEN ? THEN 'unknown' ELSE login_status END, updated_at = ? WHERE id = ?
            """,
            (
                values["name"], values["enabled"], values["timezone"], values["profile_path"], values["target_url"], values["notes"],
                values["cookie_ciphertext"], values["cookie_status"], values["cookie_updated_at"],
                values["cookie_check_enabled"], values["cookie_check_time"], values["openclaw_cookie_report_enabled"],
                1 if "cookie_value" in data or data.get("clear_cookie") else 0, timestamp, account_id,
            ),
        )
        create_event("account_updated", f"OpenClaw 已更新账号 {values['name']}", account_id=account_id)
        schedule_manager.reload()
        return {"status": "updated", "account_id": account_id, "cookie_count": cookie_count}

    if action == "account.toggle":
        account_id = _required_id(data, "account_id")
        execute("UPDATE accounts SET enabled = 1 - enabled, updated_at = ? WHERE id = ?", (timestamp, account_id))
        schedule_manager.reload()
        return {"status": "updated", "account_id": account_id}

    if action == "account.delete":
        account_id = _required_id(data, "account_id")
        account = fetch_one("SELECT name FROM accounts WHERE id = ?", (account_id,))
        if not account:
            raise HTTPException(status_code=404, detail="account not found")
        execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        create_event("account_deleted", f"OpenClaw 已删除账号 {account['name']}")
        schedule_manager.reload()
        return {"status": "deleted", "account_id": account_id}

    if action == "task.create":
        account_id = _required_id(data, "account_id")
        name = str(data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name is required")
        task_id = execute(
            """
            INSERT INTO automation_tasks(account_id, name, enabled, send_time, night_check_enabled, night_check_time,
                openclaw_send_report_enabled, openclaw_night_report_enabled,
                timezone, message_template, retry_count, timeout_seconds, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id, name, _bool_value(data.get("enabled"), True), _time_value(data.get("send_time", "09:00"), "send_time"),
                _bool_value(data.get("night_check_enabled"), False), _time_value(data.get("night_check_time", "23:20"), "night_check_time"),
                _bool_value(data.get("openclaw_send_report_enabled"), True),
                _bool_value(data.get("openclaw_night_report_enabled"), True),
                str(data.get("timezone") or settings.timezone), str(data.get("message_template") or "续火"),
                max(0, min(int(data.get("retry_count", 3)), 10)), max(30, min(int(data.get("timeout_seconds", 300)), 1800)),
                str(data.get("notes") or ""), timestamp, timestamp,
            ),
        )
        for target in _target_values(data.get("targets") or data.get("target_nicknames")):
            nickname = str(target.get("nickname") or "").strip()
            if nickname:
                execute(
                    """
                    INSERT INTO task_targets(task_id, nickname, douyin_user_id, enabled, message_template, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id, nickname, str(target.get("douyin_user_id") or ""), _bool_value(target.get("enabled"), True),
                        str(target.get("message_template") or ""), timestamp, timestamp,
                    ),
                )
        create_event("automation_task_created", f"OpenClaw 已创建任务 {name}", account_id=account_id, automation_task_id=task_id)
        schedule_manager.reload()
        return {"status": "created", "task_id": task_id}

    if action == "task.update":
        task_id = _required_id(data, "task_id")
        task = fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        values = {
            "account_id": int(data.get("account_id", task["account_id"])),
            "name": str(data.get("name", task["name"])).strip(),
            "enabled": _bool_value(data["enabled"]) if "enabled" in data else task["enabled"],
            "send_time": _time_value(data.get("send_time", task["send_time"]), "send_time"),
            "night_check_enabled": _bool_value(data["night_check_enabled"]) if "night_check_enabled" in data else task["night_check_enabled"],
            "night_check_time": _time_value(data.get("night_check_time", task["night_check_time"]), "night_check_time"),
            "openclaw_send_report_enabled": _bool_value(data["openclaw_send_report_enabled"]) if "openclaw_send_report_enabled" in data else task["openclaw_send_report_enabled"],
            "openclaw_night_report_enabled": _bool_value(data["openclaw_night_report_enabled"]) if "openclaw_night_report_enabled" in data else task["openclaw_night_report_enabled"],
            "timezone": str(data.get("timezone", task["timezone"])),
            "message_template": str(data.get("message_template", task["message_template"])),
            "retry_count": max(0, min(int(data.get("retry_count", task["retry_count"])), 10)),
            "timeout_seconds": max(30, min(int(data.get("timeout_seconds", task["timeout_seconds"])), 1800)),
            "notes": str(data.get("notes", task["notes"])),
        }
        execute(
            """
            UPDATE automation_tasks SET account_id = ?, name = ?, enabled = ?, send_time = ?, night_check_enabled = ?,
                night_check_time = ?, openclaw_send_report_enabled = ?, openclaw_night_report_enabled = ?,
                timezone = ?, message_template = ?, retry_count = ?, timeout_seconds = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (*values.values(), timestamp, task_id),
        )
        create_event("automation_task_updated", f"OpenClaw 已更新任务 {values['name']}", account_id=values["account_id"], automation_task_id=task_id)
        schedule_manager.reload()
        return {"status": "updated", "task_id": task_id}

    if action == "task.toggle":
        task_id = _required_id(data, "task_id")
        execute("UPDATE automation_tasks SET enabled = 1 - enabled, updated_at = ? WHERE id = ?", (timestamp, task_id))
        schedule_manager.reload()
        return {"status": "updated", "task_id": task_id}

    if action == "task.delete":
        task_id = _required_id(data, "task_id")
        task = fetch_one("SELECT account_id, name FROM automation_tasks WHERE id = ?", (task_id,))
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        execute("DELETE FROM automation_tasks WHERE id = ?", (task_id,))
        create_event("automation_task_deleted", f"OpenClaw 已删除任务 {task['name']}", account_id=task["account_id"])
        schedule_manager.reload()
        return {"status": "deleted", "task_id": task_id}

    if action == "target.create":
        task_id = _required_id(data, "task_id")
        nickname = str(data.get("nickname") or "").strip()
        if not nickname:
            raise HTTPException(status_code=422, detail="nickname is required")
        target_id = execute(
            """
            INSERT INTO task_targets(task_id, nickname, douyin_user_id, enabled, message_template, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, nickname, str(data.get("douyin_user_id") or ""), _bool_value(data.get("enabled"), True),
                str(data.get("message_template") or ""), timestamp, timestamp,
            ),
        )
        return {"status": "created", "target_id": target_id, "task_id": task_id}

    if action == "target.update":
        target_id = _required_id(data, "target_id")
        target = fetch_one("SELECT * FROM task_targets WHERE id = ?", (target_id,))
        if not target:
            raise HTTPException(status_code=404, detail="target not found")
        execute(
            """
            UPDATE task_targets SET nickname = ?, douyin_user_id = ?, enabled = ?, message_template = ?, updated_at = ? WHERE id = ?
            """,
            (
                str(data.get("nickname", target["nickname"])).strip(), str(data.get("douyin_user_id", target["douyin_user_id"])),
                _bool_value(data["enabled"]) if "enabled" in data else target["enabled"],
                str(data.get("message_template", target["message_template"])), timestamp, target_id,
            ),
        )
        return {"status": "updated", "target_id": target_id, "task_id": target["task_id"]}

    if action == "target.toggle":
        target_id = _required_id(data, "target_id")
        execute("UPDATE task_targets SET enabled = 1 - enabled, updated_at = ? WHERE id = ?", (timestamp, target_id))
        return {"status": "updated", "target_id": target_id}

    if action == "target.delete":
        target_id = _required_id(data, "target_id")
        target = fetch_one("SELECT task_id FROM task_targets WHERE id = ?", (target_id,))
        if not target:
            raise HTTPException(status_code=404, detail="target not found")
        execute("DELETE FROM task_targets WHERE id = ?", (target_id,))
        return {"status": "deleted", "target_id": target_id, "task_id": target["task_id"]}

    raise HTTPException(status_code=422, detail=f"unsupported action: {action}")

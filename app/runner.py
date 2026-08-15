from __future__ import annotations

import json
import threading
from typing import Any

from .config import settings
from .cookies import CookieError
from .db import (
    create_event,
    create_openclaw_notification,
    execute,
    fetch_all,
    fetch_one,
    json_text,
    now_iso,
    set_setting,
)
from .douyin_executor import DouyinExecutionError, execute_task


class RunnerManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_run_id: int | None = None

    def dispatch(self, run_id: int) -> None:
        threading.Thread(target=self._run, args=(run_id,), daemon=True).start()

    def dispatch_batch(self, run_ids: list[int], *, task_type: str, batch_id: str, source: str) -> None:
        threading.Thread(
            target=self._run_batch,
            args=(run_ids, task_type, batch_id, source),
            daemon=True,
        ).start()

    def _run(self, run_id: int, wait_for_lock: bool = False) -> None:
        if not self._lock.acquire(blocking=wait_for_lock):
            self._finish(run_id, "blocked", "已有账号任务正在执行")
            return
        try:
            row = fetch_one(
                """
                SELECT r.*, a.name AS account_name, a.enabled AS account_enabled,
                       a.profile_path, a.cookie_ciphertext, a.cookie_status, a.target_url,
                       a.openclaw_cookie_report_enabled,
                       COALESCE(t.message_template, a.message_template) AS message_template,
                       COALESCE(t.timeout_seconds, a.timeout_seconds) AS timeout_seconds,
                       COALESCE(t.timezone, a.timezone) AS timezone,
                       t.name AS automation_task_name, t.enabled AS automation_task_enabled,
                       t.openclaw_send_report_enabled, t.openclaw_night_report_enabled
                FROM task_runs r
                LEFT JOIN accounts a ON a.id = r.account_id
                LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
                WHERE r.id = ?
                """,
                (run_id,),
            )
            if not row or not row.get("account_id"):
                self._finish(run_id, "failed", "任务账号不存在")
                return
            if not row["account_enabled"]:
                self._finish(run_id, "blocked", "账号已停用")
                return
            if not settings.runner_enabled:
                self._finish(run_id, "blocked", "浏览器执行器尚未启用")
                return
            if not row.get("cookie_ciphertext"):
                self._finish(run_id, "blocked", "账号尚未保存 Cookie")
                return

            contacts: list[dict[str, Any]] = []
            if row["task_type"] in {"send", "night_check"}:
                if not row.get("automation_task_id"):
                    self._finish(run_id, "blocked", "执行记录没有关联具体任务")
                    return
                if not row.get("automation_task_enabled"):
                    self._finish(run_id, "blocked", "任务已停用")
                    return
                contacts = fetch_all(
                    """
                    SELECT id, nickname AS name, douyin_user_id, enabled, message_template,
                           last_fire_days, last_counterpart_at, renewal_status
                    FROM task_targets WHERE task_id = ? AND enabled = 1 ORDER BY id
                    """,
                    (row["automation_task_id"],),
                )
                if not contacts:
                    self._finish(run_id, "blocked", "没有启用的目标好友")
                    return

            self._active_run_id = run_id
            set_setting("active_run_id", str(run_id))
            execute(
                "UPDATE task_runs SET status = 'running', started_at = ?, summary = ? WHERE id = ?",
                (now_iso(), "浏览器已启动，正在验证 Cookie 和目标好友", run_id),
            )
            create_event(
                "task_started",
                f"{row.get('automation_task_name') or row['account_name']} 开始执行 {row['task_type']} 任务",
                account_id=int(row["account_id"]),
                automation_task_id=int(row["automation_task_id"]) if row.get("automation_task_id") else None,
                payload={"run_id": run_id, "contacts": [item["name"] for item in contacts]},
            )

            def write_progress(message: str, severity: str = "info", payload: dict[str, Any] | None = None) -> None:
                create_event(
                    "task_progress",
                    message,
                    severity=severity,
                    account_id=int(row["account_id"]),
                    automation_task_id=int(row["automation_task_id"]) if row.get("automation_task_id") else None,
                    payload={"run_id": run_id, **(payload or {})},
                )

            result = execute_task(row, contacts, run_id, progress=write_progress)
            self._store_result(run_id, row, result)
        except (CookieError, DouyinExecutionError) as exc:
            self._finish(run_id, "blocked", str(exc))
        except Exception as exc:
            self._finish(run_id, "failed", f"执行器异常：{exc}")
        finally:
            self._active_run_id = None
            set_setting("active_run_id", "")
            self._lock.release()

    def _run_batch(self, run_ids: list[int], task_type: str, batch_id: str, source: str) -> None:
        for run_id in run_ids:
            self._run(run_id, wait_for_lock=True)
        self._create_batch_notification(run_ids, task_type=task_type, batch_id=batch_id, source=source)

    @staticmethod
    def _is_batch_source(source: Any) -> bool:
        return ":batch:" in str(source or "")

    @staticmethod
    def _report_enabled(row: dict[str, Any]) -> bool:
        if not settings.agent_api_token:
            return False
        if row.get("task_type") == "login_check":
            return bool(row.get("openclaw_cookie_report_enabled"))
        if not row.get("automation_task_id") and not row.get("task_id"):
            return True
        field = (
            "openclaw_night_report_enabled"
            if row.get("task_type") == "night_check"
            else "openclaw_send_report_enabled"
        )
        return bool(row.get(field))

    def _create_batch_notification(self, run_ids: list[int], *, task_type: str, batch_id: str, source: str) -> None:
        if not run_ids:
            return
        placeholders = ",".join("?" for _ in run_ids)
        rows = fetch_all(
            f"""
            SELECT r.id AS run_id, r.status AS run_status, r.summary, r.payload_json,
                   r.account_id, r.automation_task_id AS task_id, r.task_type,
                   a.name AS account_name, a.cookie_status, a.last_login_check,
                   a.openclaw_cookie_report_enabled, t.name AS task_name,
                   t.openclaw_send_report_enabled, t.openclaw_night_report_enabled
            FROM task_runs r
            LEFT JOIN accounts a ON a.id = r.account_id
            LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
            WHERE r.id IN ({placeholders}) ORDER BY r.id
            """,
            tuple(run_ids),
        )
        contacts: list[dict[str, Any]] = []
        run_results: list[dict[str, Any]] = []
        for row in rows:
            if not self._report_enabled(row):
                continue
            try:
                payload = json.loads(row.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                payload = {}
            run_results.append({**row, "payload": payload})
            for item in payload.get("contacts") or []:
                contacts.append({
                    **item,
                    "run_id": row["run_id"],
                    "task_id": row["task_id"],
                    "task_name": row["task_name"],
                    "account_name": row["account_name"],
                })

        if not run_results:
            return

        accounts: list[dict[str, Any]] = []
        if task_type == "login_check":
            priority = {"missing": 0, "expired": 1, "unknown": 2, "valid": 3}
            accounts = [
                {
                    "account_id": row["account_id"],
                    "account_name": row["account_name"],
                    "cookie_status": str(row.get("cookie_status") or "unknown"),
                    "last_checked_at": row.get("last_login_check"),
                    "run_status": row["run_status"],
                    "summary": row.get("summary") or "",
                }
                for row in run_results
            ]
            accounts.sort(
                key=lambda item: (
                    priority.get(str(item.get("cookie_status") or "unknown"), 2),
                    str(item.get("account_name") or ""),
                )
            )
            counts = {
                status: sum(str(item.get("cookie_status") or "unknown") == status for item in accounts)
                for status in ("missing", "expired", "unknown", "valid")
            }
            message = (
                f"Cookie 健康检查完成：失效 {counts['expired']}，未保存 {counts['missing']}，"
                f"未知 {counts['unknown']}，有效 {counts['valid']}"
            )
        elif task_type == "night_check":
            order = {"not_renewed": 0, "unknown": 1, "renewed": 2}
            contacts.sort(key=lambda item: (order.get(str(item.get("renewal_status") or "unknown"), 1), str(item.get("nickname") or "")))
            counts = {
                status: sum(str(item.get("renewal_status") or "unknown") == status for item in contacts)
                for status in ("not_renewed", "unknown", "renewed")
            }
            message = (
                f"晚间检查完成：未续 {counts['not_renewed']}，"
                f"未知 {counts['unknown']}，已续 {counts['renewed']}"
            )
        else:
            contacts.sort(key=lambda item: (0 if str(item.get("status") or "failed") != "success" else 1, str(item.get("nickname") or "")))
            counts = {
                "failed": sum(str(item.get("status") or "failed") != "success" for item in contacts),
                "success": sum(str(item.get("status") or "failed") == "success" for item in contacts),
            }
            message = f"续火发送完成：失败 {counts['failed']}，成功 {counts['success']}"

        failed_runs = sum(row["run_status"] in {"failed", "blocked", "timeout"} for row in run_results)
        create_event(
            "task_batch_completed",
            message,
            severity="warning" if failed_runs else "info",
            payload={
                "batch_id": batch_id,
                "task_type": task_type,
                "runs": run_results,
                "contacts": contacts,
                "accounts": accounts,
                "counts": counts,
            },
        )
        create_openclaw_notification(
            "task_batch_completed",
            message,
            payload={
                "batch_id": batch_id,
                "task_type": task_type,
                "source": source,
                "status": "partial" if failed_runs else "success",
                "counts": counts,
                "runs": run_results,
                "contacts": contacts,
                "accounts": accounts,
            },
        )

    def _store_result(self, run_id: int, row: dict[str, Any], result: dict[str, Any]) -> None:
        status = str(result.get("status") or "failed")
        summary = str(result.get("summary") or "任务结束")
        payload = result.get("payload") or {}
        login_status = str(result.get("login_status") or "unknown")
        account_id = int(row["account_id"])
        previous_cookie_status = str(row.get("cookie_status") or "unknown")

        execute(
            "UPDATE task_runs SET status = ?, finished_at = ?, summary = ?, payload_json = ? WHERE id = ?",
            (status, now_iso(), summary, json_text(payload), run_id),
        )
        execute(
            "UPDATE accounts SET login_status = ?, cookie_status = ?, last_login_check = ?, updated_at = ? WHERE id = ?",
            (login_status, login_status, now_iso(), now_iso(), account_id),
        )
        if status == "success":
            execute(
                "UPDATE accounts SET last_success_at = ?, updated_at = ? WHERE id = ?",
                (now_iso(), now_iso(), account_id),
            )

        for item in payload.get("contacts", []):
            target_id = int(item.get("target_id") or item.get("contact_id") or 0)
            contact_status = str(item.get("status") or "failed")
            if target_id and row["task_type"] == "night_check":
                renewal_status = str(item.get("renewal_status") or "unknown")
                execute(
                    """
                    UPDATE task_targets SET last_fire_days = COALESCE(?, last_fire_days),
                        last_counterpart_at = COALESCE(?, last_counterpart_at),
                        renewal_status = ?, updated_at = ? WHERE id = ?
                    """,
                    (
                        item.get("fire_days"), item.get("last_counterpart_at"),
                        renewal_status, now_iso(), target_id,
                    ),
                )
                renewal_label = {
                    "renewed": "对方已续火",
                    "not_renewed": "对方未续火",
                    "unknown": "续火状态未知",
                }.get(renewal_status, renewal_status)
                create_event(
                    "contact_night_check",
                    f"好友 {item.get('nickname', '')}：{renewal_label}",
                    severity="warning" if renewal_status == "not_renewed" else "info",
                    account_id=account_id,
                    automation_task_id=int(row["automation_task_id"]) if row.get("automation_task_id") else None,
                    task_target_id=target_id,
                    payload=item,
                )
                continue
            if target_id and contact_status == "success":
                execute(
                    "UPDATE task_targets SET last_fire_days = COALESCE(last_fire_days, 0) + 1, updated_at = ? WHERE id = ?",
                    (now_iso(), target_id),
                )
            if target_id:
                create_event(
                    "contact_send",
                    f"好友 {item.get('nickname', '')}：{'发送成功' if contact_status == 'success' else '发送失败'}",
                    severity="info" if contact_status == "success" else "error",
                    account_id=account_id,
                    automation_task_id=int(row["automation_task_id"]) if row.get("automation_task_id") else None,
                    task_target_id=target_id,
                    payload=item,
                )

        create_event(
            "task_completed",
            summary,
            severity="error" if status in {"failed", "blocked"} else "warning" if status == "partial" else "info",
            account_id=account_id,
            automation_task_id=int(row["automation_task_id"]) if row.get("automation_task_id") else None,
            payload={"run_id": run_id, **payload},
        )
        notification_payload = {
            "run_id": run_id,
            "account_id": account_id,
            "account_name": row.get("account_name"),
            "task_id": row.get("automation_task_id"),
            "task_name": row.get("automation_task_name"),
            "task_type": row.get("task_type"),
            "status": status,
            "summary": summary,
            "login_status": login_status,
            "source": row.get("source"),
            "contacts": payload.get("contacts") or [],
        }
        if not self._is_batch_source(row.get("source")) and self._report_enabled(row):
            create_openclaw_notification("task_completed", summary, payload=notification_payload)
        if (
            row.get("task_type") != "login_check"
            and (login_status in {"expired", "missing"} or login_status != previous_cookie_status)
        ):
            cookie_message = f"账号 {row.get('account_name') or account_id} Cookie 状态：{login_status}"
            create_event(
                "cookie_status",
                cookie_message,
                severity="error" if login_status in {"expired", "missing"} else "info",
                account_id=account_id,
                payload={"previous": previous_cookie_status, "current": login_status, "run_id": run_id},
            )
            create_openclaw_notification(
                "cookie_status",
                cookie_message,
                payload={
                    "account_id": account_id,
                    "account_name": row.get("account_name"),
                    "previous": previous_cookie_status,
                    "current": login_status,
                    "run_id": run_id,
                },
            )

    def complete_active(self, payload: dict[str, Any]) -> int | None:
        run_id = self._active_run_id
        if not run_id:
            return None
        row = fetch_one("SELECT account_id FROM task_runs WHERE id = ?", (run_id,))
        status = "success" if payload.get("status", "success") == "success" else "partial"
        execute(
            "UPDATE task_runs SET status = ?, finished_at = ?, summary = ?, payload_json = ? WHERE id = ?",
            (status, now_iso(), "userscript 已回调", json_text(payload), run_id),
        )
        return run_id if row else None

    def _finish(self, run_id: int, status: str, summary: str) -> None:
        execute(
            "UPDATE task_runs SET status = ?, finished_at = ?, summary = ? WHERE id = ?",
            (status, now_iso(), summary, run_id),
        )
        row = fetch_one(
            """
            SELECT r.account_id, r.automation_task_id, r.task_type, r.source,
                   a.name AS account_name, a.cookie_status AS previous_cookie_status,
                   a.openclaw_cookie_report_enabled,
                   t.name AS automation_task_name,
                   t.openclaw_send_report_enabled, t.openclaw_night_report_enabled
            FROM task_runs r
            LEFT JOIN accounts a ON a.id = r.account_id
            LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
            WHERE r.id = ?
            """,
            (run_id,),
        )
        create_event(
            "task_finished",
            summary,
            severity="warning" if status == "blocked" else "error" if status in {"failed", "timeout"} else "info",
            account_id=int(row["account_id"]) if row and row.get("account_id") else None,
            automation_task_id=int(row["automation_task_id"]) if row and row.get("automation_task_id") else None,
            payload={"run_id": run_id, "status": status},
        )
        if row and not self._is_batch_source(row.get("source")) and self._report_enabled(row):
            create_openclaw_notification(
                "task_completed",
                summary,
                payload={
                    "run_id": run_id,
                    "account_id": row.get("account_id"),
                    "account_name": row.get("account_name"),
                    "task_id": row.get("automation_task_id"),
                    "task_name": row.get("automation_task_name"),
                    "task_type": row.get("task_type"),
                    "status": status,
                    "summary": summary,
                    "source": row.get("source"),
                },
            )
        if row and "Cookie" in summary:
            cookie_status = "missing" if "尚未保存" in summary else "expired"
            previous_cookie_status = str(row.get("previous_cookie_status") or "unknown")
            execute(
                "UPDATE accounts SET cookie_status = ?, login_status = ?, last_login_check = ?, updated_at = ? WHERE id = ?",
                (cookie_status, cookie_status, now_iso(), now_iso(), row["account_id"]),
            )
            if row.get("task_type") != "login_check":
                cookie_message = f"账号 {row.get('account_name') or row['account_id']} Cookie 状态：{cookie_status}"
                create_openclaw_notification(
                    "cookie_status",
                    cookie_message,
                    payload={
                        "account_id": row.get("account_id"),
                        "account_name": row.get("account_name"),
                        "previous": previous_cookie_status,
                        "current": cookie_status,
                        "run_id": run_id,
                    },
                )


runner = RunnerManager()

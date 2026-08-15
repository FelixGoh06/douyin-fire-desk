from __future__ import annotations

import hashlib
from collections import defaultdict
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .db import create_event, execute, fetch_all, fetch_one, now_iso
from .runner import runner


class ScheduleManager:
    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone=settings.timezone)
        self._task_job_ids: dict[tuple[int, str], str] = {}
        self._account_job_ids: dict[int, str] = {}

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        self.reload()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def reload(self) -> None:
        self.scheduler.remove_all_jobs()
        self._task_job_ids.clear()
        self._account_job_ids.clear()
        tasks = fetch_all(
            """
            SELECT t.* FROM automation_tasks t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.enabled = 1 AND a.enabled = 1
            ORDER BY t.id
            """
        )
        groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        for task in tasks:
            timezone = str(task.get("timezone") or settings.timezone)
            groups[("send", timezone, str(task["send_time"]))].append(int(task["id"]))
            if task.get("night_check_enabled") and settings.agent_api_token:
                groups[("night_check", timezone, str(task["night_check_time"]))].append(int(task["id"]))
        for (task_type, timezone, run_time), task_ids in groups.items():
            self._add_batch_job(task_ids, task_type, timezone, run_time)
        if settings.agent_api_token:
            accounts = fetch_all(
                """
                SELECT id, timezone, cookie_check_time FROM accounts
                WHERE enabled = 1 AND cookie_check_enabled = 1
                ORDER BY id
                """
            )
            account_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
            for account in accounts:
                timezone = str(account.get("timezone") or settings.timezone)
                account_groups[(timezone, str(account["cookie_check_time"]))].append(int(account["id"]))
            for (timezone, run_time), account_ids in account_groups.items():
                self._add_account_batch_job(account_ids, timezone, run_time)

    def _add_batch_job(self, task_ids: list[int], task_type: str, timezone: str, run_time: str) -> None:
        hour, minute = self._parse_time(run_time)
        kind = "night" if task_type == "night_check" else "send"
        digest = hashlib.sha1(f"{task_type}|{timezone}|{run_time}".encode("utf-8")).hexdigest()[:10]
        job_id = f"batch-{kind}-{digest}"
        self.scheduler.add_job(
            self.enqueue_batch,
            CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(timezone)),
            args=[task_ids, task_type, "scheduler"],
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=900,
        )
        for task_id in task_ids:
            self._task_job_ids[(task_id, kind)] = job_id

    def _add_account_batch_job(self, account_ids: list[int], timezone: str, run_time: str) -> None:
        hour, minute = self._parse_time(run_time)
        digest = hashlib.sha1(f"cookie|{timezone}|{run_time}".encode("utf-8")).hexdigest()[:10]
        job_id = f"batch-cookie-{digest}"
        self.scheduler.add_job(
            self.enqueue_account_batch,
            CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(timezone)),
            args=[account_ids, "scheduler"],
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=900,
        )
        for account_id in account_ids:
            self._account_job_ids[account_id] = job_id

    def enqueue_task(self, task_id: int, task_type: str, source: str) -> int:
        task = fetch_one(
            "SELECT id, account_id, name FROM automation_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            raise ValueError("任务不存在")
        run_id = execute(
            """
            INSERT INTO task_runs(
                account_id, automation_task_id, task_type, source, scheduled_for, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', ?)
            """,
            (task["account_id"], task_id, task_type, source, now_iso(), now_iso()),
        )
        create_event(
            "task_queued",
            f"任务 {task['name']} 已进入队列",
            account_id=int(task["account_id"]),
            automation_task_id=task_id,
            payload={"run_id": run_id, "task_type": task_type, "source": source},
        )
        runner.dispatch(run_id)
        return run_id

    def enqueue_batch(self, task_ids: list[int], task_type: str, source: str) -> dict:
        unique_ids = list(dict.fromkeys(int(task_id) for task_id in task_ids))
        if task_type not in {"send", "night_check"}:
            raise ValueError("不支持的批次任务类型")
        batch_id = uuid4().hex[:16]
        batch_source = f"{source}:batch:{batch_id}"
        runs: list[dict] = []
        for task_id in unique_ids:
            task = fetch_one(
                """
                SELECT t.id, t.account_id, t.name FROM automation_tasks t
                JOIN accounts a ON a.id = t.account_id
                WHERE t.id = ? AND t.enabled = 1 AND a.enabled = 1
                """,
                (task_id,),
            )
            if not task:
                continue
            run_id = execute(
                """
                INSERT INTO task_runs(
                    account_id, automation_task_id, task_type, source, scheduled_for, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?)
                """,
                (task["account_id"], task_id, task_type, batch_source, now_iso(), now_iso()),
            )
            runs.append({"run_id": run_id, "task_id": task_id, "task_name": task["name"]})
            create_event(
                "task_queued",
                f"任务 {task['name']} 已进入批次 {batch_id}",
                account_id=int(task["account_id"]),
                automation_task_id=task_id,
                payload={"run_id": run_id, "task_type": task_type, "source": source, "batch_id": batch_id},
            )
        if runs:
            runner.dispatch_batch(
                [int(item["run_id"]) for item in runs],
                task_type=task_type,
                batch_id=batch_id,
                source=source,
            )
        return {"status": "queued", "batch_id": batch_id, "task_type": task_type, "runs": runs}

    def enqueue_account_check(self, account_id: int, source: str = "manual") -> int:
        run_id = execute(
            """
            INSERT INTO task_runs(account_id, task_type, source, scheduled_for, status, created_at)
            VALUES (?, 'login_check', ?, ?, 'queued', ?)
            """,
            (account_id, source, now_iso(), now_iso()),
        )
        create_event(
            "task_queued",
            "账号登录检测已进入队列",
            account_id=account_id,
            payload={"run_id": run_id, "task_type": "login_check", "source": source},
        )
        runner.dispatch(run_id)
        return run_id

    def enqueue_account_batch(self, account_ids: list[int], source: str = "scheduler") -> dict:
        unique_ids = list(dict.fromkeys(int(account_id) for account_id in account_ids))
        batch_id = uuid4().hex[:16]
        batch_source = f"{source}:batch:{batch_id}"
        runs: list[dict] = []
        for account_id in unique_ids:
            account = fetch_one(
                "SELECT id, name FROM accounts WHERE id = ? AND enabled = 1",
                (account_id,),
            )
            if not account:
                continue
            run_id = execute(
                """
                INSERT INTO task_runs(account_id, task_type, source, scheduled_for, status, created_at)
                VALUES (?, 'login_check', ?, ?, 'queued', ?)
                """,
                (account_id, batch_source, now_iso(), now_iso()),
            )
            runs.append({"run_id": run_id, "account_id": account_id, "account_name": account["name"]})
            create_event(
                "task_queued",
                f"账号 {account['name']} 的 Cookie 检查已进入批次 {batch_id}",
                account_id=account_id,
                payload={"run_id": run_id, "task_type": "login_check", "source": source, "batch_id": batch_id},
            )
        if runs:
            runner.dispatch_batch(
                [int(item["run_id"]) for item in runs],
                task_type="login_check",
                batch_id=batch_id,
                source=source,
            )
        return {"status": "queued", "batch_id": batch_id, "task_type": "login_check", "runs": runs}

    def enqueue_and_dispatch(self, account_id: int, task_type: str, source: str) -> int:
        if task_type == "login_check":
            return self.enqueue_account_check(account_id, source)
        task = fetch_one(
            "SELECT id FROM automation_tasks WHERE account_id = ? AND enabled = 1 ORDER BY id LIMIT 1",
            (account_id,),
        )
        if not task:
            raise ValueError("账号没有启用的任务")
        return self.enqueue_task(int(task["id"]), task_type, source)

    def jobs_for_task(self, task_id: int) -> dict[str, str]:
        result: dict[str, str] = {}
        for kind in ("send", "night"):
            job_id = self._task_job_ids.get((task_id, kind))
            job = self.scheduler.get_job(job_id) if job_id else None
            if job and job.next_run_time:
                result[kind] = job.next_run_time.astimezone().isoformat(timespec="minutes")
        return result

    def jobs_for_account(self, account_id: int) -> dict[str, str]:
        task = fetch_one(
            "SELECT id FROM automation_tasks WHERE account_id = ? AND enabled = 1 ORDER BY id LIMIT 1",
            (account_id,),
        )
        result = self.jobs_for_task(int(task["id"])) if task else {}
        job_id = self._account_job_ids.get(account_id)
        job = self.scheduler.get_job(job_id) if job_id else None
        if job and job.next_run_time:
            result["cookie"] = job.next_run_time.astimezone().isoformat(timespec="minutes")
        return result

    @staticmethod
    def _parse_time(value: str) -> tuple[int, int]:
        try:
            hour_text, minute_text = value.strip().split(":", 1)
            hour, minute = int(hour_text), int(minute_text[:2])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            return hour, minute
        except (ValueError, AttributeError):
            return 0, 0


schedule_manager = ScheduleManager()

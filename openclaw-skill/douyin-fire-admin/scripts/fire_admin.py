#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:7788"
DEFAULT_ENV_FILE = Path("/etc/douyin-fire-desk-agent.env")
DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / ".notification-state.json"
TERMINAL_RUN_STATUSES = {"success", "partial", "failed", "blocked", "timeout"}


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def connection_settings() -> tuple[str, str]:
    file_values = read_env_file(Path(os.getenv("DOUYIN_FIRE_ENV_FILE", DEFAULT_ENV_FILE)))
    base_url = os.getenv("DOUYIN_FIRE_BASE_URL") or file_values.get("OPENCLAW_BASE_URL") or DEFAULT_BASE_URL
    token = os.getenv("DOUYIN_FIRE_AGENT_TOKEN") or file_values.get("AGENT_API_TOKEN") or ""
    if not token:
        raise RuntimeError("AGENT_API_TOKEN is not configured")
    return base_url.rstrip("/"), token


def api_request(method: str, path: str, payload: dict | None = None) -> dict:
    base_url, token = connection_settings()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={"X-Agent-Token": token, "Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"cannot reach Douyin fire admin: {exc.reason}") from exc


def parse_data(value: str) -> dict:
    if value == "@-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        value = Path(value[1:]).read_text(encoding="utf-8")
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("--data must be a JSON object")
    return parsed


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"last_notification_id": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_notification_id": 0}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def wait_for_run(run_id: int, timeout_seconds: int, poll_seconds: float) -> dict:
    deadline = time.monotonic() + max(1, timeout_seconds)
    latest: dict = {}
    while time.monotonic() < deadline:
        latest = api_request("GET", f"/api/openclaw/runs/{run_id}")
        run = latest.get("run") or {}
        if latest.get("terminal") or run.get("status") in TERMINAL_RUN_STATUSES:
            return latest
        time.sleep(max(0.5, poll_seconds))
    return latest


def check_target(nickname: str, timeout_seconds: int, poll_seconds: float) -> dict:
    requested = nickname.strip()
    if not requested:
        raise ValueError("nickname is required")
    overview = api_request("GET", "/api/openclaw/overview")
    matches: list[tuple[dict, dict]] = []
    for task in overview.get("tasks") or []:
        for target in task.get("targets") or []:
            if str(target.get("nickname") or "").strip() == requested and target.get("enabled"):
                matches.append((task, target))
    if not matches:
        raise RuntimeError(f"没有找到启用的目标好友：{requested}")
    if len(matches) > 1:
        task_names = "、".join(str(task.get("name") or task.get("id")) for task, _ in matches)
        raise RuntimeError(f"昵称“{requested}”存在于多个任务：{task_names}，请先明确任务")

    task, target = matches[0]
    if not task.get("enabled"):
        raise RuntimeError(f"好友“{requested}”所在任务已停用：{task.get('name')}")
    queued = api_request(
        "POST",
        "/api/openclaw/command",
        {"action": "task.check", "data": {"task_id": task["id"]}},
    )
    run_id = int(queued["run_id"])
    latest = wait_for_run(run_id, timeout_seconds, poll_seconds)
    run = latest.get("run") or {}
    if latest.get("terminal") or run.get("status") in TERMINAL_RUN_STATUSES:
        target_result = next(
            (
                item for item in latest.get("contacts") or []
                if int(item.get("target_id") or 0) == int(target["id"])
            ),
            None,
        )
        return {
            "status": "completed",
            "fresh_check": True,
            "nickname": requested,
            "task": {"id": task["id"], "name": task.get("name")},
            "run": run,
            "result": target_result,
            "checked_at": run.get("finished_at") or latest.get("server_time"),
        }
    return {
        "status": "waiting",
        "fresh_check": False,
        "nickname": requested,
        "task": {"id": task["id"], "name": task.get("name")},
        "run_id": run_id,
        "message": "实时检查仍在执行，不能根据旧状态作答",
        "latest": latest,
    }


def check_all_targets(timeout_seconds: int, poll_seconds: float) -> dict:
    overview = api_request("GET", "/api/openclaw/overview")
    tasks = [
        task for task in overview.get("tasks") or []
        if task.get("enabled") and any(target.get("enabled") for target in task.get("targets") or [])
    ]
    queued = api_request(
        "POST",
        "/api/openclaw/command",
        {"action": "task.check-all", "data": {}},
    )
    queued_runs = {
        int(item["task_id"]): item for item in queued.get("runs") or []
    }
    results: list[dict] = []
    for task in tasks:
        enabled_targets = [target for target in task.get("targets") or [] if target.get("enabled")]
        queued_run = queued_runs.get(int(task["id"]))
        if not queued_run:
            for target in enabled_targets:
                results.append({
                    "nickname": target.get("nickname"),
                    "task": {"id": task["id"], "name": task.get("name")},
                    "run_id": None,
                    "run_status": "not_queued",
                    "fresh_check": False,
                    "checked_at": None,
                    "result": None,
                })
            continue
        run_id = int(queued_run["run_id"])
        latest = wait_for_run(run_id, timeout_seconds, poll_seconds)
        run = latest.get("run") or {}
        contacts = latest.get("contacts") or []
        for target in enabled_targets:
            target_result = next(
                (item for item in contacts if int(item.get("target_id") or 0) == int(target["id"])),
                None,
            )
            results.append({
                "nickname": target.get("nickname"),
                "task": {"id": task["id"], "name": task.get("name")},
                "run_id": run_id,
                "run_status": run.get("status") or "waiting",
                "fresh_check": bool(latest.get("terminal")),
                "checked_at": run.get("finished_at") or latest.get("server_time"),
                "result": target_result,
            })
    answer_rows = []
    for item in results:
        target_result = item.get("result") or {}
        answer_rows.append({
            "nickname": item.get("nickname"),
            "renewal_status": target_result.get("renewal_status") or "unknown",
            "fire_days": target_result.get("fire_days"),
            "last_counterpart_at": target_result.get("last_counterpart_at"),
            "checked_at": item.get("checked_at"),
            "run_status": item.get("run_status"),
        })
    priority = {"not_renewed": 0, "unknown": 1, "renewed": 2}
    answer_rows.sort(key=lambda row: (priority.get(row["renewal_status"], 1), str(row.get("nickname") or "")))
    counts = {
        status: sum(row["renewal_status"] == status for row in answer_rows)
        for status in ("renewed", "not_renewed", "unknown")
    }
    return {
        "status": "completed" if all(item["fresh_check"] for item in results) else "partial",
        "fresh_check": bool(results) and all(item["fresh_check"] for item in results),
        "expected_count": sum(
            1 for task in tasks for target in task.get("targets") or [] if target.get("enabled")
        ),
        "returned_count": len(results),
        "counts": counts,
        "answer_rows": answer_rows,
        "results": results,
        "server_time": overview.get("server_time"),
        "batch_id": queued.get("batch_id"),
    }


def run_all_tasks(task_type: str) -> dict:
    action = "task.check-all" if task_type == "night_check" else "task.run-all"
    return api_request(
        "POST",
        "/api/openclaw/command",
        {"action": action, "data": {"task_type": task_type}},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the Douyin fire admin backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("overview")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--hours", type=int, default=24)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--task-id", type=int, required=True)
    run_parser.add_argument("--type", choices=["send", "night_check"], default="send")

    run_all_parser = subparsers.add_parser("run-all")
    run_all_parser.add_argument("--type", choices=["send", "night_check"], default="send")

    target_check_parser = subparsers.add_parser("check-target")
    target_check_parser.add_argument("--nickname", required=True)
    target_check_parser.add_argument("--timeout", type=int, default=180)
    target_check_parser.add_argument("--poll-seconds", type=float, default=2.0)

    all_targets_parser = subparsers.add_parser("check-all-targets")
    all_targets_parser.add_argument("--timeout-per-task", type=int, default=180)
    all_targets_parser.add_argument("--poll-seconds", type=float, default=2.0)

    cookie_parser = subparsers.add_parser("cookie-check")
    cookie_parser.add_argument("--account-id", type=int, required=True)
    subparsers.add_parser("cookie-check-all")

    command_parser = subparsers.add_parser("command")
    command_parser.add_argument("action")
    command_parser.add_argument("--data", default="{}", help="JSON object, @file, or @- for stdin")

    notification_parser = subparsers.add_parser("notifications")
    notification_parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    notification_parser.add_argument("--initialize", action="store_true")
    notification_parser.add_argument("--commit", action="store_true")

    args = parser.parse_args()
    if args.command == "overview":
        result = api_request("GET", "/api/openclaw/overview")
    elif args.command == "report":
        result = api_request("GET", f"/api/openclaw/report?{urlencode({'hours': args.hours})}")
    elif args.command == "run":
        action = "task.check" if args.type == "night_check" else "task.run"
        result = api_request("POST", "/api/openclaw/command", {"action": action, "data": {"task_id": args.task_id, "task_type": args.type}})
    elif args.command == "run-all":
        result = run_all_tasks(args.type)
    elif args.command == "check-target":
        result = check_target(args.nickname, args.timeout, args.poll_seconds)
    elif args.command == "check-all-targets":
        result = check_all_targets(args.timeout_per_task, args.poll_seconds)
    elif args.command == "cookie-check":
        result = api_request("POST", "/api/openclaw/command", {"action": "cookie.check", "data": {"account_id": args.account_id}})
    elif args.command == "cookie-check-all":
        result = api_request("POST", "/api/openclaw/command", {"action": "cookie.check-all", "data": {}})
    elif args.command == "command":
        result = api_request("POST", "/api/openclaw/command", {"action": args.action, "data": parse_data(args.data)})
    else:
        state = load_state(args.state_file)
        after_id = int(state.get("last_notification_id") or 0)
        result = api_request("GET", f"/api/openclaw/notifications?{urlencode({'after_id': after_id, 'limit': 200})}")
        if args.initialize:
            state["last_notification_id"] = int(result.get("latest_id") or after_id)
            save_state(args.state_file, state)
            result = {"status": "initialized", "last_notification_id": state["last_notification_id"]}
        elif not result.get("notifications"):
            result = {"status": "no_changes", "latest_id": result.get("latest_id", after_id)}
        else:
            result["status"] = "changes"
            if args.commit:
                state["last_notification_id"] = max(int(item["id"]) for item in result["notifications"])
                save_state(args.state_file, state)
                result["committed_id"] = state["last_notification_id"]

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Deliver backend batch notifications through a configured OpenClaw channel."""
from __future__ import annotations

import os
import shutil
import subprocess

from fire_admin import DEFAULT_STATE_FILE, api_request, load_state, save_state


def openclaw_command() -> str:
    configured = os.getenv("OPENCLAW_COMMAND", "").strip()
    if configured:
        return configured
    found = shutil.which("openclaw")
    if found:
        return found
    raise RuntimeError("OpenClaw command is unavailable; run scripts/setup-openclaw.sh again")


def delivery_settings() -> tuple[str, str]:
    channel = os.getenv("OPENCLAW_CHANNEL", "").strip()
    target = os.getenv("OPENCLAW_NOTIFY_TARGET", "").strip()
    if not channel or not target:
        raise RuntimeError("OPENCLAW_CHANNEL and OPENCLAW_NOTIFY_TARGET are not configured")
    return channel, target


def format_message(notifications: list[dict]) -> str:
    lines = ["抖音续火后台自动汇报"]
    for item in notifications:
        payload = item.get("payload") or {}
        if item.get("notification_type") == "cookie_status":
            current = payload.get("current") or "unknown"
            marker = "【警告】" if current in {"expired", "missing"} else "【Cookie】"
            lines.append(f"{marker}{payload.get('account_name') or payload.get('account_id')}：{current}")
            continue
        if item.get("notification_type") == "task_batch_completed":
            contacts = list(payload.get("contacts") or [])
            accounts = list(payload.get("accounts") or [])
            failed_runs = [run for run in payload.get("runs") or [] if run.get("run_status") in {"failed", "blocked", "timeout"}]
            if payload.get("task_type") == "login_check":
                priority = {"missing": 0, "expired": 1, "unknown": 2, "valid": 3}
                accounts.sort(key=lambda row: (priority.get(str(row.get("cookie_status") or "unknown"), 2), str(row.get("account_name") or "")))
                labels = {"missing": "未保存", "expired": "失效", "unknown": "未知", "valid": "有效"}
                counts = payload.get("counts") or {}
                lines.append(f"【Cookie 健康汇总】失效 {counts.get('expired', 0)}，未保存 {counts.get('missing', 0)}，未知 {counts.get('unknown', 0)}，有效 {counts.get('valid', 0)}")
                lines.extend(f"- {labels.get(str(account.get('cookie_status') or 'unknown'))}：{account.get('account_name') or account.get('account_id')}" for account in accounts)
            elif payload.get("task_type") == "night_check":
                priority = {"not_renewed": 0, "unknown": 1, "renewed": 2}
                contacts.sort(key=lambda row: (priority.get(str(row.get("renewal_status") or "unknown"), 1), str(row.get("nickname") or "")))
                labels = {"not_renewed": "未续", "unknown": "未知", "renewed": "已续"}
                counts = payload.get("counts") or {}
                lines.append(f"【晚间检查汇总】未续 {counts.get('not_renewed', 0)}，未知 {counts.get('unknown', 0)}，已续 {counts.get('renewed', 0)}")
                for contact in contacts:
                    days = contact.get("fire_days")
                    suffix = f"，火花 {days} 天" if days is not None else ""
                    lines.append(f"- {labels.get(str(contact.get('renewal_status') or 'unknown'))}：{contact.get('nickname') or '未命名'}{suffix}")
            else:
                contacts.sort(key=lambda row: (0 if str(row.get("status") or "failed") != "success" else 1, str(row.get("nickname") or "")))
                counts = payload.get("counts") or {}
                lines.append(f"【续火发送汇总】失败 {counts.get('failed', 0)}，成功 {counts.get('success', 0)}")
                lines.extend(f"- {'成功' if str(contact.get('status') or 'failed') == 'success' else '失败'}：{contact.get('nickname') or '未命名'}" for contact in contacts)
            for run in failed_runs:
                subject = run.get("task_name") or run.get("account_name") or run.get("task_id") or run.get("account_id")
                lines.append(f"- 任务异常：{subject}；{run.get('summary') or run.get('run_status')}")
            continue
        task_type = {"send": "续火发送", "night_check": "晚间检查", "login_check": "Cookie 检查"}.get(payload.get("task_type"), str(payload.get("task_type") or "任务"))
        subject = payload.get("task_name") or payload.get("account_name") or "未命名任务"
        lines.append(f"【{task_type}】{subject}：{payload.get('status') or 'unknown'}；{payload.get('summary') or item.get('message')}")
    return "\n".join(lines)


def main() -> int:
    try:
        channel, target = delivery_settings()
    except RuntimeError as exc:
        print(f"OpenClaw notifier idle: {exc}")
        return 0
    state = load_state(DEFAULT_STATE_FILE)
    after_id = int(state.get("last_notification_id") or 0)
    result = api_request("GET", f"/api/openclaw/notifications?after_id={after_id}&limit=200")
    notifications = list(result.get("notifications") or [])
    if not notifications:
        return 0
    subprocess.run([openclaw_command(), "message", "send", "--channel", channel, "--target", target, "--message", format_message(notifications), "--json"], check=True, stdout=subprocess.DEVNULL, timeout=60)
    state["last_notification_id"] = max(int(item["id"]) for item in notifications)
    save_state(DEFAULT_STATE_FILE, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

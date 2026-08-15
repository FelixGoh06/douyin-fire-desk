from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import BASE_DIR, settings
from .cookies import CookieError, encrypt_cookie_input
from .db import connect, create_event, execute, fetch_all, fetch_one, init_db, now_iso
from .runner import runner
from .scheduler import schedule_manager
from .security import (
    PasswordUpdateError,
    create_session_token,
    csrf_token,
    read_session_token,
    update_admin_password,
    verify_csrf,
    verify_password,
)
from .openclaw_api import router as openclaw_router


TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ADMIN_PASSWORD_RE = re.compile(r"^[A-Za-z0-9!%+,\-./:=?@^_~]{12,128}$")
SESSION_COOKIE = "douyin_admin_session"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    execute(
        "UPDATE task_runs SET status = 'failed', finished_at = ?, summary = ? WHERE status = 'running'",
        (now_iso(), "服务重启，任务执行中断"),
    )
    schedule_manager.start()
    yield
    schedule_manager.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan, root_path=settings.base_path)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
app.include_router(openclaw_router)
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def format_datetime(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        return value


templates.env.filters["datetime"] = format_datetime


def current_user(request: Request) -> str | None:
    return read_session_token(request.cookies.get(SESSION_COOKIE))


def require_user(request: Request) -> str:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def require_csrf(request: Request, submitted: str) -> None:
    if not verify_csrf(request.cookies.get(SESSION_COOKIE), submitted):
        raise HTTPException(status_code=403, detail="invalid csrf token")


def page_context(request: Request, *, title: str, active: str, **extra: Any) -> dict[str, Any]:
    user = require_user(request)
    session = request.cookies.get(SESSION_COOKIE, "")
    return {
        "request": request,
        "app_name": settings.app_name,
        "title": title,
        "active": active,
        "user": user,
        "csrf": csrf_token(session),
        "runner_enabled": settings.runner_enabled,
        "base_path": settings.base_path,
        **extra,
    }


def redirect(path: str, message: str | None = None) -> RedirectResponse:
    if message:
        from urllib.parse import quote

        separator = "&" if "?" in path else "?"
        path = f"{path}{separator}message={quote(message)}"
    return RedirectResponse(f"{settings.base_path}{path}", status_code=303)


def redirect_error(path: str, error: str) -> RedirectResponse:
    from urllib.parse import quote

    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{settings.base_path}{path}{separator}error={quote(error)}", status_code=303)


def validate_time(value: str, field_name: str) -> str:
    value = value.strip()
    if not TIME_RE.match(value):
        raise HTTPException(status_code=422, detail=f"{field_name} 格式必须为 HH:MM")
    return value


def parse_target_nicknames(value: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in value.replace("，", "\n").replace(",", "\n").splitlines():
        nickname = line.strip()
        if nickname and nickname not in seen:
            seen.add(nickname)
            result.append(nickname)
    return result


def account_for_view(account: dict[str, Any]) -> dict[str, Any]:
    safe = dict(account)
    safe["has_cookie"] = bool(safe.pop("cookie_ciphertext", ""))
    return safe


@app.exception_handler(401)
async def authentication_exception_handler(request: Request, _: HTTPException):
    if request.url.path.startswith("/api/") or request.url.path == "/done":
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return redirect("/login")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "scheduler": schedule_manager.scheduler.running,
        "runner_enabled": settings.runner_enabled,
        "time": now_iso(),
    }


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    if current_user(request):
        return redirect("/")
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "app_name": settings.app_name, "title": "登录", "error": error, "base_path": settings.base_path},
    )


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username != settings.admin_username or not verify_password(password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "app_name": settings.app_name, "title": "登录", "error": "账号或密码错误", "base_path": settings.base_path},
            status_code=401,
        )
    token = create_session_token(username)
    response = redirect("/")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=settings.session_secure,
        samesite="lax",
    )
    return response


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    response = redirect("/login")
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, message: str = ""):
    accounts = fetch_all(
        """
        SELECT a.*,
               (SELECT COUNT(*) FROM automation_tasks t WHERE t.account_id = a.id) AS task_count,
               (SELECT status FROM task_runs r WHERE r.account_id = a.id ORDER BY r.id DESC LIMIT 1) AS last_run_status
        FROM accounts a ORDER BY a.id
        """
    )
    recent_runs = fetch_all(
        """
        SELECT r.*, a.name AS account_name, t.name AS automation_task_name FROM task_runs r
        LEFT JOIN accounts a ON a.id = r.account_id
        LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
        ORDER BY r.id DESC LIMIT 8
        """
    )
    stats = fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM accounts) AS accounts,
          (SELECT COUNT(*) FROM accounts WHERE enabled = 1) AS enabled_accounts,
          (SELECT COUNT(*) FROM automation_tasks) AS tasks,
          (SELECT COUNT(*) FROM automation_tasks WHERE enabled = 1) AS enabled_tasks,
          (SELECT COUNT(*) FROM task_targets WHERE enabled = 1) AS targets,
          (SELECT COUNT(*) FROM task_runs WHERE date(created_at) = date('now', 'localtime')) AS today_runs,
          (SELECT COUNT(*) FROM task_runs WHERE date(created_at) = date('now', 'localtime') AND status IN ('failed','timeout')) AS today_failures
        """
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        page_context(
            request,
            title="总览",
            active="dashboard",
            accounts=accounts,
            recent_runs=recent_runs,
            stats=stats or {},
            message=message,
        ),
    )


@app.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, message: str = ""):
    accounts = fetch_all(
        """
        SELECT a.*, COUNT(t.id) AS task_count
        FROM accounts a LEFT JOIN automation_tasks t ON t.account_id = a.id
        GROUP BY a.id ORDER BY a.id
        """
    )
    return templates.TemplateResponse(
        request,
        "accounts.html",
        page_context(request, title="账号", active="accounts", accounts=accounts, message=message),
    )


@app.get("/accounts/new", response_class=HTMLResponse)
def account_new(request: Request):
    return templates.TemplateResponse(
        request,
        "account_form.html",
        page_context(request, title="添加账号", active="accounts", account=None),
    )


@app.post("/accounts")
def account_create(
    request: Request,
    csrf: str = Form(...),
    name: str = Form(...),
    timezone: str = Form("Asia/Shanghai"),
    profile_path: str = Form(""),
    cookie_value: str = Form(...),
    target_url: str = Form(...),
    notes: str = Form(""),
    enabled: str | None = Form(None),
):
    require_user(request)
    require_csrf(request, csrf)
    timestamp = now_iso()
    try:
        cookie_ciphertext, cookie_count = encrypt_cookie_input(cookie_value)
    except CookieError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        account_id = execute(
            """
            INSERT INTO accounts(
                name, enabled, timezone, profile_path, cookie_ciphertext, cookie_updated_at,
                cookie_status, target_url, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(), 1 if enabled else 0, timezone.strip(), profile_path.strip(),
                cookie_ciphertext, timestamp, "unknown", target_url.strip(), notes.strip(), timestamp, timestamp,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"账号保存失败：{exc}") from exc
    create_event(
        "account_created",
        f"已添加账号 {name.strip()}，保存 {cookie_count} 个 Cookie",
        account_id=account_id,
    )
    schedule_manager.reload()
    return redirect(f"/accounts/{account_id}", "账号已添加")


@app.get("/accounts/{account_id}", response_class=HTMLResponse)
def account_detail(request: Request, account_id: int, message: str = ""):
    account = fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    account = account_for_view(account)
    tasks = fetch_all(
        """
        SELECT t.*,
               (SELECT COUNT(*) FROM task_targets x WHERE x.task_id = t.id AND x.enabled = 1) AS target_count,
               (SELECT status FROM task_runs r WHERE r.automation_task_id = t.id ORDER BY r.id DESC LIMIT 1) AS last_run_status
        FROM automation_tasks t WHERE t.account_id = ? ORDER BY t.id
        """,
        (account_id,),
    )
    for task in tasks:
        task["next_jobs"] = schedule_manager.jobs_for_task(int(task["id"]))
    runs = fetch_all(
        """
        SELECT r.*, t.name AS automation_task_name FROM task_runs r
        LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
        WHERE r.account_id = ? ORDER BY r.id DESC LIMIT 12
        """,
        (account_id,),
    )
    return templates.TemplateResponse(
        request,
        "account_detail.html",
        page_context(
            request,
            title=account["name"],
            active="accounts",
            account=account,
            tasks=tasks,
            runs=runs,
            message=message,
        ),
    )


@app.get("/accounts/{account_id}/edit", response_class=HTMLResponse)
def account_edit(request: Request, account_id: int):
    account = fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    return templates.TemplateResponse(
        request,
        "account_form.html",
        page_context(request, title="编辑账号", active="accounts", account=account_for_view(account)),
    )


@app.post("/accounts/{account_id}")
def account_update(
    request: Request,
    account_id: int,
    csrf: str = Form(...),
    name: str = Form(...),
    timezone: str = Form(...),
    profile_path: str = Form(""),
    cookie_value: str = Form(""),
    clear_cookie: str | None = Form(None),
    target_url: str = Form(...),
    notes: str = Form(""),
    enabled: str | None = Form(None),
):
    require_user(request)
    require_csrf(request, csrf)
    cookie_ciphertext: str | None = None
    cookie_count = 0
    if cookie_value.strip():
        try:
            cookie_ciphertext, cookie_count = encrypt_cookie_input(cookie_value)
        except CookieError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    timestamp = now_iso()
    if cookie_ciphertext is not None or clear_cookie:
        execute(
            """
            UPDATE accounts SET name = ?, enabled = ?, timezone = ?, profile_path = ?,
                cookie_ciphertext = ?, cookie_updated_at = ?,
                cookie_status = ?, login_status = 'unknown', target_url = ?,
                notes = ?, updated_at = ? WHERE id = ?
            """,
            (
                name.strip(), 1 if enabled else 0, timezone.strip(),
                profile_path.strip(), cookie_ciphertext or "", timestamp,
                "unknown" if cookie_ciphertext else "missing", target_url.strip(),
                notes.strip(), timestamp, account_id,
            ),
        )
    else:
        execute(
            """
            UPDATE accounts SET name = ?, enabled = ?, timezone = ?, profile_path = ?,
                target_url = ?, notes = ?, updated_at = ? WHERE id = ?
            """,
            (
                name.strip(), 1 if enabled else 0, timezone.strip(), profile_path.strip(),
                target_url.strip(), notes.strip(), timestamp, account_id,
            ),
        )
    message = f"已更新账号 {name.strip()}"
    if cookie_ciphertext is not None:
        message += f"，更新 {cookie_count} 个 Cookie"
    elif clear_cookie:
        message += "，已清除 Cookie"
    create_event("account_updated", message, account_id=account_id)
    schedule_manager.reload()
    return redirect(f"/accounts/{account_id}", "账号设置已保存")


@app.post("/accounts/{account_id}/toggle")
def account_toggle(request: Request, account_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    execute("UPDATE accounts SET enabled = 1 - enabled, updated_at = ? WHERE id = ?", (now_iso(), account_id))
    schedule_manager.reload()
    return redirect("/accounts", "账号状态已更新")


@app.post("/accounts/{account_id}/delete")
def account_delete(request: Request, account_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    account = fetch_one("SELECT name FROM accounts WHERE id = ?", (account_id,))
    if account:
        execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        create_event("account_deleted", f"已删除账号 {account['name']}")
    schedule_manager.reload()
    return redirect("/accounts", "账号已删除")


@app.post("/accounts/{account_id}/run/{task_type}")
def account_run(request: Request, account_id: int, task_type: str, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    if task_type != "login_check":
        raise HTTPException(status_code=422, detail="未知任务类型")
    run_id = schedule_manager.enqueue_account_check(account_id, "manual")
    return redirect(f"/runs?focus={run_id}", f"任务 #{run_id} 已创建")


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, message: str = ""):
    tasks = fetch_all(
        """
        SELECT t.*, a.name AS account_name, a.login_status, a.cookie_status,
               (SELECT COUNT(*) FROM task_targets x WHERE x.task_id = t.id AND x.enabled = 1) AS target_count,
               (SELECT status FROM task_runs r WHERE r.automation_task_id = t.id ORDER BY r.id DESC LIMIT 1) AS last_run_status,
               (SELECT summary FROM task_runs r WHERE r.automation_task_id = t.id ORDER BY r.id DESC LIMIT 1) AS last_run_summary
        FROM automation_tasks t JOIN accounts a ON a.id = t.account_id
        ORDER BY t.id DESC
        """
    )
    for task in tasks:
        task["next_jobs"] = schedule_manager.jobs_for_task(int(task["id"]))
    stats = fetch_one(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled,
               (SELECT COUNT(*) FROM task_targets WHERE enabled = 1) AS targets
        FROM automation_tasks
        """
    )
    return templates.TemplateResponse(
        request,
        "tasks.html",
        page_context(
            request, title="任务管理", active="tasks", tasks=tasks,
            stats=stats or {}, message=message,
        ),
    )


@app.get("/tasks/new", response_class=HTMLResponse)
def task_new(request: Request, account_id: int | None = None):
    accounts = fetch_all("SELECT id, name, timezone FROM accounts ORDER BY id")
    return templates.TemplateResponse(
        request,
        "task_form.html",
        page_context(
            request, title="创建任务", active="tasks", task=None,
            accounts=accounts, selected_account_id=account_id,
            openclaw_configured=bool(settings.agent_api_token),
        ),
    )


@app.post("/tasks")
def task_create(
    request: Request,
    csrf: str = Form(...),
    account_id: int = Form(...),
    name: str = Form(...),
    send_time: str = Form("09:00"),
    night_check_time: str = Form("23:20"),
    timezone: str = Form("Asia/Shanghai"),
    message_template: str = Form("续火"),
    retry_count: int = Form(3),
    timeout_seconds: int = Form(300),
    target_nicknames: str = Form(""),
    notes: str = Form(""),
    enabled: str | None = Form(None),
    night_check_enabled: str | None = Form(None),
):
    require_user(request)
    require_csrf(request, csrf)
    if night_check_enabled and not settings.agent_api_token:
        raise HTTPException(status_code=422, detail="启用晚间检查前需要先配置 OpenClaw")
    send_time = validate_time(send_time, "发送时间")
    night_check_time = validate_time(night_check_time, "晚间检查时间")
    account = fetch_one("SELECT id FROM accounts WHERE id = ?", (account_id,))
    if not account:
        raise HTTPException(status_code=422, detail="账号不存在")
    timestamp = now_iso()
    try:
        task_id = execute(
            """
            INSERT INTO automation_tasks(
                account_id, name, enabled, send_time, night_check_enabled, night_check_time,
                timezone, message_template, retry_count, timeout_seconds, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id, name.strip(), 1 if enabled else 0, send_time,
                1 if night_check_enabled else 0, night_check_time, timezone.strip(),
                message_template.strip() or "续火", max(0, min(retry_count, 10)),
                max(30, min(timeout_seconds, 1800)), notes.strip(), timestamp, timestamp,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"任务保存失败：{exc}") from exc
    for nickname in parse_target_nicknames(target_nicknames):
        execute(
            """
            INSERT INTO task_targets(task_id, nickname, enabled, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (task_id, nickname, timestamp, timestamp),
        )
    create_event(
        "automation_task_created", f"已创建任务 {name.strip()}",
        account_id=account_id, automation_task_id=task_id,
    )
    schedule_manager.reload()
    return redirect(f"/tasks/{task_id}", "任务已创建")


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: int, message: str = ""):
    task = fetch_one(
        """
        SELECT t.*, a.name AS account_name, a.login_status, a.cookie_status
        FROM automation_tasks t JOIN accounts a ON a.id = t.account_id WHERE t.id = ?
        """,
        (task_id,),
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    targets = fetch_all("SELECT * FROM task_targets WHERE task_id = ? ORDER BY id", (task_id,))
    runs = fetch_all(
        "SELECT * FROM task_runs WHERE automation_task_id = ? ORDER BY id DESC LIMIT 20",
        (task_id,),
    )
    return templates.TemplateResponse(
        request,
        "task_detail.html",
        page_context(
            request, title=task["name"], active="tasks", task=task,
            targets=targets, runs=runs, next_jobs=schedule_manager.jobs_for_task(task_id),
            message=message,
        ),
    )


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit(request: Request, task_id: int):
    task = fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    accounts = fetch_all("SELECT id, name, timezone FROM accounts ORDER BY id")
    targets = fetch_all("SELECT id, nickname FROM task_targets WHERE task_id = ? ORDER BY id", (task_id,))
    return templates.TemplateResponse(
        request,
        "task_form.html",
        page_context(
            request, title="编辑任务", active="tasks", task=task,
            accounts=accounts, targets=targets, selected_account_id=task["account_id"],
            openclaw_configured=bool(settings.agent_api_token),
        ),
    )


@app.post("/tasks/{task_id}")
def task_update(
    request: Request,
    task_id: int,
    csrf: str = Form(...),
    account_id: int = Form(...),
    name: str = Form(...),
    send_time: str = Form(...),
    night_check_time: str = Form(...),
    timezone: str = Form(...),
    message_template: str = Form("续火"),
    retry_count: int = Form(3),
    timeout_seconds: int = Form(300),
    notes: str = Form(""),
    enabled: str | None = Form(None),
    night_check_enabled: str | None = Form(None),
    target_id: list[int] = Form([]),
    target_nickname: list[str] = Form([]),
):
    require_user(request)
    require_csrf(request, csrf)
    if night_check_enabled and not settings.agent_api_token:
        raise HTTPException(status_code=422, detail="启用晚间检查前需要先配置 OpenClaw")
    send_time = validate_time(send_time, "发送时间")
    night_check_time = validate_time(night_check_time, "晚间检查时间")
    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=422, detail="任务名称不能为空")
    if not fetch_one("SELECT id FROM accounts WHERE id = ?", (account_id,)):
        raise HTTPException(status_code=422, detail="执行账号不存在")
    if len(target_id) != len(target_nickname):
        raise HTTPException(status_code=422, detail="好友昵称参数不完整")

    requested_names = [nickname.strip() for nickname in target_nickname]
    if any(not nickname for nickname in requested_names):
        raise HTTPException(status_code=422, detail="好友昵称不能为空")
    if len(set(requested_names)) != len(requested_names):
        raise HTTPException(status_code=422, detail="同一任务下好友昵称不能重复")

    timestamp = now_iso()
    renamed_targets = 0
    with connect() as connection:
        task = connection.execute("SELECT id FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        existing_targets = connection.execute(
            "SELECT id, nickname FROM task_targets WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        existing_by_id = {int(target["id"]): target for target in existing_targets}
        if set(target_id) != set(existing_by_id):
            raise HTTPException(status_code=409, detail="好友配置已变化，请刷新页面后再保存")

        target_changes = [
            (target_key, nickname)
            for target_key, nickname in zip(target_id, requested_names)
            if existing_by_id[target_key]["nickname"] != nickname
        ]
        # Move changed rows aside first so renaming A to B (or swapping two names) never trips the unique key.
        for target_key, _ in target_changes:
            connection.execute(
                "UPDATE task_targets SET nickname = ?, updated_at = ? WHERE id = ?",
                (f"__renaming_{task_id}_{target_key}_{timestamp}", timestamp, target_key),
            )
        for target_key, nickname in target_changes:
            connection.execute(
                "UPDATE task_targets SET nickname = ?, updated_at = ? WHERE id = ?",
                (nickname, timestamp, target_key),
            )
        renamed_targets = len(target_changes)
        connection.execute(
            """
            UPDATE automation_tasks SET account_id = ?, name = ?, enabled = ?, send_time = ?,
                night_check_enabled = ?, night_check_time = ?, timezone = ?, message_template = ?,
                retry_count = ?, timeout_seconds = ?, notes = ?, updated_at = ? WHERE id = ?
            """,
            (
                account_id, normalized_name, 1 if enabled else 0, send_time,
                1 if night_check_enabled else 0, night_check_time, timezone.strip(),
                message_template.strip() or "续火", max(0, min(retry_count, 10)),
                max(30, min(timeout_seconds, 1800)), notes.strip(), timestamp, task_id,
            ),
        )
    create_event(
        "automation_task_updated", f"已更新任务 {normalized_name}",
        account_id=account_id, automation_task_id=task_id,
        payload={"renamed_targets": renamed_targets},
    )
    schedule_manager.reload()
    return redirect(f"/tasks/{task_id}", "任务设置已保存")


@app.post("/tasks/{task_id}/toggle")
def task_toggle(request: Request, task_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    execute("UPDATE automation_tasks SET enabled = 1 - enabled, updated_at = ? WHERE id = ?", (now_iso(), task_id))
    schedule_manager.reload()
    return redirect("/tasks", "任务状态已更新")


@app.post("/tasks/{task_id}/delete")
def task_delete(request: Request, task_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    task = fetch_one("SELECT account_id, name FROM automation_tasks WHERE id = ?", (task_id,))
    if task:
        execute("DELETE FROM automation_tasks WHERE id = ?", (task_id,))
        create_event("automation_task_deleted", f"已删除任务 {task['name']}", account_id=task["account_id"])
    schedule_manager.reload()
    return redirect("/tasks", "任务已删除")


@app.post("/tasks/{task_id}/run/{task_type}")
def task_run(request: Request, task_id: int, task_type: str, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    if task_type not in {"send", "night_check"}:
        raise HTTPException(status_code=422, detail="未知任务类型")
    run_id = schedule_manager.enqueue_task(task_id, task_type, "manual")
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"run_id": run_id, "task_type": task_type, "status": "queued"}, status_code=202)
    return redirect(f"/runs?focus={run_id}", f"执行记录 #{run_id} 已创建")


@app.get("/api/tasks/{task_id}/logs")
def task_logs(request: Request, task_id: int, after_id: int = 0):
    require_user(request)
    task = fetch_one("SELECT id FROM automation_tasks WHERE id = ?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    after_id = max(after_id, 0)
    if after_id:
        events = fetch_all(
            """
            SELECT id, event_type, severity, message, payload_json, created_at
            FROM events WHERE automation_task_id = ? AND id > ?
            ORDER BY id ASC LIMIT 200
            """,
            (task_id, after_id),
        )
    else:
        events = fetch_all(
            """
            SELECT * FROM (
                SELECT id, event_type, severity, message, payload_json, created_at
                FROM events WHERE automation_task_id = ? ORDER BY id DESC LIMIT 200
            ) ORDER BY id ASC
            """,
            (task_id,),
        )
    for event in events:
        try:
            event["payload"] = json.loads(event.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            event["payload"] = {}
    latest_run = fetch_one(
        """
        SELECT id, task_type, source, status, summary, started_at, finished_at, payload_json, created_at
        FROM task_runs WHERE automation_task_id = ? ORDER BY id DESC LIMIT 1
        """,
        (task_id,),
    )
    if latest_run:
        try:
            latest_run["payload"] = json.loads(latest_run.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            latest_run["payload"] = {}
    return {"events": events, "latest_run": latest_run, "server_time": now_iso()}


@app.post("/tasks/{task_id}/targets")
def task_target_create(
    request: Request,
    task_id: int,
    csrf: str = Form(...),
    nickname: str = Form(...),
    douyin_user_id: str = Form(""),
    message_template: str = Form(""),
    enabled: str | None = Form(None),
):
    require_user(request)
    require_csrf(request, csrf)
    timestamp = now_iso()
    execute(
        """
        INSERT INTO task_targets(
            task_id, nickname, douyin_user_id, enabled, message_template, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id, nickname) DO UPDATE SET
            douyin_user_id = excluded.douyin_user_id,
            enabled = excluded.enabled,
            message_template = excluded.message_template,
            updated_at = excluded.updated_at
        """,
        (
            task_id, nickname.strip(), douyin_user_id.strip(), 1 if enabled else 0,
            message_template.strip(), timestamp, timestamp,
        ),
    )
    return redirect(f"/tasks/{task_id}", "目标好友已保存")


@app.post("/task-targets/{target_id}/toggle")
def task_target_toggle(request: Request, target_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    target = fetch_one("SELECT task_id FROM task_targets WHERE id = ?", (target_id,))
    if not target:
        raise HTTPException(status_code=404, detail="目标好友不存在")
    execute("UPDATE task_targets SET enabled = 1 - enabled, updated_at = ? WHERE id = ?", (now_iso(), target_id))
    return redirect(f"/tasks/{target['task_id']}", "目标状态已更新")


@app.post("/task-targets/{target_id}/delete")
def task_target_delete(request: Request, target_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    target = fetch_one("SELECT task_id FROM task_targets WHERE id = ?", (target_id,))
    if target:
        execute("DELETE FROM task_targets WHERE id = ?", (target_id,))
        return redirect(f"/tasks/{target['task_id']}", "目标好友已删除")
    return redirect("/tasks")


@app.post("/accounts/{account_id}/contacts")
def contact_create(
    request: Request,
    account_id: int,
    csrf: str = Form(...),
    name: str = Form(...),
    douyin_user_id: str = Form(""),
    message_template: str = Form(""),
    enabled: str | None = Form(None),
):
    require_user(request)
    require_csrf(request, csrf)
    timestamp = now_iso()
    execute(
        """
        INSERT INTO contacts(account_id, name, douyin_user_id, enabled, message_template, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, name) DO UPDATE SET
            douyin_user_id = excluded.douyin_user_id,
            enabled = excluded.enabled,
            message_template = excluded.message_template,
            updated_at = excluded.updated_at
        """,
        (
            account_id, name.strip(), douyin_user_id.strip(), 1 if enabled else 0,
            message_template.strip(), timestamp, timestamp,
        ),
    )
    return redirect(f"/accounts/{account_id}", "好友已保存")


@app.post("/contacts/{contact_id}/toggle")
def contact_toggle(request: Request, contact_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    contact = fetch_one("SELECT account_id FROM contacts WHERE id = ?", (contact_id,))
    if not contact:
        raise HTTPException(status_code=404, detail="好友不存在")
    execute("UPDATE contacts SET enabled = 1 - enabled, updated_at = ? WHERE id = ?", (now_iso(), contact_id))
    return redirect(f"/accounts/{contact['account_id']}", "好友状态已更新")


@app.post("/contacts/{contact_id}/delete")
def contact_delete(request: Request, contact_id: int, csrf: str = Form(...)):
    require_user(request)
    require_csrf(request, csrf)
    contact = fetch_one("SELECT account_id FROM contacts WHERE id = ?", (contact_id,))
    if contact:
        execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        return redirect(f"/accounts/{contact['account_id']}", "好友已删除")
    return redirect("/accounts")


@app.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request, message: str = "", status: str = "", focus: int | None = None):
    query = """
        SELECT r.*, a.name AS account_name, t.name AS automation_task_name FROM task_runs r
        LEFT JOIN accounts a ON a.id = r.account_id
        LEFT JOIN automation_tasks t ON t.id = r.automation_task_id
    """
    params: tuple[Any, ...] = ()
    if status:
        query += " WHERE r.status = ?"
        params = (status,)
    query += " ORDER BY r.id DESC LIMIT 200"
    runs = fetch_all(query, params)
    return templates.TemplateResponse(
        request,
        "runs.html",
        page_context(
            request,
            title="任务",
            active="runs",
            runs=runs,
            filter_status=status,
            focus=focus,
            message=message,
        ),
    )


@app.get("/openclaw", response_class=HTMLResponse)
def openclaw_page(request: Request, message: str = ""):
    accounts = fetch_all(
        """
        SELECT id, name, enabled, timezone, cookie_status, last_login_check,
               cookie_check_enabled, cookie_check_time, openclaw_cookie_report_enabled,
               CASE WHEN cookie_ciphertext <> '' THEN 1 ELSE 0 END AS has_cookie
        FROM accounts ORDER BY id
        """
    )
    tasks = fetch_all(
        """
        SELECT t.*, a.name AS account_name,
               (SELECT COUNT(*) FROM task_targets x WHERE x.task_id = t.id AND x.enabled = 1) AS target_count
        FROM automation_tasks t
        JOIN accounts a ON a.id = t.account_id
        ORDER BY t.id DESC
        """
    )
    configured = bool(settings.agent_api_token)
    stats = {
        "configured": configured,
        "send_reports": sum(bool(task["openclaw_send_report_enabled"]) for task in tasks),
        "night_reports": sum(
            bool(task["night_check_enabled"] and task["openclaw_night_report_enabled"])
            for task in tasks
        ),
        "cookie_reports": sum(
            bool(account["cookie_check_enabled"] and account["openclaw_cookie_report_enabled"])
            for account in accounts
        ),
    }
    return templates.TemplateResponse(
        request,
        "openclaw.html",
        page_context(
            request,
            title="OpenClaw",
            active="openclaw",
            accounts=accounts,
            tasks=tasks,
            configured=configured,
            stats=stats,
            message=message,
        ),
    )


@app.post("/openclaw/accounts/{account_id}")
def openclaw_account_update(
    request: Request,
    account_id: int,
    csrf: str = Form(...),
    cookie_check_time: str = Form("08:45"),
    cookie_check_enabled: str | None = Form(None),
    cookie_report_enabled: str | None = Form(None),
):
    require_user(request)
    require_csrf(request, csrf)
    if not settings.agent_api_token:
        raise HTTPException(status_code=422, detail="请先完成 OpenClaw 对接")
    cookie_check_time = validate_time(cookie_check_time, "Cookie 检查时间")
    account = fetch_one("SELECT id, name FROM accounts WHERE id = ?", (account_id,))
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    execute(
        """
        UPDATE accounts
        SET cookie_check_enabled = ?, cookie_check_time = ?,
            openclaw_cookie_report_enabled = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            1 if cookie_check_enabled else 0,
            cookie_check_time,
            1 if cookie_report_enabled else 0,
            now_iso(),
            account_id,
        ),
    )
    create_event(
        "openclaw_cookie_settings_updated",
        f"已更新账号 {account['name']} 的 Cookie 健康检查设置",
        account_id=account_id,
    )
    schedule_manager.reload()
    return redirect("/openclaw", "Cookie 健康检查设置已保存")


@app.post("/openclaw/tasks/{task_id}")
def openclaw_task_update(
    request: Request,
    task_id: int,
    csrf: str = Form(...),
    send_report_enabled: str | None = Form(None),
    night_report_enabled: str | None = Form(None),
):
    require_user(request)
    require_csrf(request, csrf)
    if not settings.agent_api_token:
        raise HTTPException(status_code=422, detail="请先完成 OpenClaw 对接")
    task = fetch_one(
        """
        SELECT id, account_id, name, night_check_enabled, openclaw_night_report_enabled
        FROM automation_tasks WHERE id = ?
        """,
        (task_id,),
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    night_value = (
        1 if night_report_enabled else 0
        if task["night_check_enabled"]
        else int(task["openclaw_night_report_enabled"])
    )
    execute(
        """
        UPDATE automation_tasks
        SET openclaw_send_report_enabled = ?, openclaw_night_report_enabled = ?, updated_at = ?
        WHERE id = ?
        """,
        (1 if send_report_enabled else 0, night_value, now_iso(), task_id),
    )
    create_event(
        "openclaw_report_settings_updated",
        f"已更新任务 {task['name']} 的 OpenClaw 回复设置",
        account_id=int(task["account_id"]),
        automation_task_id=task_id,
    )
    return redirect("/openclaw", "OpenClaw 回复任务已保存")


@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request, message: str = "", error: str = ""):
    recent_events = fetch_all(
        """
        SELECT e.*, a.name AS account_name FROM events e
        LEFT JOIN accounts a ON a.id = e.account_id ORDER BY e.id DESC LIMIT 100
        """
    )
    runtime = {
        "runner_enabled": settings.runner_enabled,
        "browser_bin": settings.browser_bin or "自动检测",
        "use_xvfb": settings.use_xvfb,
        "callback_loopback": settings.callback_only_loopback,
        "database_path": str(settings.database_path),
        "timezone": settings.timezone,
        "default_password": settings.admin_password == "change-me",
        "default_secret": settings.session_secret == "development-secret-change-me",
        "openclaw_configured": bool(settings.agent_api_token),
    }
    return templates.TemplateResponse(
        request,
        "system.html",
        page_context(
            request,
            title="系统",
            active="system",
            events=recent_events,
            runtime=runtime,
            message=message,
            error=error,
        ),
    )


@app.post("/system/password")
def system_password_update(
    request: Request,
    csrf: str = Form(...),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    require_user(request)
    require_csrf(request, csrf)
    if not verify_password(current_password):
        return redirect_error("/system", "当前密码不正确")
    if new_password != confirm_password:
        return redirect_error("/system", "两次输入的新密码不一致")
    if not ADMIN_PASSWORD_RE.fullmatch(new_password):
        return redirect_error("/system", "新密码需为 12-128 位，并仅使用字母、数字或常见英文符号")
    try:
        update_admin_password(new_password)
    except PasswordUpdateError as exc:
        return redirect_error("/system", str(exc))
    create_event("admin_password_updated", "管理员密码已更新，服务正在重启", severity="warning")
    response = redirect("/login", "密码已更新，请使用新密码重新登录")
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.post("/done")
async def compatible_done(request: Request):
    client_host = request.client.host if request.client else ""
    if settings.callback_only_loopback and client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="callback only accepts loopback requests")
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {"status": "success"}
    run_id = runner.complete_active(payload)
    if not run_id:
        create_event("orphan_callback", "收到回调，但当前没有运行中的任务", severity="warning", payload=payload)
        return JSONResponse({"status": "ignored", "reason": "no active run"}, status_code=202)
    return {"status": "ok", "run_id": run_id}


def verify_agent_token(token: str | None) -> None:
    if settings.agent_api_token and token != settings.agent_api_token:
        raise HTTPException(status_code=401, detail="invalid agent token")


@app.get("/api/agent/config/{account_id}")
def agent_config(account_id: int, x_agent_token: str | None = Header(None)):
    verify_agent_token(x_agent_token)
    account = fetch_one("SELECT * FROM accounts WHERE id = ? AND enabled = 1", (account_id,))
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    automation_tasks = fetch_all(
        "SELECT * FROM automation_tasks WHERE account_id = ? AND enabled = 1 ORDER BY id",
        (account_id,),
    )
    for task in automation_tasks:
        task["targets"] = fetch_all(
            """
            SELECT id, nickname, douyin_user_id, message_template
            FROM task_targets WHERE task_id = ? AND enabled = 1 ORDER BY id
            """,
            (task["id"],),
        )
    safe_account = account_for_view(account)
    return {"account": safe_account, "tasks": automation_tasks, "server_time": now_iso()}


@app.post("/api/agent/events")
async def agent_event(request: Request, x_agent_token: str | None = Header(None)):
    verify_agent_token(x_agent_token)
    payload = await request.json()
    account_id = int(payload.get("account_id") or 0)
    event_type = str(payload.get("event_type") or "agent_event")
    status = str(payload.get("status") or "unknown")
    message = str(payload.get("message") or event_type)
    if event_type in {"auth_state", "cookie_state"} and account_id:
        allowed = {"valid", "expired", "unknown"}
        login_status = status if status in allowed else "unknown"
        execute(
            "UPDATE accounts SET login_status = ?, last_login_check = ?, updated_at = ? WHERE id = ?",
            (login_status, now_iso(), now_iso(), account_id),
        )
    create_event(
        event_type,
        message,
        severity="error" if status in {"expired", "failed"} else "info",
        account_id=account_id or None,
        payload=payload,
    )
    return {"status": "ok"}

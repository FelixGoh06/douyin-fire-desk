from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import settings
from .cookies import CookieError, decrypt_cookies


CHAT_URL = "https://www.douyin.com/chat"
SEARCH_SELECTORS = (
    'input.semi-input[placeholder="搜索"][type="text"]',
    'input.semi-input[placeholder="搜索"]',
    'input[placeholder="搜索"]',
    '.searchSearchInputinput_box input',
    '.LeftPanelHeadersearch input',
)
EDITOR_SELECTORS = (
    'div[data-slate-editor="true"][contenteditable="true"]',
    '[contenteditable="true"][role="textbox"]',
)


class DouyinExecutionError(RuntimeError):
    pass


def execute_task(
    account: dict[str, Any],
    contacts: list[dict[str, Any]],
    run_id: int,
    progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    def log(message: str, severity: str = "info", payload: dict[str, Any] | None = None) -> None:
        if progress:
            progress(message, severity, payload)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DouyinExecutionError("服务器未安装 Playwright 执行器") from exc

    cookies = decrypt_cookies(str(account.get("cookie_ciphertext") or ""))
    if not cookies:
        raise CookieError("账号尚未保存 Cookie")

    profile_value = str(account.get("profile_path") or "").strip()
    profile_path = Path(profile_value or f"/var/lib/douyin-fire-profiles/account-{account['id']}")
    profile_path.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    log("准备启动浏览器并导入 Cookie", payload={"account": account.get("account_name")})
    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {
            "headless": settings.browser_headless,
            "locale": "zh-CN",
            "timezone_id": str(account.get("timezone") or settings.timezone),
            "viewport": {"width": 1440, "height": 900},
            "args": [
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if settings.browser_bin:
            launch_options["executable_path"] = settings.browser_bin
        context = playwright.chromium.launch_persistent_context(str(profile_path), **launch_options)
        try:
            log("浏览器已启动，正在打开抖音聊天页")
            context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            target_url = str(account.get("target_url") or CHAT_URL)
            if "douyin.com" not in target_url:
                target_url = CHAT_URL
            page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
            log("聊天页已打开，正在验证 Cookie 和会话列表")
            login_evidence = _wait_for_login_evidence(page)
            if not login_evidence["authenticated"]:
                log("Cookie 验证失败，聊天页没有加载真实会话", "warning", {"login_evidence": login_evidence})
                return {
                    "status": "blocked",
                    "login_status": "expired",
                    "summary": "Cookie 已失效，或聊天页没有加载出真实会话数据",
                    "payload": {
                        "run_id": run_id,
                        "validation_version": 2,
                        "login_evidence": login_evidence,
                        "contacts": [],
                    },
                }

            log(
                f"Cookie 验证通过，已加载 {int(login_evidence['visible_conversations'])} 条可见会话",
                payload={"login_evidence": login_evidence},
            )
            if account.get("task_type") == "login_check":
                visible_count = int(login_evidence["visible_conversations"])
                evidence_text = (
                    f"已加载 {visible_count} 条可见会话"
                    if visible_count
                    else "已加载真实好友会话"
                )
                return {
                    "status": "success",
                    "login_status": "valid",
                    "summary": f"Cookie 有效，{evidence_text}",
                    "payload": {
                        "run_id": run_id,
                        "url": page.url,
                        "validation_version": 2,
                        "login_evidence": login_evidence,
                    },
                }

            if account.get("task_type") == "night_check":
                for contact in contacts:
                    nickname = str(contact["name"]).strip()
                    try:
                        log(f"正在检查好友 {nickname} 是否已续火", payload={"target_id": contact["id"], "nickname": nickname})
                        _open_chat_by_nickname(page, nickname)
                        page.wait_for_timeout(800)
                        renewal = _read_renewal_status(page, str(account.get("timezone") or settings.timezone))
                        results.append(
                            {
                                "target_id": contact["id"],
                                "nickname": nickname,
                                "status": "success",
                                **renewal,
                            }
                        )
                        result_label = {"renewed": "已续火", "not_renewed": "今天未续火", "unknown": "状态未识别"}.get(
                            str(renewal.get("renewal_status")), "状态未识别"
                        )
                        log(f"好友 {nickname} 检查完成：{result_label}", payload={"target_id": contact["id"], **renewal})
                    except Exception as exc:
                        results.append(
                            {
                                "target_id": contact["id"],
                                "nickname": nickname,
                                "status": "failed",
                                "error": str(exc)[:300],
                            }
                        )
                        _save_failure_screenshot(page, run_id, nickname)
                        log(f"好友 {nickname} 检查失败：{str(exc)[:160]}", "error", {"target_id": contact["id"]})

                checked = sum(item["status"] == "success" for item in results)
                renewed = sum(item.get("renewal_status") == "renewed" for item in results)
                not_renewed = sum(item.get("renewal_status") == "not_renewed" for item in results)
                unknown = checked - renewed - not_renewed
                failed = len(results) - checked
                status = "success" if failed == 0 else "partial" if checked else "failed"
                log(f"晚间检查完成：已续 {renewed}，未续 {not_renewed}，未知 {unknown}，失败 {failed}")
                return {
                    "status": status,
                    "login_status": "valid",
                    "summary": (
                        f"晚间检查完成：已续 {renewed}，未续 {not_renewed}，"
                        f"未知 {unknown}，失败 {failed}"
                    ),
                    "payload": {
                        "run_id": run_id,
                        "validation_version": 3,
                        "login_evidence": login_evidence,
                        "contacts": results,
                    },
                }

            for contact in contacts:
                nickname = str(contact["name"]).strip()
                message = str(contact.get("message_template") or account.get("message_template") or "续火")
                fire_days = int(contact.get("last_fire_days") or 1)
                message = message.replace("[天数]", str(fire_days))
                try:
                    log(f"正在向好友 {nickname} 发送续火消息", payload={"target_id": contact["id"], "nickname": nickname})
                    _open_chat_by_nickname(page, nickname)
                    _send_message(page, message)
                    results.append({"target_id": contact["id"], "nickname": nickname, "status": "success"})
                    log(f"好友 {nickname} 消息发送完成", payload={"target_id": contact["id"], "nickname": nickname})
                except Exception as exc:
                    results.append(
                        {
                            "target_id": contact["id"],
                            "nickname": nickname,
                            "status": "failed",
                            "error": str(exc)[:300],
                        }
                    )
                    _save_failure_screenshot(page, run_id, nickname)
                    log(f"好友 {nickname} 发送失败：{str(exc)[:160]}", "error", {"target_id": contact["id"]})

            sent = sum(item["status"] == "success" for item in results)
            failed = len(results) - sent
            status = "success" if failed == 0 else "partial" if sent else "failed"
            log(f"发送任务完成：成功 {sent}，失败 {failed}")
            return {
                "status": status,
                "login_status": "valid",
                "summary": f"发送完成：成功 {sent}，失败 {failed}",
                "payload": {
                    "run_id": run_id,
                    "validation_version": 2,
                    "login_evidence": login_evidence,
                    "sentCount": sent,
                    "failCount": failed,
                    "contacts": results,
                },
            }
        finally:
            context.close()


def _login_evidence(page: Any) -> dict[str, Any]:
    evidence = page.evaluate(
        """
        () => {
          const visible = (element) => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
          };
          const bodyText = document.body?.innerText || '';
          const search = [...document.querySelectorAll('input[placeholder="搜索"]')].find(visible);
          const wrapper = document.querySelector('.conversationConversationListwrapper');
          const creatorNames = [...document.querySelectorAll('[class*="item-header-name-"]')]
            .filter((element) => visible(element) && element.textContent.trim());
          const loginPrompt = ['扫码登录', '验证码登录', '登录后', '请登录'].some((text) => bodyText.includes(text));
          const qrVisible = [...document.querySelectorAll('[class*="qrcode"], [class*="QRCode"], [class*="login-modal"]')]
            .some(visible);
          let conversationTextLength = 0;
          let visibleConversations = 0;
          if (wrapper && visible(wrapper)) {
            conversationTextLength = (wrapper.innerText || '').trim().length;
            const rowPositions = new Set();
            for (const element of wrapper.querySelectorAll('div')) {
              if (!visible(element) || !(element.innerText || '').trim()) continue;
              const rect = element.getBoundingClientRect();
              if (rect.width < 180 || rect.height < 38 || rect.height > 130) continue;
              rowPositions.add(Math.round(rect.top / 4) * 4);
            }
            visibleConversations = rowPositions.size;
          }
          const hasConversationData = conversationTextLength >= 20 || creatorNames.length > 0;
          return {
            authenticated: !location.href.toLowerCase().includes('login') && !loginPrompt && !qrVisible && hasConversationData,
            search_visible: Boolean(search),
            conversation_text_length: conversationTextLength,
            visible_conversations: visibleConversations,
            creator_friend_count: creatorNames.length,
            login_prompt: loginPrompt,
            qr_visible: qrVisible,
          };
        }
        """
    )
    return dict(evidence)


def _wait_for_login_evidence(page: Any, timeout_seconds: int = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    evidence = _login_evidence(page)
    while not evidence["authenticated"] and time.monotonic() < deadline:
        page.wait_for_timeout(1_000)
        evidence = _login_evidence(page)
    return evidence


def _first_visible(page: Any, selectors: tuple[str, ...], timeout_ms: int = 12_000) -> Any:
    per_selector = max(500, timeout_ms // len(selectors))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=per_selector):
                return locator
        except Exception:
            continue
    return None


def _open_chat_by_nickname(page: Any, nickname: str) -> None:
    search = _first_visible(page, SEARCH_SELECTORS)
    if search is None:
        _open_creator_chat(page, nickname)
        return

    search.click()
    search.fill("")
    search.fill(nickname)
    page.wait_for_timeout(1_500)

    result_selectors = (
        '[class*="SearchPanelitem"]',
        '[class*="search-result"]',
        '[class*="SearchPanel"] [class*="item"]',
    )
    for selector in result_selectors:
        candidates = page.locator(selector).all()
        for candidate in candidates:
            try:
                text = candidate.inner_text(timeout=1_000).strip()
            except Exception:
                continue
            if nickname not in text:
                continue
            buttons = candidate.locator('div[class*="chat_btn"], button, [role="button"]').all()
            for button in buttons:
                try:
                    label = button.inner_text(timeout=500)
                    if "聊天" in label or "发消息" in label or "chat_btn" in str(button.get_attribute("class")):
                        button.click(timeout=5_000)
                        page.wait_for_timeout(1_200)
                        return
                except Exception:
                    continue
            candidate.click(timeout=5_000)
            page.wait_for_timeout(1_200)
            return
    for _ in range(4):
        for match in page.get_by_text(nickname, exact=True).all():
            try:
                if not match.is_visible(timeout=500):
                    continue
                box = match.bounding_box()
                if not box or box["x"] >= 360:
                    continue
                match.click(timeout=5_000)
                page.wait_for_timeout(1_200)
                return
            except Exception:
                continue
        page.wait_for_timeout(800)
    raise DouyinExecutionError(f"没有找到昵称为“{nickname}”的好友；请确认昵称完全一致")


def _open_creator_chat(page: Any, nickname: str) -> None:
    names = page.locator('[class*="item-header-name-"]').all()
    for name in names:
        try:
            if name.inner_text(timeout=500).strip() == nickname:
                name.click(timeout=5_000)
                page.wait_for_timeout(1_000)
                return
        except Exception:
            continue
    raise DouyinExecutionError(f"当前好友列表中没有找到“{nickname}”")


def _send_message(page: Any, message: str) -> None:
    editor = _first_visible(page, EDITOR_SELECTORS, timeout_ms=15_000)
    if editor is None:
        raise DouyinExecutionError("已进入好友会话，但没有找到消息输入框")
    editor.click()
    try:
        editor.fill(message)
    except Exception:
        page.keyboard.insert_text(message)
    page.wait_for_timeout(500)
    editor.press("Enter")
    page.wait_for_timeout(1_500)


def _save_failure_screenshot(page: Any, run_id: int, nickname: str) -> None:
    safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", nickname)[:40] or "contact"
    output_dir = settings.database_path.parent / "failures"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(output_dir / f"run-{run_id}-{safe_name}.png"), full_page=False)
    except Exception:
        pass


def _read_renewal_status(page: Any, timezone_name: str) -> dict[str, Any]:
    snapshot = page.evaluate(
        """
        () => {
          const visible = (element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
          };
          const markers = [...document.querySelectorAll('.MessageBoxTimetimeLayout')]
            .filter(visible)
            .map((element) => {
              const rect = element.getBoundingClientRect();
              return { text: (element.textContent || '').trim(), y: Math.round(rect.y) };
            });
          const messages = [...document.querySelectorAll('.messageMessageBoxmessageBox')]
            .filter(visible)
            .map((element) => {
              const rect = element.getBoundingClientRect();
              const y = Math.round(rect.y);
              const nearest = markers.reduce((best, marker) =>
                !best || Math.abs(marker.y - y) < Math.abs(best.y - y) ? marker : best, null);
              return {
                y,
                outgoing: Boolean(element.querySelector('.messageMessageBoxcontentBox.messageMessageBoxisFromMe')),
                time_label: nearest && Math.abs(nearest.y - y) <= 18 ? nearest.text : '',
              };
            })
            .sort((left, right) => left.y - right.y);
          const streaks = [...document.querySelectorAll('.commonStreaknormalText')]
            .filter(visible)
            .map((element) => {
              const rect = element.getBoundingClientRect();
              return { text: (element.textContent || '').trim(), x: Math.round(rect.x), y: Math.round(rect.y) };
            });
          const streakIcons = [...document.querySelectorAll('img.commonStreakicon')]
            .filter(visible)
            .map((element) => {
              const rect = element.getBoundingClientRect();
              return { src: element.getAttribute('src') || '', x: Math.round(rect.x), y: Math.round(rect.y) };
            });
          return { messages, streaks, streakIcons };
        }
        """
    )
    summary = _summarize_renewal_timeline(
        list(snapshot.get("messages") or []),
        timezone_name,
    )
    current_streaks = [
        str(item.get("text") or "")
        for item in snapshot.get("streaks") or []
        if int(item.get("x") or 0) >= 360 and int(item.get("y") or 0) <= 120
    ]
    for streak in current_streaks:
        match = re.search(r"(\d+)", streak)
        if match:
            summary["fire_days"] = int(match.group(1))
            break
    current_icons = [
        str(item.get("src") or "")
        for item in snapshot.get("streakIcons") or []
        if int(item.get("x") or 0) >= 360 and int(item.get("y") or 0) <= 120
    ]
    icon_src = current_icons[0] if current_icons else ""
    summary["renewal_status"] = _select_renewal_status(
        icon_src,
        str(summary["renewal_status"]),
    )
    summary["renewal_evidence"] = (
        "gray_normal_icon" if "gray_normal.png" in icon_src else "active_streak_icon" if icon_src else "message_timeline"
    )
    return summary


def _summarize_renewal_timeline(
    messages: list[dict[str, Any]],
    timezone_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:
        timezone = ZoneInfo(settings.timezone)
    current_time = now.astimezone(timezone) if now else datetime.now(timezone)
    observed_today = False
    counterpart_today = False
    active_day: bool | None = None
    latest_counterpart_at: datetime | None = None

    for message in sorted(messages, key=lambda item: int(item.get("y") or 0)):
        label = str(message.get("time_label") or "")
        if label:
            marker_time = _parse_chat_time(label, current_time)
            if marker_time:
                active_day = marker_time.date() == current_time.date()
                observed_today = observed_today or active_day
        if active_day is True and not bool(message.get("outgoing")):
            counterpart_today = True
            marker_time = _parse_chat_time(label, current_time) if label else None
            latest_counterpart_at = marker_time or latest_counterpart_at

    renewal_status = "renewed" if counterpart_today else "not_renewed" if observed_today else "unknown"
    return {
        "renewal_status": renewal_status,
        "last_counterpart_at": latest_counterpart_at.isoformat(timespec="seconds") if latest_counterpart_at else None,
        "today_window_observed": observed_today,
    }


def _parse_chat_time(label: str, now: datetime) -> datetime | None:
    normalized = re.sub(r"\s+", "", label)
    if not normalized:
        return None
    if "刚刚" in normalized:
        return now
    minutes_ago = re.search(r"(\d+)分钟前", normalized)
    if minutes_ago:
        return now - timedelta(minutes=int(minutes_ago.group(1)))
    time_match = re.search(r"(\d{1,2}):(\d{2})", normalized)
    if not time_match:
        return None
    hour, minute = (int(value) for value in time_match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    day = now.date() - timedelta(days=1) if "昨天" in normalized else now.date()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)


def _select_renewal_status(icon_src: str, timeline_status: str) -> str:
    if "gray_normal.png" in icon_src:
        return "not_renewed"
    if icon_src:
        return "renewed"
    return timeline_status

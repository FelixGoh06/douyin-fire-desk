from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


class CookieError(ValueError):
    pass


def _fernet() -> Fernet:
    configured = settings.cookie_encryption_key.strip()
    if configured:
        try:
            return Fernet(configured.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise CookieError("COOKIE_ENCRYPTION_KEY 不是有效的 Fernet 密钥") from exc
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.session_secret.encode("utf-8")).digest())
    return Fernet(derived)


def parse_cookie_input(raw: str) -> list[dict[str, Any]]:
    value = raw.strip()
    if not value:
        raise CookieError("Cookie 不能为空")

    if value[0] in "[{":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CookieError("Cookie JSON 格式不正确") from exc
        if isinstance(parsed, dict) and isinstance(parsed.get("cookies"), list):
            parsed = parsed["cookies"]
        if isinstance(parsed, dict):
            parsed = [{"name": key, "value": item} for key, item in parsed.items()]
        if not isinstance(parsed, list):
            raise CookieError("Cookie JSON 必须是数组、对象或包含 cookies 数组")
        cookies = [_normalize_cookie(item) for item in parsed if isinstance(item, dict)]
    else:
        cookies = []
        reserved = {"domain", "path", "expires", "max-age", "secure", "httponly", "samesite"}
        for part in value.replace("\r", "").replace("\n", ";").split(";"):
            name, separator, cookie_value = part.strip().partition("=")
            if separator and name and name.lower() not in reserved:
                cookies.append(_normalize_cookie({"name": name, "value": cookie_value}))

    cookies = [cookie for cookie in cookies if cookie["name"] and cookie["value"]]
    if not cookies:
        raise CookieError("没有解析到有效 Cookie")
    return cookies


def _normalize_cookie(item: dict[str, Any]) -> dict[str, Any]:
    cookie: dict[str, Any] = {
        "name": str(item.get("name") or "").strip(),
        "value": str(item.get("value") or ""),
        "domain": str(item.get("domain") or ".douyin.com").strip(),
        "path": str(item.get("path") or "/"),
        "secure": bool(item.get("secure", True)),
        "httpOnly": bool(item.get("httpOnly", False)),
    }
    same_site = str(item.get("sameSite") or item.get("same_site") or "Lax").capitalize()
    if same_site in {"Lax", "Strict", "None"}:
        cookie["sameSite"] = same_site
    expires = item.get("expires") or item.get("expirationDate")
    if expires not in (None, "", -1, 0, "0"):
        try:
            expires_value = float(expires)
            if expires_value > 0:
                cookie["expires"] = expires_value
        except (TypeError, ValueError):
            pass
    return cookie


def encrypt_cookie_input(raw: str) -> tuple[str, int]:
    cookies = parse_cookie_input(raw)
    normalized = json.dumps(cookies, ensure_ascii=False, separators=(",", ":"))
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii"), len(cookies)


def decrypt_cookies(ciphertext: str) -> list[dict[str, Any]]:
    if not ciphertext:
        return []
    try:
        decrypted = _fernet().decrypt(ciphertext.encode("ascii"))
        parsed = json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise CookieError("Cookie 解密失败，请重新录入") from exc
    if not isinstance(parsed, list):
        raise CookieError("Cookie 存储格式无效")
    return [_normalize_cookie(item) for item in parsed if isinstance(item, dict)]

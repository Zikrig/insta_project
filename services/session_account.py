"""Ник владельца сессии. Значения cookies в лог не пишутся."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from services.names import normalize_username

_APP_ID = "936619743392459"


def instagram_user_id(path: Path) -> str | None:
    cookies = _cookies(path)
    user_id = cookies.get("ds_user_id", "")
    if user_id.isdigit():
        return user_id
    return None


def read_username(path: Path) -> str | None:
    """Ник по ds_user_id из файла сессии. Запрос только на instagram.com."""
    cookies = _cookies(path)
    user_id = cookies.get("ds_user_id", "")
    if not user_id.isdigit():
        return None
    header = "; ".join(f"{name}={value}" for name, value in cookies.items())
    request = urllib.request.Request(
        f"https://www.instagram.com/api/v1/users/{user_id}/info/",
        headers={
            "User-Agent": "Mozilla/5.0",
            "X-IG-App-ID": _APP_ID,
            "X-CSRFToken": cookies.get("csrftoken", ""),
            "Referer": "https://www.instagram.com/",
            "Cookie": header,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, ValueError):
        return None
    user = payload.get("user") if isinstance(payload, dict) else None
    username = user.get("username") if isinstance(user, dict) else None
    if not isinstance(username, str):
        return None
    return normalize_username(username)


def _cookies(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    found: dict[str, str] = {}
    for cookie in payload.get("cookies") or []:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain") or "")
        if "instagram.com" not in domain:
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if isinstance(name, str) and isinstance(value, str) and value:
            found[name] = value
    return found

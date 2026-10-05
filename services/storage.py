"""Проверка файла сессии Playwright. Значения cookies не логируются и не возвращаются."""

from __future__ import annotations

import json
from pathlib import Path


def validate_storage_state(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Файл сессии не является JSON.") from exc
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(cookies, list) or not cookies:
        raise ValueError("В файле нет cookies. Нужен storage_state, который сохраняет Playwright.")
    names = {item.get("name") for item in cookies if isinstance(item, dict)}
    if "sessionid" not in names:
        raise ValueError("В сессии нет cookie sessionid. Войдите в аккаунт и сохраните файл снова.")

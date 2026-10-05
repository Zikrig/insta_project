"""Тексты причин остановки. В них нет данных аккаунта."""

from __future__ import annotations

REASON_TEXT = {
    "stopped_by_admin": "остановлено администратором",
    "rate_limited": "ограничение Instagram (Try Again Later или похожее)",
    "session_invalid": "сессия недействительна",
    "daily_limit": "достигнут дневной лимит",
    "finished": "список обработан",
    "test_limit": "достигнут лимит тестового прогона (20)",
    "error": "ошибка прогона",
    "ui_changed": "не найдена форма подписчиков на сайте",
}

STATUS_RU = {
    "removed": "удалён",
    "not_found": "не найден",
    "error": "ошибка",
}


def reason_text(reason: str) -> str:
    return REASON_TEXT.get(reason, reason)


def safe_detail(exc: BaseException) -> str:
    """Короткий текст ошибки без cookies и без кусков страницы."""
    text = str(exc).replace("\n", " ").strip()
    lowered = text.lower()
    if "sessionid" in lowered or "cookie" in lowered or "set-cookie" in lowered:
        return type(exc).__name__
    return text[:200] or type(exc).__name__

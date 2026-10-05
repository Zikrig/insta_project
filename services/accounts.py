"""Строка с никами профилей для главного меню."""

from __future__ import annotations

from services import db


async def accounts_text() -> str:
    profiles = await db.list_profiles()
    if not profiles:
        return "Профилей нет."
    lines = []
    for profile in profiles:
        if profile.ig_username:
            lines.append(f"{profile.name}: @{profile.ig_username}")
        else:
            lines.append(f"{profile.name}: ник не задан")
    return "\n".join(lines)

"""Сохранить ник из сессии в профиль и собрать строку для меню."""

from __future__ import annotations

import asyncio
from pathlib import Path

from services import db
from services.db import Profile
from services.session_account import read_username


async def remember_username(profile: Profile) -> Profile:
    if profile.ig_username or not profile.session_path:
        return profile
    path = Path(profile.session_path)
    if not path.is_file():
        return profile
    username = await asyncio.to_thread(read_username, path)
    if not username:
        return profile
    await db.update_field(profile.id, "ig_username", username)
    updated = await db.get_profile(profile.id)
    return updated or profile


async def remember_all() -> None:
    for profile in await db.list_profiles():
        await remember_username(profile)


async def accounts_text() -> str:
    profiles = await db.list_profiles()
    if not profiles:
        return "Сессий нет."
    lines = []
    for profile in profiles:
        if profile.ig_username:
            lines.append(f"{profile.name}: @{profile.ig_username}")
        else:
            lines.append(f"{profile.name}: ник из сессии пока не прочитан")
    return "\n".join(lines)

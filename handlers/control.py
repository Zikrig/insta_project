"""Запуск, остановка и тестовый прогон на 20 ников."""

from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from handlers.keyboards import choice_kb
from services import db
from services.accounts import remember_username
from services.db import Profile
from services.runner import runner

router = Router(name="control")
TEST_LIMIT = 20


async def ask_start(message: Message, *, test: bool) -> None:
    profiles = await db.list_profiles()
    if not profiles:
        await message.answer("Сначала загрузите сессию.")
        return
    prefix = "test" if test else "run"
    if len(profiles) == 1:
        await launch(message, profiles[0], test=test)
        return
    title = "Выберите профиль для теста на 20 ников." if test else "Выберите профиль."
    await message.answer(
        title,
        reply_markup=choice_kb([(item.name, f"{prefix}:{item.id}") for item in profiles]),
    )


async def ask_power(message: Message) -> None:
    if runner.running():
        await ask_stop(message)
        return
    await ask_start(message, test=False)


async def ask_stop(message: Message) -> None:
    if not runner.running():
        await message.answer("Прогон не выполняется.")
        return
    note = await message.answer("Останавливаю прогон.")
    await runner.stop()
    try:
        await note.edit_text("Прогон остановлен.")
    except Exception:
        await message.answer("Прогон остановлен.")
    await _refresh(message)


@router.callback_query(F.data.startswith("run:") | F.data.startswith("test:"))
async def on_launch(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None or not query.data:
        return
    test = query.data.startswith("test:")
    profile = await _profile(query.data)
    if profile is None:
        await query.message.answer("Профиль не найден.")
        return
    await launch(query.message, profile, test=test)


async def launch(message: Message, profile: Profile, *, test: bool) -> None:
    profile = await remember_username(profile)
    missing = _missing(profile)
    if missing:
        await message.answer(f"У профиля «{profile.name}» не хватает: {', '.join(missing)}.")
        return
    try:
        await runner.start(
            profile,
            test_limit=TEST_LIMIT if test else None,
            bot=message.bot,
        )
    except RuntimeError as exc:
        await message.answer(str(exc))
        return
    label = "Тестовый прогон на 20 ников" if test else "Прогон"
    await message.answer(f"{label} «{profile.name}» запущен.")
    await _refresh(message)


def _missing(profile: Profile) -> list[str]:
    missing: list[str] = []
    if not profile.session_path or not Path(profile.session_path).is_file():
        missing.append("сессию")
    if not profile.list_path or not Path(profile.list_path).is_file() or profile.list_count <= 0:
        missing.append("список")
    if not profile.ig_username:
        missing.append("ник Instagram (не прочитался из сессии, задайте в «Параметры»)")
    return missing


async def _refresh(message: Message) -> None:
    from handlers.menu import refresh_open_menu

    await refresh_open_menu(message.bot, message.chat.id)


async def _profile(data: str) -> Profile | None:
    _, _, raw_id = data.partition(":")
    if not raw_id.isdigit():
        return None
    return await db.get_profile(int(raw_id))

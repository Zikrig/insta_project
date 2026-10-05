"""Инлайн-кнопки администратора. Ответ не-админу их не показывает."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BTN_SESSION = "Загрузить сессию"
BTN_LIST = "Загрузить список"
BTN_PARAMS = "Параметры"
BTN_PROFILES = "Профили"
BTN_TEST = "Тест 20"


def menu_rows(running: bool | None = None) -> list[list[InlineKeyboardButton]]:
    active = _running() if running is None else running
    power = "🟢 Остановить" if active else "🔴 Запустить"
    return [
        [
            InlineKeyboardButton(text=BTN_SESSION, callback_data="m:session"),
            InlineKeyboardButton(text=BTN_LIST, callback_data="m:list"),
        ],
        [
            InlineKeyboardButton(text=BTN_PARAMS, callback_data="m:params"),
            InlineKeyboardButton(text=BTN_PROFILES, callback_data="m:profiles"),
        ],
        [InlineKeyboardButton(text=power, callback_data="m:power")],
        [InlineKeyboardButton(text=BTN_TEST, callback_data="m:test")],
    ]


def admin_kb(running: bool | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=menu_rows(running))


def _running() -> bool:
    from services.runner import runner

    return runner.running()


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="m:back")]]
    )


def profile_actions_kb(profile_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data=f"rmyes:{profile_id}")],
            [InlineKeyboardButton(text="Назад", callback_data="m:profiles")],
        ]
    )


def choice_kb(pairs: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=data)] for title, data in pairs]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="m:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

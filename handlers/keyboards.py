"""Инлайн-кнопки администратора. Ответ не-админу их не показывает."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BTN_SESSION = "Загрузить сессию"
BTN_LIST = "Загрузить список"
BTN_PARAMS = "Параметры"
BTN_START = "Запустить"
BTN_STOP = "Остановить"
BTN_STATUS = "Статус"
BTN_TEST = "Тест 20"


def menu_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(text=BTN_SESSION, callback_data="m:session"),
            InlineKeyboardButton(text=BTN_LIST, callback_data="m:list"),
        ],
        [
            InlineKeyboardButton(text=BTN_PARAMS, callback_data="m:params"),
            InlineKeyboardButton(text=BTN_STATUS, callback_data="m:status"),
        ],
        [
            InlineKeyboardButton(text=BTN_START, callback_data="m:start"),
            InlineKeyboardButton(text=BTN_STOP, callback_data="m:stop"),
        ],
        [InlineKeyboardButton(text=BTN_TEST, callback_data="m:test")],
    ]


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=menu_rows())


def choice_kb(pairs: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=data)] for title, data in pairs]
    rows.extend(menu_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)

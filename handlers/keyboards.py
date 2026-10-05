"""Клавиатура администратора. Ответ не-админу её не показывает."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

BTN_SESSION = "Загрузить сессию"
BTN_LIST = "Загрузить список"
BTN_PARAMS = "Параметры"
BTN_START = "Запустить"
BTN_STOP = "Остановить"
BTN_STATUS = "Статус"
BTN_TEST = "Тест 20"

MENU_BUTTONS = (
    BTN_SESSION,
    BTN_LIST,
    BTN_PARAMS,
    BTN_START,
    BTN_STOP,
    BTN_STATUS,
    BTN_TEST,
)


def admin_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_SESSION), KeyboardButton(text=BTN_LIST)],
        [KeyboardButton(text=BTN_PARAMS), KeyboardButton(text=BTN_STATUS)],
        [KeyboardButton(text=BTN_START), KeyboardButton(text=BTN_STOP)],
        [KeyboardButton(text=BTN_TEST)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def choice_kb(pairs: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=data)] for title, data in pairs
        ]
    )

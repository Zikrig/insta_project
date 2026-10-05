"""Кнопки меню. Роутер подключается первым, чтобы кнопка прерывала незавершённый ввод."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.control import ask_start, ask_status, ask_stop
from handlers.keyboards import (
    BTN_LIST,
    BTN_PARAMS,
    BTN_SESSION,
    BTN_START,
    BTN_STATUS,
    BTN_STOP,
    BTN_TEST,
    admin_kb,
)
from handlers.profiles import prompt_list, prompt_params, prompt_session

router = Router(name="menu")

WELCOME = (
    "Меню администратора.\n\n"
    "Загрузить сессию — JSON после входа через scripts/login_session.py.\n"
    "Загрузить список — Excel с никами.\n"
    "Параметры — username, паузы, перерыв и дневной лимит.\n"
    "Запустить / Остановить — снятие подписчиков.\n"
    "Тест 20 — тот же прогон, но только 20 ещё не обработанных ников.\n"
    "Статус — что происходит сейчас.\n\n"
    "Логин и пароль Instagram бот не спрашивает."
)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=admin_kb())


@router.message(F.text == BTN_SESSION)
async def session_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await prompt_session(message, state)


@router.message(F.text == BTN_LIST)
async def list_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await prompt_list(message, state)


@router.message(F.text == BTN_PARAMS)
async def params_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await prompt_params(message, state)


@router.message(F.text == BTN_START)
async def start_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ask_start(message, test=False)


@router.message(F.text == BTN_TEST)
async def test_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ask_start(message, test=True)


@router.message(F.text == BTN_STOP)
async def stop_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ask_stop(message)


@router.message(F.text == BTN_STATUS)
async def status_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ask_status(message)

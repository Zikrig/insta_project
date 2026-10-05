"""Инлайн-меню. Нажатие прерывает незавершённый ввод."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from handlers.control import ask_start, ask_status, ask_stop
from handlers.keyboards import admin_kb
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
    await _show(message, WELCOME, clear_reply=True)


@router.callback_query(F.data == "m:session")
async def session_button(query: CallbackQuery, state: FSMContext) -> None:
    await _open(query, state, prompt_session)


@router.callback_query(F.data == "m:list")
async def list_button(query: CallbackQuery, state: FSMContext) -> None:
    await _open(query, state, prompt_list)


@router.callback_query(F.data == "m:params")
async def params_button(query: CallbackQuery, state: FSMContext) -> None:
    await _open(query, state, prompt_params)


@router.callback_query(F.data == "m:start")
async def start_button(query: CallbackQuery, state: FSMContext) -> None:
    await _run(query, state, test=False)


@router.callback_query(F.data == "m:test")
async def test_button(query: CallbackQuery, state: FSMContext) -> None:
    await _run(query, state, test=True)


@router.callback_query(F.data == "m:stop")
async def stop_button(query: CallbackQuery, state: FSMContext) -> None:
    message = await _prepare(query, state)
    if message is None:
        return
    await ask_stop(message)


@router.callback_query(F.data == "m:status")
async def status_button(query: CallbackQuery, state: FSMContext) -> None:
    message = await _prepare(query, state)
    if message is None:
        return
    await ask_status(message)


async def _show(message: Message, text: str, *, clear_reply: bool = False) -> None:
    if not clear_reply:
        await message.answer(text, reply_markup=admin_kb())
        return
    # Старую клавиатуру под полем ввода снимаем, кнопки остаются у сообщения.
    sent = await message.answer(text, reply_markup=ReplyKeyboardRemove())
    await sent.edit_reply_markup(reply_markup=admin_kb())


async def _prepare(query: CallbackQuery, state: FSMContext) -> Message | None:
    await query.answer()
    await state.clear()
    message = query.message
    if not isinstance(message, Message):
        return None
    return message


async def _open(query: CallbackQuery, state: FSMContext, action) -> None:
    message = await _prepare(query, state)
    if message is None:
        return
    await action(message, state)


async def _run(query: CallbackQuery, state: FSMContext, *, test: bool) -> None:
    message = await _prepare(query, state)
    if message is None:
        return
    await ask_start(message, test=test)

"""Инлайн-меню. Нажатие прерывает незавершённый ввод."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from handlers.control import ask_power, ask_start
from services.accounts import accounts_text
from handlers.keyboards import admin_kb
from handlers.profiles import prompt_list, prompt_params, prompt_profiles, prompt_session

router = Router(name="menu")
_menu_ids: dict[int, int] = {}

WELCOME = (
    "Меню администратора.\n\n"
    "Загрузить сессию — имя профиля, ник Instagram и JSON после scripts/login_session.py.\n"
    "Загрузить список — Excel с никами.\n"
    "Параметры — паузы, перерыв и дневной лимит.\n"
    "Профили — выбрать профиль, затем удалить его или вернуться назад.\n"
    "Запустить / Остановить — одна кнопка. Красная «Запустить», пока стоит. Зелёная «Остановить», пока идёт.\n"
    "Тест 20 — тот же прогон, но только 20 ещё не обработанных ников.\n\n"
    "Логин и пароль Instagram бот не спрашивает."
)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_menu(message, WELCOME)


@router.callback_query(F.data == "m:back")
async def back_button(query: CallbackQuery, state: FSMContext) -> None:
    message = await _prepare(query, state)
    if message is None:
        return
    await show_menu(message, "Меню администратора.")


@router.callback_query(F.data == "m:session")
async def session_button(query: CallbackQuery, state: FSMContext) -> None:
    await _open(query, state, prompt_session)


@router.callback_query(F.data == "m:list")
async def list_button(query: CallbackQuery, state: FSMContext) -> None:
    await _open(query, state, prompt_list)


@router.callback_query(F.data == "m:params")
async def params_button(query: CallbackQuery, state: FSMContext) -> None:
    await _open(query, state, prompt_params)


@router.callback_query(F.data == "m:profiles")
async def profiles_button(query: CallbackQuery, state: FSMContext) -> None:
    await _open(query, state, prompt_profiles)


@router.callback_query(F.data == "m:power")
async def power_button(query: CallbackQuery, state: FSMContext) -> None:
    message = await _prepare(query, state)
    if message is None:
        return
    await ask_power(message)


@router.callback_query(F.data == "m:test")
async def test_button(query: CallbackQuery, state: FSMContext) -> None:
    await _run(query, state, test=True)


async def show_menu(message: Message, text: str) -> None:
    """Инлайн-кнопки сразу в новом сообщении.

    Сообщение со снятием нижней клавиатуры Telegram править нельзя,
    поэтому меню и снятие клавиатуры — два разных сообщения.
    """
    body = f"{text}\n\n{await accounts_text()}"
    sent = await message.answer(body, reply_markup=admin_kb())
    await _keep_one_menu(sent)
    cleaner = await message.answer("\u2060", reply_markup=ReplyKeyboardRemove())
    try:
        await cleaner.delete()
    except Exception:
        return


async def refresh_open_menu(bot, chat_id: int, *, running: bool | None = None) -> None:
    """Обновить цвет кнопки запуска на последнем меню, не присылая его заново."""
    message_id = _menu_ids.get(chat_id)
    if message_id is None:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=admin_kb(running=running),
        )
    except Exception:
        return


async def _keep_one_menu(sent: Message) -> None:
    chat_id = sent.chat.id
    previous = _menu_ids.get(chat_id)
    _menu_ids[chat_id] = sent.message_id
    if previous is None or previous == sent.message_id:
        return
    try:
        await sent.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=previous,
            reply_markup=None,
        )
    except Exception:
        return


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

"""Загрузка сессии, списка и правка параметров профиля."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import get_settings
from handlers.keyboards import back_kb, choice_kb
from services import db
from services.db import Profile
from services.excel_io import read_list
from services.names import LIST_ID, LIST_NICK, normalize_username, safe_profile_name
from services.accounts import remember_username
from services.storage import validate_storage_state

logger = logging.getLogger("remover")
router = Router(name="profiles")

PARAM_FIELDS = (
    ("ig_username", "Username Instagram"),
    ("pause_min", "Пауза от, секунд"),
    ("pause_max", "Пауза до, секунд"),
    ("break_every_min", "Перерыв каждые, от"),
    ("break_every_max", "Перерыв каждые, до"),
    ("break_minutes", "Длительность перерыва, мин"),
    ("daily_limit", "Дневной лимит"),
)
_FIELD_LABELS = dict(PARAM_FIELDS)


class SessionUpload(StatesGroup):
    name = State()
    file = State()


class ListUpload(StatesGroup):
    file = State()


class ParamsEdit(StatesGroup):
    value = State()


def format_profile(profile: Profile) -> str:
    session = "загружена" if profile.session_path else "нет"
    unit = "id" if profile.list_kind == LIST_ID else "ников"
    listing = f"{profile.list_count} {unit}" if profile.list_count else "нет"
    instagram = profile.ig_username or "не задан"
    mode = "id" if profile.list_kind == LIST_ID else "ники"
    return (
        f"Профиль {profile.name}\n"
        f"Сессия: {session}\n"
        f"Список: {listing}\n"
        f"В файле: {mode}\n"
        f"Instagram: {instagram}\n"
        f"Пауза: {_num(profile.pause_min)}–{_num(profile.pause_max)} секунд\n"
        f"Длинный перерыв: каждые {profile.break_every_min}–{profile.break_every_max} "
        f"удалений, {_num(profile.break_minutes)} мин\n"
        f"Дневной лимит: {profile.daily_limit}"
    )


def parse_field(field: str, raw: str, profile: Profile) -> str | int | float:
    text = raw.strip().replace(",", ".")
    if field == "ig_username":
        username = normalize_username(text)
        if username is None:
            raise ValueError("Username: латиница, цифры, точка и _, до 30 символов.")
        return username
    if field in {"pause_min", "pause_max", "break_every_min", "break_every_max", "daily_limit"}:
        if not text.isdigit():
            if field in {"pause_min", "pause_max"}:
                raise ValueError("Нужно одно целое число секунд, например 20.")
            raise ValueError("Нужно целое число.")
        value: int | float = int(text)
    else:
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError("Нужно число.") from exc

    pause_min = value if field == "pause_min" else profile.pause_min
    pause_max = value if field == "pause_max" else profile.pause_max
    every_min = int(value) if field == "break_every_min" else profile.break_every_min
    every_max = int(value) if field == "break_every_max" else profile.break_every_max
    if field in {"pause_min", "pause_max"} and (
        pause_min < 5 or pause_max > 300 or pause_min > pause_max
    ):
        raise ValueError("Пауза: одно число от 5 до 300 секунд. «От» не больше «до».")
    if field in {"break_every_min", "break_every_max"} and (
        every_min < 1 or every_max > 500 or every_min > every_max
    ):
        raise ValueError("Интервал перерыва: целые числа от 1 до 500, «от» не больше «до».")
    if field == "break_minutes" and not 1 <= float(value) <= 240:
        raise ValueError("Длительность перерыва: от 1 до 240 минут.")
    if field == "daily_limit" and not 1 <= int(value) <= 10000:
        raise ValueError("Дневной лимит: целое число от 1 до 10000.")
    return value


async def prompt_session(message: Message, state: FSMContext) -> None:
    await state.set_state(SessionUpload.name)
    await message.answer(
        "Введите имя профиля: буквы, цифры, _ и -, до 40 символов.",
        reply_markup=back_kb(),
    )


async def prompt_list(message: Message, state: FSMContext) -> None:
    profiles = await db.list_profiles()
    if not profiles:
        await message.answer("Сначала загрузите сессию.", reply_markup=back_kb())
        return
    if len(profiles) == 1:
        await _ask_excel(message, state, profiles[0])
        return
    await message.answer(
        "Выберите профиль для списка.",
        reply_markup=choice_kb([(item.name, f"list:{item.id}") for item in profiles]),
    )


async def prompt_params(message: Message, state: FSMContext) -> None:
    profiles = await db.list_profiles()
    if not profiles:
        await message.answer("Сначала загрузите сессию.", reply_markup=back_kb())
        return
    if len(profiles) == 1:
        await _show_params(message, profiles[0])
        return
    await message.answer(
        "Выберите профиль.",
        reply_markup=choice_kb([(item.name, f"param:{item.id}") for item in profiles]),
    )


@router.message(SessionUpload.name, F.text)
async def session_name(message: Message, state: FSMContext) -> None:
    try:
        name = safe_profile_name(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=back_kb())
        return
    await state.update_data(profile_name=name)
    await state.set_state(SessionUpload.file)
    await message.answer(
        "Пришлите файл сессии .json (storage_state Playwright).",
        reply_markup=back_kb(),
    )


@router.message(SessionUpload.name)
async def session_name_other(message: Message) -> None:
    await message.answer("Имя профиля нужно отправить текстом.", reply_markup=back_kb())


@router.message(SessionUpload.file, F.document)
async def session_file(message: Message, state: FSMContext) -> None:
    document = message.document
    if document is None:
        return
    filename = (document.file_name or "").lower()
    if not filename.endswith(".json"):
        await message.answer("Нужен файл с расширением .json.", reply_markup=back_kb())
        return
    if document.file_size and document.file_size > 1_048_576:
        await message.answer("Файл сессии больше 1 МБ. Это не storage_state.", reply_markup=back_kb())
        return
    data = await state.get_data()
    name = str(data["profile_name"])
    destination = (get_settings().sessions_dir / f"{name}.json").resolve()
    try:
        await _download(message, destination, validate_storage_state)
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=back_kb())
        return
    except Exception as exc:
        # В тексте ошибки Telegram бывает URL с токеном бота — в лог пишем только тип.
        logger.error("сессия не сохранена: %s", type(exc).__name__)
        await message.answer("Не удалось сохранить сессию. Пришлите файл ещё раз.", reply_markup=back_kb())
        return
    profile = await remember_username(await db.save_session(name, str(destination)))
    await state.clear()
    from handlers.menu import show_menu

    await show_menu(
        message,
        f"Сессия профиля «{profile.name}» сохранена.\n{format_profile(profile)}",
    )


@router.message(SessionUpload.file)
async def session_file_other(message: Message) -> None:
    await message.answer("Пришлите сессию документом .json.", reply_markup=back_kb())


@router.callback_query(F.data.startswith("list:"))
async def pick_list(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    profile = await _profile_from_callback(query.data or "")
    if profile is None or query.message is None:
        return
    await _ask_excel(query.message, state, profile)


@router.message(ListUpload.file, F.document)
async def list_file(message: Message, state: FSMContext) -> None:
    document = message.document
    if document is None:
        return
    filename = (document.file_name or "").lower()
    if not filename.endswith(".xlsx"):
        await message.answer("Нужен файл .xlsx.", reply_markup=back_kb())
        return
    if document.file_size and document.file_size > 20 * 1024 * 1024:
        await message.answer("Файл больше 20 МБ, Telegram его не отдаст боту.", reply_markup=back_kb())
        return
    data = await state.get_data()
    profile = await db.get_profile(int(data["profile_id"]))
    if profile is None:
        await state.clear()
        await message.answer("Профиль не найден.", reply_markup=back_kb())
        return
    destination = (get_settings().lists_dir / f"{profile.name}.xlsx").resolve()
    try:
        kind = profile.list_kind
        count, skipped = await _download(
            message,
            destination,
            lambda path, current=kind: _checked_workbook(path, current),
        )
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=back_kb())
        return
    except Exception as exc:
        logger.error("список не сохранён: %s", type(exc).__name__)
        await message.answer("Не удалось сохранить список. Пришлите файл ещё раз.", reply_markup=back_kb())
        return
    await db.save_list(profile.id, str(destination), count)
    await state.clear()
    mode = "id" if profile.list_kind == LIST_ID else "ники"
    from handlers.menu import show_menu

    await show_menu(
        message,
        f"Список «{profile.name}» сохранён. Записей: {count} (режим: {mode}). "
        f"Пропущено некорректных ячеек: {skipped}.",
    )


@router.message(ListUpload.file)
async def list_file_other(message: Message) -> None:
    await message.answer("Пришлите список документом .xlsx.", reply_markup=back_kb())


@router.callback_query(F.data.startswith("kind:"))
async def toggle_kind(query: CallbackQuery) -> None:
    await query.answer()
    if query.message is None:
        return
    profile = await _profile_from_callback(query.data or "")
    if profile is None:
        await query.message.answer("Профиль не найден.", reply_markup=back_kb())
        return
    kind = LIST_NICK if profile.list_kind == LIST_ID else LIST_ID
    await db.update_field(profile.id, "list_kind", kind)
    note = await _recount_list(profile, kind)
    updated = await db.get_profile(profile.id)
    if updated is None:
        await query.message.answer("Профиль не найден.", reply_markup=back_kb())
        return
    if note:
        await query.message.answer(note)
    await _show_params(query.message, updated)


@router.callback_query(F.data.startswith("param:"))
async def pick_params(query: CallbackQuery) -> None:
    await query.answer()
    profile = await _profile_from_callback(query.data or "")
    if profile is None or query.message is None:
        return
    await _show_params(query.message, profile)


@router.callback_query(F.data.startswith("pf:"))
async def edit_field(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or query.message is None:
        return
    field = parts[2]
    if field not in _FIELD_LABELS:
        return
    profile = await db.get_profile(int(parts[1]))
    if profile is None:
        await query.message.answer("Профиль не найден.", reply_markup=back_kb())
        return
    await state.set_state(ParamsEdit.value)
    await state.update_data(profile_id=profile.id, field=field)
    await query.message.answer(
        _field_prompt(field, profile),
        reply_markup=back_kb(),
    )


@router.message(ParamsEdit.value, F.text)
async def save_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = await db.get_profile(int(data["profile_id"]))
    field = str(data.get("field", ""))
    if profile is None or field not in _FIELD_LABELS:
        await state.clear()
        await message.answer("Настройка устарела. Откройте параметры снова.", reply_markup=back_kb())
        return
    try:
        value = parse_field(field, message.text or "", profile)
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=back_kb())
        return
    await db.update_field(profile.id, field, value)
    await state.clear()
    updated = await db.get_profile(profile.id)
    if updated is None:
        await message.answer("Профиль не найден.", reply_markup=back_kb())
        return
    await _show_params(message, updated)


@router.message(ParamsEdit.value)
async def save_value_other(message: Message) -> None:
    await message.answer("Значение нужно отправить текстом.", reply_markup=back_kb())


async def _ask_excel(message: Message, state: FSMContext, profile: Profile) -> None:
    await state.set_state(ListUpload.file)
    await state.update_data(profile_id=profile.id)
    values = "числовые id" if profile.list_kind == LIST_ID else "ники"
    await message.answer(
        f"Пришлите .xlsx для профиля «{profile.name}». "
        f"Первый столбец, со второй строки: {values}. "
        "Режим переключается кнопкой в «Параметры».",
        reply_markup=back_kb(),
    )


async def _show_params(message: Message, profile: Profile) -> None:
    kind_label = "В файле: id" if profile.list_kind == LIST_ID else "В файле: ники"
    await message.answer(
        f"{format_profile(profile)}\n\nЧто изменить?",
        reply_markup=choice_kb(
            [(kind_label, f"kind:{profile.id}")]
            + [(label, f"pf:{profile.id}:{field}") for field, label in PARAM_FIELDS]
        ),
    )


async def _recount_list(profile: Profile, kind: str) -> str:
    if not profile.list_path or not Path(profile.list_path).is_file():
        return ""
    try:
        items, skipped = await asyncio.to_thread(read_list, Path(profile.list_path), kind)
    except Exception as exc:
        logger.error("список не перечитан: %s", type(exc).__name__)
        return "Режим сохранён, но файл списка не удалось перечитать."
    await db.save_list(profile.id, profile.list_path, len(items))
    mode = "id" if kind == LIST_ID else "ники"
    if not items:
        return f"Режим «{mode}» включён. В первом столбце со второй строки подходящих значений нет."
    return f"Режим «{mode}» включён. Подошло строк: {len(items)}, пропущено: {skipped}."


async def _profile_from_callback(data: str) -> Profile | None:
    _, _, raw_id = data.partition(":")
    if not raw_id.isdigit():
        return None
    return await db.get_profile(int(raw_id))


async def _download(message: Message, destination: Path, validator):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Суффикс .part отрезает .xlsx, и openpyxl отказывается открывать файл.
    temporary = destination.with_name(f"{destination.stem}.upload{destination.suffix}")
    try:
        await message.bot.download(message.document, destination=temporary, timeout=120)
        result = await asyncio.to_thread(validator, temporary)
        temporary.replace(destination)
        return result
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _checked_workbook(path: Path, kind: str) -> tuple[int, int]:
    try:
        entries, skipped = read_list(path, kind)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Не удалось прочитать Excel. Нужен файл .xlsx.") from exc
    if not entries:
        expected = "числовых id" if kind == LIST_ID else "ников"
        raise ValueError(f"В первом столбце со второй строки нет {expected}.")
    return len(entries), skipped


def _field_prompt(field: str, profile: Profile) -> str:
    if field == "pause_min":
        return (
            "Минимальная пауза между действиями.\n"
            f"Одно целое число секунд, от 5 до 300. Сейчас: {_num(profile.pause_min)}."
        )
    if field == "pause_max":
        return (
            "Максимальная пауза между действиями.\n"
            f"Одно целое число секунд, от 5 до 300. Сейчас: {_num(profile.pause_max)}."
        )
    return f"Введите новое значение: {_FIELD_LABELS[field]}."


def _num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)

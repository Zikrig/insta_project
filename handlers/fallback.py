"""Любой неразобранный апдейт снова открывает инлайн-меню."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.menu import show_menu

router = Router(name="fallback")


@router.message()
async def unknown(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_menu(message, "Меню администратора.")

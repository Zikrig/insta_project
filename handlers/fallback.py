"""Любой неразобранный апдейт снова открывает меню."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.keyboards import admin_kb

router = Router(name="fallback")


@router.message()
async def unknown(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Меню администратора.", reply_markup=admin_kb())

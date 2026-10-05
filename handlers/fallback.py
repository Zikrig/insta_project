"""Любой неразобранный апдейт снова открывает инлайн-меню."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from handlers.keyboards import admin_kb

router = Router(name="fallback")


@router.message()
async def unknown(message: Message, state: FSMContext) -> None:
    await state.clear()
    sent = await message.answer("Меню администратора.", reply_markup=ReplyKeyboardRemove())
    await sent.edit_reply_markup(reply_markup=admin_kb())

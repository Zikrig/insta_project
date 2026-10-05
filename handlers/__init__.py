"""Регистрация роутеров. Меню идёт первым, запасной ответ — последним."""

from __future__ import annotations

from aiogram import Dispatcher

from handlers.fallback import router as fallback_router
from handlers.menu import router as menu_router
from handlers.middleware import AdminOnlyMiddleware
from handlers.control import router as control_router
from handlers.profiles import router as profiles_router


def setup(dp: Dispatcher) -> None:
    dp.update.middleware(AdminOnlyMiddleware())
    dp.include_router(menu_router)
    dp.include_router(profiles_router)
    dp.include_router(control_router)
    dp.include_router(fallback_router)

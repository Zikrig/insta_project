"""Доступ только у id из ADMIN_IDS и только в личном чате."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update

from config import get_settings

logger = logging.getLogger("remover")


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if not _is_private(event):
            return None
        user = data.get("event_from_user")
        if user is None and event.message is not None:
            user = event.message.from_user
        if user is None and event.callback_query is not None:
            user = event.callback_query.from_user
        if user is None or user.id not in get_settings().admin_ids:
            await _refuse(event)
            logger.info("отказ пользователю %s", getattr(user, "id", "unknown"))
            return None
        return await handler(event, data)


def _is_private(event: Update) -> bool:
    if event.message is not None:
        return event.message.chat.type == "private"
    callback = event.callback_query
    if callback is None:
        return False
    # Старое сообщение может быть уже недоступно, но нажатие всё равно из личного чата.
    if callback.message is None:
        return True
    return callback.message.chat.type == "private"


async def _refuse(event: Update) -> None:
    if event.message is not None:
        await event.message.answer("Нет доступа.")
    elif event.callback_query is not None:
        await event.callback_query.answer("Нет доступа.", show_alert=True)

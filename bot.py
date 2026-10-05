"""Точка входа: бот, фоновый прогон и ежедневный отчёт в одном процессе."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import ensure_dirs, get_settings, load_settings
from handlers import setup
from services.db import init_db
from services.report import daily_loop
from services.runner import runner


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue


def _setup_logging() -> None:
    log_path = get_settings().logs_dir / "remover.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    # Апдейты Telegram не пишем: текстом могут прислать содержимое сессии.
    logging.getLogger("aiogram").setLevel(logging.WARNING)


async def main() -> None:
    _utf8_stdio()
    load_settings()
    ensure_dirs(get_settings())
    _setup_logging()
    await init_db()
    logger = logging.getLogger("remover")
    logger.info("бот запущен, админов: %s", len(get_settings().admin_ids))
    bot = Bot(token=get_settings().bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    setup(dispatcher)
    report_task = asyncio.create_task(daily_loop(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        report_task.cancel()
        await runner.stop()
        try:
            await report_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Один прогон удаления. Второй одновременно не стартует."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path

from aiogram import Bot

from services import db
from services.db import Profile
from services.excel_io import read_list
from services.instagram import RunConfig, run_remover
from services.reasons import STATUS_RU, safe_detail
from services.report import notify_admins, render_stop

logger = logging.getLogger("remover")


class Runner:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._pages: list = []
        self._bot: Bot | None = None
        self._start_lock = asyncio.Lock()
        self.profile_id: int | None = None
        self.profile_name: str | None = None
        self.run_id: int | None = None
        self.test_mode = False

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, profile: Profile, *, test_limit: int | None, bot: Bot) -> None:
        async with self._start_lock:
            if self.running():
                raise RuntimeError("Уже выполняется другой прогон.")
            self._bot = bot
            self._stop = asyncio.Event()
            self._pages = []
            self.profile_id = profile.id
            self.profile_name = profile.name
            self.test_mode = test_limit is not None
            self.run_id = None
            self._task = asyncio.create_task(self._execute(profile, test_limit))

    async def stop(self) -> bool:
        if not self.running():
            return False
        self._stop.set()
        page = self._pages[0] if self._pages else None
        if page is not None:
            try:
                await page.close()
            except Exception as exc:
                logger.error("страница не закрылась: %s", type(exc).__name__)
        task = self._task
        if task is None:
            return True
        try:
            await asyncio.wait_for(task, timeout=90)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return True

    async def _execute(self, profile: Profile, test_limit: int | None) -> None:
        reason = "error"
        run_id: int | None = None
        try:
            if not profile.list_path or not Path(profile.list_path).is_file():
                raise FileNotFoundError("файл списка не найден")
            if not profile.session_path or not Path(profile.session_path).is_file():
                raise FileNotFoundError("файл сессии не найден")
            usernames, _skipped = await asyncio.to_thread(
                read_list, Path(profile.list_path), profile.list_kind
            )
            # Уже снятые и отсутствующие в подписчиках не трогаем. Ошибки остаются в очереди.
            done = await db.final_usernames(profile.id)
            pending = [name for name in usernames if name not in done]
            logger.info(
                "профиль %s: режим %s, в файле %s, уже обработано %s, в очереди %s",
                profile.name,
                profile.list_kind,
                len(usernames),
                len(usernames) - len(pending),
                len(pending),
            )
            removed_today = await db.removed_on_day(profile.id, date.today())
            run_id = await db.start_run(profile.id, test_limit is not None)
            self.run_id = run_id
            if not pending:
                reason = "finished"
                return
            if removed_today >= profile.daily_limit:
                reason = "daily_limit"
                return
            config = RunConfig(
                session_path=profile.session_path,
                ig_username=profile.ig_username,
                pause_min=profile.pause_min,
                pause_max=profile.pause_max,
                break_every_min=profile.break_every_min,
                break_every_max=profile.break_every_max,
                break_minutes=profile.break_minutes,
                daily_limit=profile.daily_limit,
                daily_removed=removed_today,
                test_limit=test_limit,
                list_kind=profile.list_kind,
                usernames=pending,
            )

            async def on_result(username: str, status: str, detail: str = "") -> None:
                await db.record_result(profile.id, run_id, username, status, detail)
                logger.info("%s | %s | %s", profile.name, username, STATUS_RU.get(status, status))

            reason = await run_remover(config, self._stop, on_result, self._pages)
        except asyncio.CancelledError:
            # Снимаем флаг отмены, иначе запись причины в базу оборвётся на первом await.
            reason = "stopped_by_admin"
            current = asyncio.current_task()
            while current is not None and current.cancelling():
                current.uncancel()
        except Exception as exc:
            logger.error("прогон прерван: %s", safe_detail(exc))
            reason = "stopped_by_admin" if self._stop.is_set() else "error"
        finally:
            await self._close_run(profile.name, run_id, reason)

    async def _close_run(self, profile_name: str, run_id: int | None, reason: str) -> None:
        removed = not_found = errors = 0
        try:
            if run_id is not None:
                removed, not_found, errors = await db.finish_run(run_id, reason)
            text = render_stop(profile_name, reason, removed, not_found, errors)
            logger.info("%s", text.replace("\n", " | "))
            if self._bot is not None:
                await notify_admins(self._bot, text, running=False)
        except Exception as exc:
            logger.error("не удалось закрыть прогон: %s", type(exc).__name__)
        finally:
            self.run_id = None
            self.profile_id = None
            self.profile_name = None
            self.test_mode = False


runner = Runner()

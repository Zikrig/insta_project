"""SQLite: профили, результаты по никам и прогоны.

Удалённые и не найденные ники при следующем запуске пропускаются.
Статус «ошибка» остаётся в таблице, но в пропуск не входит — такой ник
будет обработан снова.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import aiosqlite

from config import get_settings
from services.reasons import reason_text

_db_path: Path | None = None
_lock = asyncio.Lock()

_STATUS_COLUMN = {
    "removed": "removed_count",
    "not_found": "not_found_count",
    "error": "error_count",
}

_FIELDS = {
    "ig_username",
    "pause_min",
    "pause_max",
    "break_every_min",
    "break_every_max",
    "break_minutes",
    "daily_limit",
    "list_kind",
}


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    session_path: str | None
    list_path: str | None
    list_count: int
    ig_username: str
    pause_min: float
    pause_max: float
    break_every_min: int
    break_every_max: int
    break_minutes: float
    daily_limit: int
    list_kind: str


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _profile(row: aiosqlite.Row) -> Profile:
    return Profile(
        id=row["id"],
        name=row["name"],
        session_path=row["session_path"],
        list_path=row["list_path"],
        list_count=row["list_count"],
        ig_username=row["ig_username"],
        pause_min=row["pause_min"],
        pause_max=row["pause_max"],
        break_every_min=row["break_every_min"],
        break_every_max=row["break_every_max"],
        break_minutes=row["break_minutes"],
        daily_limit=row["daily_limit"],
        list_kind=row["list_kind"] if row["list_kind"] in {"nick", "id"} else "nick",
    )


@asynccontextmanager
async def _connect():
    if _db_path is None:
        raise RuntimeError("База не инициализирована")
    async with _lock:
        db = await aiosqlite.connect(_db_path)
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def init_db() -> None:
    global _db_path
    _db_path = get_settings().db_path
    async with _connect() as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                session_path TEXT,
                list_path TEXT,
                list_count INTEGER NOT NULL DEFAULT 0,
                ig_username TEXT NOT NULL DEFAULT '',
                pause_min REAL NOT NULL DEFAULT 20,
                pause_max REAL NOT NULL DEFAULT 60,
                break_every_min INTEGER NOT NULL DEFAULT 20,
                break_every_max INTEGER NOT NULL DEFAULT 30,
                break_minutes REAL NOT NULL DEFAULT 60,
                daily_limit INTEGER NOT NULL DEFAULT 100,
                list_kind TEXT NOT NULL DEFAULT 'nick',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS results (
                profile_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (profile_id, username),
                FOREIGN KEY (profile_id) REFERENCES profiles(id)
            );

            CREATE TABLE IF NOT EXISTS user_notify (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                stopped_at TEXT,
                stop_reason TEXT NOT NULL DEFAULT '',
                removed_count INTEGER NOT NULL DEFAULT 0,
                not_found_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                test_mode INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (profile_id) REFERENCES profiles(id)
            );
            """
        )
        cursor = await db.execute("PRAGMA table_info(profiles)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "list_kind" not in columns:
            await db.execute(
                "ALTER TABLE profiles ADD COLUMN list_kind TEXT NOT NULL DEFAULT 'nick'"
            )
        if "cooldown_until" not in columns:
            await db.execute("ALTER TABLE profiles ADD COLUMN cooldown_until TEXT")
        await db.execute(
            """
            UPDATE profiles
            SET pause_min = 20, pause_max = 60,
                break_every_min = 20, break_every_max = 30,
                break_minutes = 60
            WHERE pause_min = 15 AND pause_max = 40 AND break_minutes = 15
            """
        )


async def notifications_on(user_id: int) -> bool:
    """Писать ли этому Telegram-id сообщения прогона. Нет строки — писать."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT enabled FROM user_notify WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return True
    return bool(row["enabled"])


async def set_notifications(user_id: int, enabled: bool) -> None:
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO user_notify (user_id, enabled)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET enabled = excluded.enabled
            """,
            (user_id, 1 if enabled else 0),
        )


async def save_session(name: str, session_path: str, ig_username: str) -> Profile:
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO profiles (
                name, session_path, ig_username, created_at,
                pause_min, pause_max, break_every_min, break_every_max, break_minutes
            )
            VALUES (?, ?, ?, ?, 20, 60, 20, 30, 60)
            ON CONFLICT(name) DO UPDATE SET
                session_path = excluded.session_path,
                ig_username = excluded.ig_username
            """,
            (name, session_path, ig_username, _now()),
        )
        cursor = await db.execute("SELECT * FROM profiles WHERE name = ?", (name,))
        row = await cursor.fetchone()
    return _profile(row)


async def save_list(profile_id: int, list_path: str, list_count: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE profiles SET list_path = ?, list_count = ? WHERE id = ?",
            (list_path, list_count, profile_id),
        )


async def update_field(profile_id: int, field: str, value: object) -> None:
    if field not in _FIELDS:
        raise ValueError("Неизвестная настройка")
    async with _connect() as db:
        await db.execute(
            f"UPDATE profiles SET {field} = ? WHERE id = ?",
            (value, profile_id),
        )


async def get_profile(profile_id: int) -> Profile | None:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        row = await cursor.fetchone()
    return _profile(row) if row else None


async def delete_profile(profile_id: int) -> Profile | None:
    """Удалить профиль вместе с журналом ников и прогонов. Файлы снимает вызывающий код."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        await db.execute("DELETE FROM results WHERE profile_id = ?", (profile_id,))
        await db.execute("DELETE FROM runs WHERE profile_id = ?", (profile_id,))
        await db.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    return _profile(row)


async def list_profiles() -> list[Profile]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM profiles ORDER BY name")
        rows = await cursor.fetchall()
    return [_profile(row) for row in rows]


async def statuses(profile_id: int) -> dict[str, str]:
    """Последний статус каждого ника профиля. Ключ — ник или id из списка."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT username, status FROM results WHERE profile_id = ?",
            (profile_id,),
        )
        rows = await cursor.fetchall()
    return {row["username"]: row["status"] for row in rows}


async def final_usernames(profile_id: int) -> set[str]:
    """Ники, которые повторно не трогаем: уже сняты или не были в подписчиках."""
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT username FROM results
            WHERE profile_id = ? AND status IN ('removed', 'not_found')
            """,
            (profile_id,),
        )
        rows = await cursor.fetchall()
    return {row["username"] for row in rows}


async def removed_between(profile_id: int, start: str, end: str) -> int:
    """Успешные снятия с момента start включительно до end, не включая end."""
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) AS total FROM results
            WHERE profile_id = ? AND status = 'removed'
              AND updated_at >= ? AND updated_at < ?
            """,
            (profile_id, start, end),
        )
        row = await cursor.fetchone()
    return int(row["total"])


async def cooldown_until(profile_id: int) -> datetime | None:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT cooldown_until FROM profiles WHERE id = ?",
            (profile_id,),
        )
        row = await cursor.fetchone()
    if row is None or not row["cooldown_until"]:
        return None
    try:
        return datetime.fromisoformat(row["cooldown_until"])
    except ValueError:
        return None


async def set_cooldown(profile_id: int, until: datetime) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE profiles SET cooldown_until = ? WHERE id = ?",
            (until.replace(microsecond=0).isoformat(), profile_id),
        )


async def removed_on_day(profile_id: int, day: date) -> int:
    start, end = _day_bounds(day)
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) AS total FROM results
            WHERE profile_id = ? AND status = 'removed'
              AND updated_at >= ? AND updated_at < ?
            """,
            (profile_id, start, end),
        )
        row = await cursor.fetchone()
    return int(row["total"])


async def start_run(profile_id: int, test_mode: bool) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            """
            INSERT INTO runs (profile_id, started_at, test_mode)
            VALUES (?, ?, ?)
            """,
            (profile_id, _now(), 1 if test_mode else 0),
        )
        return int(cursor.lastrowid)


async def record_result(
    profile_id: int,
    run_id: int,
    username: str,
    status: str,
    detail: str = "",
) -> None:
    column = _STATUS_COLUMN.get(status)
    if column is None:
        raise ValueError("Неизвестный статус")
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO results (profile_id, username, status, detail, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, username) DO UPDATE SET
                status = excluded.status,
                detail = excluded.detail,
                updated_at = excluded.updated_at
            """,
            (profile_id, username, status, detail[:300], _now()),
        )
        await db.execute(
            f"UPDATE runs SET {column} = {column} + 1 WHERE id = ?",
            (run_id,),
        )


async def finish_run(run_id: int, reason: str) -> tuple[int, int, int]:
    async with _connect() as db:
        await db.execute(
            """
            UPDATE runs
            SET stopped_at = ?, stop_reason = ?
            WHERE id = ? AND stopped_at IS NULL
            """,
            (_now(), reason, run_id),
        )
        cursor = await db.execute(
            """
            SELECT removed_count, not_found_count, error_count
            FROM runs WHERE id = ?
            """,
            (run_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return 0, 0, 0
    return int(row["removed_count"]), int(row["not_found_count"]), int(row["error_count"])


async def run_counts(run_id: int) -> tuple[int, int, int]:
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT removed_count, not_found_count, error_count
            FROM runs WHERE id = ?
            """,
            (run_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return 0, 0, 0
    return int(row["removed_count"]), int(row["not_found_count"]), int(row["error_count"])


async def latest_run() -> aiosqlite.Row | None:
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT runs.*, profiles.name AS profile_name
            FROM runs
            JOIN profiles ON profiles.id = runs.profile_id
            ORDER BY runs.id DESC
            LIMIT 1
            """
        )
        return await cursor.fetchone()


async def report_rows(day: date) -> tuple[list[tuple[str, int, int, int]], str]:
    """Счётчики за календарный день и текст последней остановки за этот день."""
    start, end = _day_bounds(day)
    async with _connect() as db:
        cursor = await db.execute("SELECT id, name FROM profiles ORDER BY name")
        profiles = await cursor.fetchall()
        cursor = await db.execute(
            """
            SELECT profile_id, status, COUNT(*) AS total
            FROM results
            WHERE updated_at >= ? AND updated_at < ?
            GROUP BY profile_id, status
            """,
            (start, end),
        )
        grouped = await cursor.fetchall()
        cursor = await db.execute(
            """
            SELECT stop_reason, stopped_at
            FROM runs
            WHERE started_at < ? AND (stopped_at IS NULL OR stopped_at >= ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (end, start),
        )
        last = await cursor.fetchone()

    totals: dict[int, dict[str, int]] = {}
    for row in grouped:
        bucket = totals.setdefault(row["profile_id"], {"removed": 0, "not_found": 0, "error": 0})
        if row["status"] in bucket:
            bucket[row["status"]] = int(row["total"])

    rows = []
    for profile in profiles:
        bucket = totals.get(profile["id"], {"removed": 0, "not_found": 0, "error": 0})
        rows.append((profile["name"], bucket["removed"], bucket["not_found"], bucket["error"]))

    if last is None:
        last_stop = "остановок не было"
    elif last["stopped_at"] is None:
        last_stop = "прогон ещё выполняется"
    else:
        last_stop = reason_text(last["stop_reason"])
    return rows, last_stop


def _day_bounds(day: date) -> tuple[str, str]:
    start = f"{day.isoformat()}T00:00:00"
    next_day = day + timedelta(days=1)
    end = f"{next_day.isoformat()}T00:00:00"
    return start, end

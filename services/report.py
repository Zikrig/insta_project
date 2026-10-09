"""Ежедневный отчёт: письмо и то же текст администраторам в Telegram."""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage

from aiogram import Bot

from config import get_settings
from services import db
from services.reasons import reason_text

logger = logging.getLogger("remover")


def render_report(day: str, rows: list[tuple[str, int, int, int]], last_stop: str) -> str:
    lines = [f"Отчёт за {day}", ""]
    removed_total = 0
    if not rows:
        lines.append("Профилей нет.")
    for name, removed, not_found, errors in rows:
        removed_total += removed
        lines.append(f"{name}")
        lines.append(f"удалён: {removed}")
        lines.append(f"не найден: {not_found}")
        lines.append(f"ошибка: {errors}")
        lines.append("")
    lines.append(f"Всего удалено: {removed_total}")
    lines.append(f"Последняя остановка: {last_stop}")
    text = "\n".join(lines).strip()
    if len(text) > 4000:
        return text[:3980] + "\n…обрезано"
    return text


def queue_counts(names: list[str], statuses: dict[str, str]) -> tuple[int, int]:
    """Снятые из текущего списка и сколько строк ещё не закрыто.

    «Не найден» в остаток не входит: такой ник повторно не берётся.
    Ошибка и необработанная строка остаются в очереди.
    """
    removed = 0
    remaining = 0
    for name in names:
        status = statuses.get(name)
        if status == "removed":
            removed += 1
        elif status != "not_found":
            remaining += 1
    return removed, remaining


def queue_line(removed_total: int, remaining: int) -> str:
    return f"всего удалено {removed_total}, осталось {remaining}"


def render_stop(profile_name: str, reason: str, removed: int, not_found: int, errors: int) -> str:
    return (
        f"Прогон «{profile_name}» завершён.\n"
        f"Причина: {reason_text(reason)}\n"
        f"Удалено: {removed}\n"
        f"Не найдено: {not_found}\n"
        f"Ошибки: {errors}"
    )


async def build_report(day: date) -> str:
    rows, last_stop = await db.report_rows(day)
    return render_report(day.isoformat(), rows, last_stop)


def _send_email(text: str) -> None:
    current = get_settings()
    message = EmailMessage()
    message["Subject"] = "Instagram: отчёт"
    message["From"] = current.smtp_from or current.smtp_user
    message["To"] = current.report_email
    message.set_content(text)
    if current.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(current.smtp_host, current.smtp_port, timeout=30)
    else:
        smtp = smtplib.SMTP(current.smtp_host, current.smtp_port, timeout=30)
    try:
        if current.smtp_port == 587:
            smtp.starttls()
            smtp.ehlo()
        if current.smtp_user:
            smtp.login(current.smtp_user, current.smtp_password)
        smtp.send_message(message)
    finally:
        smtp.quit()


def _api_reason(exc: BaseException) -> str:
    """Короткий текст ошибки Telegram без URL: в адресе метода бывает токен бота."""
    raw = getattr(exc, "message", None) or type(exc).__name__
    text = str(raw)
    token = get_settings().bot_token
    if token:
        text = text.replace(token, "")
    text = re.sub(r"https?://\S+", "", text)
    text = " ".join(text.split())
    return text[:180] or type(exc).__name__


async def notify_admins(
    bot: Bot, text: str, *, running: bool | None = None, refresh: bool = True
) -> bool:
    from handlers.menu import refresh_open_menu

    delivered = False
    for admin_id in get_settings().admin_ids:
        if not await db.notifications_on(admin_id):
            if refresh:
                await refresh_open_menu(bot, admin_id, running=running)
            continue
        try:
            await bot.send_message(admin_id, text)
            delivered = True
        except Exception as exc:
            logger.error("сообщение в Telegram не ушло: %s", _api_reason(exc))
            continue
        if refresh:
            await refresh_open_menu(bot, admin_id, running=running)
    return delivered


async def deliver(bot: Bot, text: str) -> bool:
    """Отправить отчёт. True, если ушло хотя бы в один канал."""
    current = get_settings()
    logger.info("отчёт:\n%s", text)
    delivered = False
    email_ready = bool(current.smtp_host and current.report_email and (current.smtp_from or current.smtp_user))
    if email_ready:
        try:
            await asyncio.to_thread(_send_email, text)
            delivered = True
        except Exception as exc:
            logger.error("письмо не отправлено: %s", type(exc).__name__)
    elif not current.smtp_host:
        logger.info("SMTP не задан, письмо пропущено")
    if await notify_admins(bot, text):
        delivered = True
    return delivered


async def daily_loop(bot: Bot) -> None:
    """Раз в сутки в REPORT_HOUR шлёт отчёт за предыдущий календарный день."""
    while True:
        try:
            await _maybe_send(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("сбой отчёта: %s", type(exc).__name__)
        await asyncio.sleep(30)


async def _maybe_send(bot: Bot) -> None:
    current = get_settings()
    now = datetime.now()
    if now.hour != current.report_hour:
        return
    day = (now.date() - timedelta(days=1)).isoformat()
    marker = current.report_marker
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == day:
        return
    text = await build_report(now.date() - timedelta(days=1))
    if await deliver(bot, text):
        marker.write_text(day, encoding="utf-8")

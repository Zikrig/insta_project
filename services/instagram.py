"""Снятие подписчиков в веб-версии Instagram через сохранённую сессию.

Логин и пароль не используются. Очередь ников сюда приходит уже без тех,
кто помечен удалённым или не найденным: продолжение с места остановки
делает вызывающий код.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, Page, TimeoutError as PlaywrightTimeout, async_playwright

from services.names import normalize_username
from services.reasons import safe_detail

logger = logging.getLogger("remover")
_verbose: contextvars.ContextVar[bool] = contextvars.ContextVar("remover_verbose", default=False)
_shot_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar("remover_shots", default=None)
_shot_n: contextvars.ContextVar[int] = contextvars.ContextVar("remover_shot_n", default=0)

# Селекторы веб-версии instagram.com. Вёрстка сайта их ломает:
# если прогон останавливается с «не найдена форма подписчиков», править этот блок.
SEARCH_INPUT = (
    "input[aria-label='Search input'], "
    "input[aria-label='Search'], "
    "input[aria-label='Поиск'], "
    "input[placeholder='Search'], "
    "input[placeholder='Поиск']"
)
TEXT_INPUT = "input[type='text'], input[type='search'], input:not([type])"
REMOVE_BUTTON = re.compile(r"^(Remove|Удалить)\b", re.IGNORECASE)
BLOCK_TEXT = re.compile(
    r"try again later|action blocked|we limit how often|please wait a few minutes|"
    r"попробуйте позже|повторите попытку позже|действие заблокировано",
    re.IGNORECASE,
)
LOGIN_PARTS = ("/accounts/login", "/challenge/", "checkpoint")
FOLLOWERS_LINK = re.compile(r"followers|подписчик", re.IGNORECASE)

ResultCallback = Callable[[str, str, str], Awaitable[None]]


class StopRun(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RunConfig:
    session_path: str
    ig_username: str
    pause_min: float
    pause_max: float
    break_every_min: int
    break_every_max: int
    break_minutes: float
    daily_limit: int
    daily_removed: int
    test_limit: int | None
    list_kind: str
    usernames: list[str]


class AbsentAccount(Exception):
    """Числовой id не открылся как аккаунт. Такой строке ставим «не найден»."""


async def run_remover(
    config: RunConfig,
    stop_event: asyncio.Event,
    on_result: ResultCallback,
    pages: list[Page],
) -> str:
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                # В Docker у Chromium маленький /dev/shm, без этого флага он часто падает.
                # AutomationControlled: иначе сайт часто отдаёт пустую страницу без списка подписчиков.
                args=["--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            tokens = _arm_trace(config.test_limit is not None)
            try:
                return await _browse(browser, config, stop_event, on_result, pages)
            finally:
                pages.clear()
                await browser.close()
                _disarm_trace(tokens)
    except StopRun as exc:
        return exc.reason
    except Exception as exc:
        if stop_event.is_set():
            return "stopped_by_admin"
        logger.error("сбой браузера: %s", safe_detail(exc))
        return "error"


async def _browse(
    browser: Browser,
    config: RunConfig,
    stop_event: asyncio.Event,
    on_result: ResultCallback,
    pages: list[Page],
) -> str:
    probe = await browser.new_context()
    probe_page = await probe.new_page()
    raw_agent = await probe_page.evaluate("() => navigator.userAgent")
    await probe.close()
    user_agent = str(raw_agent).replace("HeadlessChrome", "Chrome")
    context = await browser.new_context(
        storage_state=config.session_path,
        viewport={"width": 1280, "height": 800},
        locale="ru-RU",
        user_agent=user_agent,
    )
    page = await context.new_page()
    pages.append(page)
    page.set_default_timeout(20_000)
    page.set_default_navigation_timeout(45_000)
    await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    await _settle_profile(page)
    logger.info("адрес ленты: %s", _page_address(page))
    await _shot(page, "feed")
    if await _session_rejected(page):
        logger.info("сессия недействительна: вместо ленты страница входа")
        await _shot(page, "login")
        raise StopRun("session_invalid")
    await _open_followers(page, config.ig_username)
    if not await _pause(config.pause_min, stop_event):
        return "stopped_by_admin"
    return await _walk(page, config, stop_event, on_result)


async def _walk(
    page: Page,
    config: RunConfig,
    stop_event: asyncio.Event,
    on_result: ResultCallback,
) -> str:
    removed_today = config.daily_removed
    since_break = 0
    # Длинный перерыв не по таймеру, а после пачки успешных удалений.
    break_after = random.randint(config.break_every_min, config.break_every_max)
    processed = 0
    for username in config.usernames:
        if stop_event.is_set():
            return "stopped_by_admin"
        if config.test_limit is not None and processed >= config.test_limit:
            return "test_limit"
        # Лимит считается по успешным снятиям за календарные сутки, не по попыткам.
        if removed_today >= config.daily_limit:
            return "daily_limit"
        if await _rate_limited(page):
            logger.info("обнаружено ограничение Instagram, прогон остановлен")
            raise StopRun("rate_limited")
        try:
            await _ensure_followers(page, config.ig_username)
            lookup = username
            if config.list_kind == "id":
                # В поиске подписчиков Instagram ждёт ник, не числовой id.
                lookup = await _username_for_id(page, username)
            status = await _remove_one(page, lookup)
            detail = ""
        except AbsentAccount:
            status = "not_found"
            detail = "аккаунт по id не открылся"
        except StopRun:
            # Ограничение на текущем нике: в базу его не пишем, чтобы повтор не пропустил его.
            raise
        except Exception as exc:
            status = "error"
            detail = safe_detail(exc)
        try:
            await on_result(username, status, detail)
        except Exception:
            logger.error("результат не сохранён, прогон остановлен")
            return "error"
        processed += 1
        if status == "removed":
            removed_today += 1
            since_break += 1
            if removed_today >= config.daily_limit:
                return "daily_limit"
            if since_break >= break_after:
                logger.info(
                    "длинный перерыв %.0f мин после %s удалений",
                    config.break_minutes,
                    since_break,
                )
                if not await _pause(config.break_minutes * 60, stop_event):
                    return "stopped_by_admin"
                since_break = 0
                break_after = random.randint(config.break_every_min, config.break_every_max)
        if not await _pause(random.uniform(config.pause_min, config.pause_max), stop_event):
            return "stopped_by_admin"
    return "finished"


async def _pause(seconds: float, stop_event: asyncio.Event) -> bool:
    """Пауза, которую остановка прогона прерывает примерно за секунду."""
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return False
        await asyncio.sleep(min(1.0, deadline - time.monotonic()))
    return True


async def _username_for_id(page: Page, user_id: str) -> str:
    """Ник по числовому id через уже открытую страницу instagram.com.

    Запрос уходит только на instagram.com с cookies этой сессии.
    В лог попадает ник, не тело ответа и не cookie.
    """
    result = await page.evaluate(
        """async (userId) => {
            const row = document.cookie.split('; ').find((item) => item.startsWith('csrftoken='));
            const csrf = row ? decodeURIComponent(row.slice('csrftoken='.length)) : '';
            let response;
            try {
                response = await fetch(
                    'https://www.instagram.com/api/v1/users/' + encodeURIComponent(userId) + '/info/',
                    {
                        credentials: 'include',
                        headers: {
                            'X-IG-App-ID': '936619743392459',
                            'X-CSRFToken': csrf,
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                    },
                );
            } catch (error) {
                return { status: 'error' };
            }
            let text = '';
            try {
                text = await response.text();
            } catch (error) {
                return { status: 'error' };
            }
            const lowered = text.toLowerCase();
            if (
                response.status === 429
                || lowered.includes('try again later')
                || lowered.includes('action blocked')
                || lowered.includes('please wait a few minutes')
            ) {
                return { status: 'blocked' };
            }
            if (response.status === 401 || lowered.includes('login_required')) {
                return { status: 'login' };
            }
            if (response.status === 404) {
                return { status: 'absent' };
            }
            if (!response.ok) {
                return { status: 'error' };
            }
            try {
                const data = JSON.parse(text);
                const name = data && data.user && data.user.username;
                if (typeof name === 'string' && name) {
                    return { status: 'ok', username: name };
                }
            } catch (error) {
                return { status: 'error' };
            }
            return { status: 'absent' };
        }""",
        user_id,
    )
    status = result.get("status") if isinstance(result, dict) else "error"
    if status == "blocked":
        raise StopRun("rate_limited")
    if status == "login":
        raise StopRun("session_invalid")
    if status == "absent":
        raise AbsentAccount()
    if status != "ok":
        raise RuntimeError("не удалось открыть ник по id")
    username = normalize_username(str(result.get("username", "")))
    if username is None:
        raise RuntimeError("по id пришёл некорректный ник")
    logger.info("id %s → %s", user_id, username)
    return username


async def _remove_one(page: Page, username: str) -> str:
    _detail("--- ник %s ---", username)
    dialog = await _followers_dialog(page)
    search = await _search_box(dialog)
    if search is None:
        logger.info("в окне подписчиков нет поля поиска, адрес: %s", _page_address(page))
        await _shot(page, "no_search")
        raise StopRun("ui_changed")
    await search.click()
    await search.press("Control+A")
    await search.press("Backspace")
    await search.press_sequentially(username, delay=40)
    # Точное совпадение ника: /ann/ не должен цеплять /anna/.
    link = dialog.locator(
        f'a[href="/{username}/"], a[href^="/{username}/?"], '
        f'a[href="https://www.instagram.com/{username}/"], '
        f'a[href^="https://www.instagram.com/{username}/?"]'
    )
    try:
        await link.first.wait_for(state="visible", timeout=8000)
    except PlaywrightTimeout:
        if await _rate_limited(page):
            raise StopRun("rate_limited")
        _detail("строка @%s не появилась", username)
        await _shot(page, f"missing_{_shot_name(username)}")
        return "not_found"
    button = await _remove_control(link.first)
    if button is None:
        _detail("кнопка удаления в строке @%s не найдена", username)
        await _shot(page, f"no_remove_{_shot_name(username)}")
        return "not_found"
    label = ""
    try:
        label = (await button.inner_text()).replace("\n", " ").strip()
    except Exception:
        label = ""
    _detail("нажимаю %s", (label or "удалить")[:40])
    await button.click()
    if await _rate_limited(page):
        raise StopRun("rate_limited")
    await _confirm_remove(page)
    if await _rate_limited(page):
        raise StopRun("rate_limited")
    _detail("подписчик @%s снят", username)
    await _shot(page, f"removed_{_shot_name(username)}")
    return "removed"


async def _remove_control(link):
    """Кнопка «Удалить» в той же строке, что и ник. Это часто div, не button."""
    node = link
    for _ in range(8):
        parent = node.locator("xpath=..")
        if await parent.count() == 0:
            return None
        control = await _text_control(parent, REMOVE_BUTTON)
        if control is not None:
            return control
        node = parent
    return None


async def _text_control(scope, pattern: re.Pattern[str]):
    nodes = scope.locator("button, [role='button'], div, span")
    count = await nodes.count()
    for index in range(min(count, 40)):
        item = nodes.nth(index)
        try:
            text = (await item.inner_text(timeout=500)).strip()
        except Exception:
            continue
        if pattern.fullmatch(text):
            return item
    return None


async def _confirm_remove(page: Page) -> None:
    """Второе нажатие Remove в окне без поля поиска — это подтверждение."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if await _rate_limited(page):
            raise StopRun("rate_limited")
        dialogs = page.get_by_role("dialog")
        count = await dialogs.count()
        for index in range(count):
            dialog = dialogs.nth(index)
            if await dialog.locator("input").count():
                continue
            button = await _text_control(dialog, REMOVE_BUTTON)
            if button is None:
                continue
            await button.click()
            _detail("подтверждение нажато")
            try:
                await dialog.wait_for(state="hidden", timeout=8000)
            except PlaywrightTimeout:
                if await _rate_limited(page):
                    raise StopRun("rate_limited")
                await _shot(page, "confirm_open")
                raise RuntimeError("подтверждение удаления не закрылось")
            return
        await asyncio.sleep(0.25)
    _detail("окно подтверждения не появилось")
    await _shot(page, "no_confirm")
    raise RuntimeError("нет окна подтверждения удаления")


async def _open_followers(page: Page, username: str) -> None:
    logger.info("открываю профиль https://www.instagram.com/%s/", username)
    await page.goto(
        f"https://www.instagram.com/{username}/",
        wait_until="domcontentloaded",
    )
    await _settle_profile(page)
    logger.info("адрес после профиля: %s, заголовок: %s", _page_address(page), await _title(page))
    await _shot(page, "profile")
    if await _session_rejected(page):
        logger.info("вместо профиля страница входа или проверки")
        await _shot(page, "login")
        raise StopRun("session_invalid")
    opened = await _click_followers(page, username)
    if not opened:
        logger.info("открываю подписчиков по адресу, страница: %s", _page_address(page))
        await page.goto(
            f"https://www.instagram.com/{username}/followers/",
            wait_until="domcontentloaded",
        )
        await _settle_profile(page)
        logger.info("адрес после перехода: %s, заголовок: %s", _page_address(page), await _title(page))
        await _shot(page, "followers_url")
        if await _session_rejected(page):
            logger.info("вместо подписчиков страница входа или проверки")
            await _shot(page, "login")
            raise StopRun("session_invalid")
    dialog = page.get_by_role("dialog").first
    try:
        await dialog.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeout as exc:
        logger.info(
            "окно подписчиков не открылось, адрес: %s, заголовок: %s",
            _page_address(page),
            await _title(page),
        )
        await _shot(page, "no_dialog")
        raise StopRun("ui_changed") from exc
    count = await page.get_by_role("dialog").count()
    logger.info("окон dialog: %s, адрес: %s", count, _page_address(page))
    logger.info("поиск в окне: %s", await _describe_inputs(dialog))
    await _shot(page, "followers")
    # Поиск в шапке сайта не считается: нужен поиск именно в окне подписчиков.
    if await _search_box(dialog) is None:
        logger.info("в окне подписчиков нет поля поиска, адрес: %s", _page_address(page))
        await _shot(page, "no_search")
        raise StopRun("ui_changed")


async def _click_followers(page: Page, username: str) -> bool:
    link = page.locator(f'a[href*="/{username}/followers"]')
    try:
        await link.first.wait_for(state="attached", timeout=12_000)
        logger.info("ссылок на подписчиков по адресу: %s", await link.count())
    except PlaywrightTimeout:
        by_role = page.get_by_role("link", name=FOLLOWERS_LINK)
        role_count = await by_role.count()
        logger.info(
            "ссылок на подписчиков по адресу: 0, по подписи: %s, адрес: %s",
            role_count,
            _page_address(page),
        )
        logger.info("href со словом followers: %s", await _follower_hrefs(page))
        if role_count == 0:
            await _shot(page, "no_followers_link")
            return False
        link = by_role
    href = await link.first.get_attribute("href")
    logger.info("кликаю подписчиков, href=%s", href or "нет")
    await _dismiss_overlays(page)
    try:
        await link.first.click(timeout=5_000)
    except Exception:
        await _dismiss_overlays(page)
        try:
            await link.first.click(timeout=5_000)
        except Exception as exc:
            logger.info("клик по подписчикам не прошёл: %s", type(exc).__name__)
            await _shot(page, "click_failed")
            return False
    return True


async def _search_box(dialog):
    specific = dialog.locator(SEARCH_INPUT)
    try:
        await specific.first.wait_for(state="attached", timeout=8_000)
        return specific.first
    except PlaywrightTimeout:
        fallback = dialog.locator(TEXT_INPUT)
        count = await fallback.count()
        for index in range(min(count, 5)):
            field = fallback.nth(index)
            if await field.is_visible():
                return field
        return None


def _page_address(page: Page) -> str:
    return page.url.split("?")[0][:180]


def _arm_trace(enabled: bool) -> tuple[contextvars.Token, contextvars.Token, contextvars.Token]:
    verbose_token = _verbose.set(enabled)
    folder: Path | None = None
    if enabled:
        try:
            from config import get_settings

            folder = get_settings().logs_dir / "shots"
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("*.png"):
                old.unlink()
            logger.info("тест: шаги в этом логе, снимки в data/logs/shots")
        except Exception as exc:
            logger.info("снимки теста недоступны: %s", type(exc).__name__)
            folder = None
    return verbose_token, _shot_dir.set(folder), _shot_n.set(0)


def _disarm_trace(tokens: tuple[contextvars.Token, contextvars.Token, contextvars.Token]) -> None:
    verbose_token, dir_token, n_token = tokens
    _verbose.reset(verbose_token)
    _shot_dir.reset(dir_token)
    _shot_n.reset(n_token)


def _detail(message: str, *args: object) -> None:
    """Шаги по каждому нику пишем только в тестовом прогоне, чтобы полный лог не раздувался."""
    if _verbose.get():
        logger.info(message, *args)


def _shot_name(username: str) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "", username.lower())[:20]
    return cleaned or "nick"


async def _title(page: Page) -> str:
    try:
        return (await page.title())[:80]
    except Exception:
        return ""


async def _shot(page: Page, name: str) -> None:
    folder = _shot_dir.get()
    if folder is None:
        return
    number = _shot_n.get() + 1
    _shot_n.set(number)
    path = folder / f"{number:02d}_{_shot_name(name)}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
        logger.info("снимок %s", path.name)
    except Exception as exc:
        logger.info("снимок не сохранился: %s", type(exc).__name__)


async def _describe_inputs(scope) -> str:
    inputs = scope.locator("input")
    count = await inputs.count()
    parts: list[str] = []
    for index in range(min(count, 5)):
        field = inputs.nth(index)
        try:
            placeholder = await field.get_attribute("placeholder") or ""
            label = await field.get_attribute("aria-label") or ""
        except Exception:
            continue
        parts.append(f"[{index}] placeholder={placeholder!r} aria={label!r}")
    return f"всего {count}; " + ("; ".join(parts) or "полей нет")


async def _follower_hrefs(page: Page) -> str:
    try:
        hrefs = await page.evaluate(
            """() => [...document.querySelectorAll('a[href]')]
                .map((el) => el.getAttribute('href') || '')
                .filter((href) => /follower|подпис/i.test(href))
                .slice(0, 6)"""
        )
    except Exception:
        return "не прочитаны"
    if not isinstance(hrefs, list) or not hrefs:
        return "нет"
    return ", ".join(str(item)[:80] for item in hrefs[:6])


async def _ensure_followers(page: Page, username: str) -> None:
    try:
        await _followers_dialog(page)
    except StopRun:
        await _open_followers(page, username)


async def _followers_dialog(page: Page):
    dialogs = page.get_by_role("dialog")
    count = await dialogs.count()
    fallback = None
    for index in range(count):
        dialog = dialogs.nth(index)
        if await dialog.locator(SEARCH_INPUT).count():
            return dialog
        if fallback is None and await dialog.locator(TEXT_INPUT).count():
            fallback = dialog
    if fallback is not None:
        return fallback
    raise StopRun("ui_changed")


async def _session_rejected(page: Page) -> bool:
    url = page.url.lower()
    if any(part in url for part in LOGIN_PARTS):
        return True
    if await page.locator("form#loginForm").count() > 0:
        return True
    password = page.locator("input[name='password']")
    return await password.count() > 0 and await password.first.is_visible()


async def _rate_limited(page: Page) -> bool:
    """Ищем текст ограничения в коротких окнах, а не в списке подписчиков.

    В списке встречаются биографии, и фраза оттуда не должна останавливать прогон.
    """
    try:
        title = await page.title()
    except Exception:
        title = ""
    if BLOCK_TEXT.search(title):
        return True
    alerts = page.locator("[role='alert']")
    try:
        alert_count = await alerts.count()
    except Exception:
        alert_count = 0
    for index in range(min(alert_count, 10)):
        text = await _short_text(alerts.nth(index))
        if BLOCK_TEXT.search(text):
            return True
    dialogs = page.get_by_role("dialog")
    try:
        dialog_count = await dialogs.count()
    except Exception:
        return False
    for index in range(dialog_count):
        dialog = dialogs.nth(index)
        try:
            if await dialog.locator("input").count():
                continue
            text = await _short_text(dialog)
        except Exception:
            continue
        if BLOCK_TEXT.search(text):
            return True
    return False


async def _short_text(locator) -> str:
    try:
        return (await locator.inner_text(timeout=1000))[:400]
    except Exception:
        return ""


async def _settle_profile(page: Page) -> None:
    await _dismiss_overlays(page)
    try:
        await page.locator("header, main").first.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeout:
        pass
    await _dismiss_overlays(page)


async def _dismiss_overlays(page: Page) -> None:
    labels = (
        "Allow all cookies",
        "Decline optional cookies",
        "Only allow essential cookies",
        "Not Now",
        "Не сейчас",
        "Отклонить необязательные файлы cookie",
        "Разрешить все cookie",
        "Принять все",
    )
    for label in labels:
        button = page.get_by_role("button", name=label)
        if await button.count() == 0:
            continue
        try:
            await button.first.click(timeout=1500)
        except Exception:
            continue

"""Тест снятия одного подписчика по сессии data/sessions/main.json.

Путь как в браузере: профиль, список подписчиков, поиск ника, кнопка удаления,
затем подтверждение. Между шагами пауза. После первого снятого ник скрипт
останавливается. Cookies и ответы сайта в лог не пишутся.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout, async_playwright

from services.instagram import _confirm_remove, _remove_control
from services.names import normalize_username
from services.reasons import safe_detail

SESSION = ROOT / "data" / "sessions" / "main.json"
LOG_PATH = ROOT / "data" / "logs" / "test_remove.log"
SHOTS = ROOT / "data" / "logs" / "test_shots"
TARGETS = (
    "____outlet____",
    "___albi_shop___",
    "___tamila___shop___",
    "__globalmarket__",
    "__lifemagazine__",
    "__magazin__pozitiv__",
    "__shoping___",
    "_automarket_",
    "_baby_time_shop_",
    "_cookies_sweet_shop",
    "_day_store_plus_",
    "_dubai_shop_nita",
    "_eva_kids_shop_",
    "_jess.shop_",
)
REMOVE_NAME = re.compile(r"^(Remove|Удалить)\b", re.IGNORECASE)
FOLLOWERS_NAME = re.compile(r"followers|подписчик", re.IGNORECASE)
LOGIN_PARTS = ("/accounts/login", "/challenge/", "checkpoint")

logger = logging.getLogger("test_remove")


def _setup_log() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream)


async def _pause(label: str, low: float = 8, high: float = 14) -> None:
    seconds = random.uniform(low, high)
    logger.info("пауза %.0f с — %s", seconds, label)
    await asyncio.sleep(seconds)


async def _shot(page: Page, name: str) -> None:
    path = SHOTS / f"{name}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
        logger.info("снимок %s", path.name)
    except Exception as exc:
        logger.info("снимок не сохранился: %s", type(exc).__name__)


def _login_wall(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in LOGIN_PARTS)


async def _dismiss(page: Page) -> None:
    for label in ("Не сейчас", "Not Now", "Отклонить необязательные файлы cookie"):
        button = page.get_by_role("button", name=label)
        if await button.count() == 0:
            continue
        try:
            await button.first.click(timeout=1500)
            logger.info("закрыто окно: %s", label)
            await _pause("окно закрыто", 2, 4)
        except Exception as exc:
            logger.info("окно «%s» не закрылось: %s", label, type(exc).__name__)


async def _username_from_page(page: Page) -> str | None:
    """Ссылка профиля в меню. Текст cookies сюда не попадает."""
    href = await page.evaluate(
        """() => {
            const label = [...document.querySelectorAll('a, span, div')].find((el) => {
                const clean = (el.textContent || '').trim();
                return clean === 'Переключиться' || clean === 'Switch';
            });
            if (!label) return '';
            let node = label.parentElement;
            for (let step = 0; step < 6 && node; step += 1) {
                const link = [...node.querySelectorAll('a[href]')].find((item) =>
                    /^\\/[A-Za-z0-9._]+\\/?$/.test(item.getAttribute('href') || '')
                );
                if (link) return link.getAttribute('href') || '';
                node = node.parentElement;
            }
            return '';
        }"""
    )
    logger.info("ссылка рядом с переключателем аккаунта: %s", href or "нет")
    hrefs = [href] if href else []
    for href in hrefs:
        username = normalize_username(str(href).strip("/"))
        if username and username not in {"explore", "reels", "direct", "accounts"}:
            logger.info("аккаунт сессии по ссылке: @%s", username)
            return username
    return None


async def _account_username(page: Page) -> str | None:
    """Ник владельца сессии. В лог уходит только ник или короткий статус."""
    await _dismiss(page)
    from_page = await _username_from_page(page)
    if from_page:
        return from_page
    result = await page.evaluate(
        """async () => {
            const pick = (name) => {
                const row = document.cookie.split('; ').find((item) => item.startsWith(name + '='));
                return row ? decodeURIComponent(row.slice(name.length + 1)) : '';
            };
            const id = pick('ds_user_id');
            if (!/^\\d+$/.test(id)) return { ok: false, why: 'no_id' };
            let response;
            try {
                response = await fetch(
                    'https://www.instagram.com/api/v1/users/' + encodeURIComponent(id) + '/info/',
                    {
                        credentials: 'include',
                        headers: {
                            'X-IG-App-ID': '936619743392459',
                            'X-CSRFToken': pick('csrftoken'),
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                    },
                );
            } catch (err) {
                return { ok: false, why: 'fetch' };
            }
            if (!response.ok) return { ok: false, why: 'http_' + response.status };
            let payload;
            try {
                payload = await response.json();
            } catch (err) {
                return { ok: false, why: 'json' };
            }
            const name = payload && payload.user && payload.user.username;
            if (typeof name !== 'string' || !name) return { ok: false, why: 'empty' };
            return { ok: true, username: name };
        }"""
    )
    if isinstance(result, dict) and result.get("ok"):
        username = normalize_username(str(result.get("username", "")))
        if username:
            logger.info("аккаунт сессии: @%s", username)
            return username
    why = result.get("why") if isinstance(result, dict) else "empty"
    logger.info("ник сессии через страницу не прочитан: %s", why)
    return None


async def _open_followers(page: Page, username: str) -> bool:
    url = f"https://www.instagram.com/{username}/"
    logger.info("открываю профиль %s", url)
    await page.goto(url, wait_until="domcontentloaded")
    await _pause("страница профиля открылась", 6, 10)
    logger.info("адрес после профиля: %s", page.url.split("?")[0])
    await _dismiss(page)
    if _login_wall(page.url):
        logger.info("вместо профиля страница входа или проверки")
        await _shot(page, "login")
        return False
    link = page.locator(
        f'a[href="/{username}/followers/"], a[href^="/{username}/followers/?"]'
    )
    count = await link.count()
    logger.info("ссылок на подписчиков по адресу: %s", count)
    if count == 0:
        link = page.get_by_role("link", name=FOLLOWERS_NAME)
        count = await link.count()
        logger.info("ссылок на подписчиков по подписи: %s", count)
    if count == 0:
        await _shot(page, "no_followers_link")
        return False
    href = await link.first.get_attribute("href")
    logger.info("кликаю подписчиков, href=%s", href)
    await link.first.click()
    await _pause("жду окно подписчиков", 4, 7)
    dialog = page.get_by_role("dialog")
    dialogs = await dialog.count()
    logger.info("окон dialog: %s, адрес: %s", dialogs, page.url.split("?")[0])
    if dialogs == 0:
        await _shot(page, "no_dialog")
        return False
    inputs = await _describe_inputs(dialog.first)
    logger.info("поиск в окне: %s", inputs)
    await _shot(page, "followers")
    return True


async def _describe_inputs(scope) -> str:
    inputs = scope.locator("input")
    count = await inputs.count()
    parts: list[str] = []
    for index in range(min(count, 5)):
        field = inputs.nth(index)
        placeholder = await field.get_attribute("placeholder") or ""
        label = await field.get_attribute("aria-label") or ""
        parts.append(f"[{index}] placeholder={placeholder!r} aria={label!r}")
    return f"всего {count}; " + ("; ".join(parts) or "полей нет")


async def _button_labels(scope, limit: int = 12) -> list[str]:
    buttons = scope.locator("button, [role='button']")
    count = await buttons.count()
    labels: list[str] = []
    for index in range(min(count, limit)):
        try:
            text = (await buttons.nth(index).inner_text(timeout=1000)).replace("\n", " ").strip()
        except Exception:
            text = ""
        if text:
            labels.append(text[:60])
    return labels


async def _search_box(page: Page):
    dialog = page.get_by_role("dialog").last
    box = dialog.locator(
        "input[aria-label='Search input'], input[placeholder='Search'], input[placeholder='Поиск']"
    )
    if await box.count() == 0:
        box = dialog.locator("input")
    if await box.count() == 0:
        return None
    return box.first


async def _try_one(page: Page, username: str) -> str:
    logger.info("--- ник %s ---", username)
    box = await _search_box(page)
    if box is None:
        logger.info("в окне подписчиков нет поля поиска")
        await _shot(page, f"no_search_{username[:20]}")
        return "error"
    await box.click()
    await box.press("Control+A")
    await box.press("Backspace")
    await box.press_sequentially(username, delay=80)
    logger.info("имя введено, жду строку в списке")
    await _pause("поиск по списку", 4, 7)
    dialog = page.get_by_role("dialog").last
    link = dialog.locator(
        f'a[href="/{username}/"], a[href^="/{username}/?"], '
        f'a[href="https://www.instagram.com/{username}/"], '
        f'a[href^="https://www.instagram.com/{username}/?"]'
    )
    try:
        await link.first.wait_for(state="visible", timeout=8000)
    except PlaywrightTimeout:
        labels = await _button_labels(dialog)
        logger.info("строка @%s не появилась. Кнопки окна: %s", username, labels[:8])
        await _shot(page, f"missing_{username[:20]}")
        return "not_found"
    logger.info("строка @%s видна", username)
    button = await _remove_control(link.first)
    if button is None:
        logger.info("кнопка «Удалить» в строке не найдена")
        await _shot(page, f"no_remove_{username[:20]}")
        return "not_found"
    label = (await button.inner_text()).replace("\n", " ").strip()
    logger.info("нажимаю кнопку %r", label[:40])
    await _pause("перед удалением", 3, 6)
    await button.click()
    await _pause("жду подтверждение", 2, 4)
    try:
        await _confirm_remove(page)
    except Exception as exc:
        logger.info("подтверждение не нажато: %s", safe_detail(exc))
        await _shot(page, f"no_confirm_{username[:20]}")
        return "error"
    logger.info("подписчик @%s снят", username)
    await _shot(page, f"removed_{username[:20]}")
    return "removed"


async def _confirm(page: Page) -> bool:
    deadline = asyncio.get_running_loop().time() + 8
    while asyncio.get_running_loop().time() < deadline:
        dialogs = page.get_by_role("dialog")
        count = await dialogs.count()
        logger.info("окон для подтверждения: %s", count)
        for index in range(count):
            dialog = dialogs.nth(index)
            if await dialog.locator("input").count():
                continue
            labels = await _button_labels(dialog)
            logger.info("окно без поиска, кнопки: %s", labels[:8])
            button = dialog.locator("button, [role='button']").filter(has_text=REMOVE_NAME)
            if await button.count() == 0:
                continue
            await button.first.click()
            logger.info("подтверждение нажато")
            try:
                await dialog.wait_for(state="hidden", timeout=8000)
            except PlaywrightTimeout:
                logger.info("окно подтверждения не закрылось")
                return False
            return True
        await asyncio.sleep(0.4)
    logger.info("окно подтверждения не появилось")
    return False


async def run() -> int:
    if not SESSION.is_file():
        logger.info("нет файла сессии %s", SESSION.name)
        return 1
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        try:
            context = await browser.new_context(
                storage_state=str(SESSION),
                viewport={"width": 1280, "height": 800},
                locale="ru-RU",
            )
            page = await context.new_page()
            page.set_default_timeout(20_000)
            logger.info("открываю ленту")
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            await _pause("лента загрузилась", 6, 10)
            logger.info("адрес: %s", page.url.split("?")[0])
            if _login_wall(page.url):
                logger.info("сессия не пускает: страница входа или проверки")
                await _shot(page, "login")
                return 2
            username = await _account_username(page)
            if not username:
                await _shot(page, "no_username")
                return 2
            if not await _open_followers(page, username):
                return 3
            for nick in TARGETS:
                parsed = normalize_username(nick)
                if parsed is None:
                    logger.info("ник %s не похож на имя Instagram, пропускаю", nick)
                    continue
                try:
                    status = await _try_one(page, parsed)
                except Exception as exc:
                    logger.info("сбой на @%s: %s", parsed, safe_detail(exc))
                    await _shot(page, f"error_{parsed[:20]}")
                    status = "error"
                if status == "removed":
                    logger.info("готово: снят один подписчик @%s", parsed)
                    return 0
                await _pause("перед следующим ником", 12, 18)
            logger.info("из списка никого снять не удалось")
            return 4
        finally:
            await browser.close()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    _setup_log()
    try:
        code = asyncio.run(run())
    except Exception as exc:
        logger.info("тест прерван: %s", safe_detail(exc))
        raise SystemExit(1) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()

"""Видимый браузер: ручной вход в Instagram и запись storage_state.

Запускается на машине с экраном, не как процесс контейнера бота.
Пароль вводится в окне сайта и в файл не попадает.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright

from services.names import safe_profile_name
from services.storage import validate_storage_state


async def save(name: str) -> None:
    safe_profile_name(name)
    destination = ROOT / "data" / "sessions" / f"{name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            print("Войдите в Instagram в открывшемся окне. Пароль скрипт не читает.")
            print("Когда откроется лента, вернитесь сюда и нажмите Enter.")
            await asyncio.to_thread(input, "")
            url = page.url.lower()
            if "/accounts/login" in url or "/challenge/" in url or "checkpoint" in url:
                print("Вход не завершён, файл не сохранён.")
                return
            temporary = destination.with_name(destination.name + ".part")
            await context.storage_state(path=str(temporary))
        finally:
            await browser.close()
    try:
        validate_storage_state(temporary)
    except ValueError as exc:
        temporary.unlink(missing_ok=True)
        print(str(exc))
        raise SystemExit(1) from exc
    temporary.replace(destination)
    print(f"Сессия записана: {destination}")
    print("Отправьте этот JSON боту кнопкой «Загрузить сессию».")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    name = sys.argv[1] if len(sys.argv) > 1 else "main"
    try:
        asyncio.run(save(name))
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

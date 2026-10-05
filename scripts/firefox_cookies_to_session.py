"""Собрать storage_state из cookies Firefox.

В инспекторе значение в колонке обрезано. Дважды щёлкните ячейку «Значение»,
затем Ctrl+A и Ctrl+C — так копируется строка целиком.
Скрипт пароль не спрашивает и введённое в консоль не пишет.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.names import safe_profile_name
from services.storage import validate_storage_state

# Порядок как в хранилище Firefox для instagram.com.
# httpOnly, secure, sameSite — по колонкам таблицы, не по значению.
COOKIE_FIELDS = (
    ("sessionid", True, True, "None"),
    ("csrftoken", False, True, "None"),
    ("ds_user_id", False, True, "None"),
    ("datr", False, True, "None"),
    ("ig_did", True, True, "None"),
    ("mid", False, True, "None"),
    ("rur", True, True, "Lax"),
    ("dpr", False, True, "None"),
    ("wd", False, True, "Lax"),
)


def _ask(name: str) -> str:
    print(f"{name}: вставьте значение и нажмите Enter")
    return input().strip()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    profile = sys.argv[1] if len(sys.argv) > 1 else "main"
    try:
        safe_profile_name(profile)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1) from exc

    print("Firefox: F12 → Хранилище → Куки → https://www.instagram.com")
    print("Двойной щелчок по ячейке «Значение», Ctrl+A, Ctrl+C.")
    print("Пустая строка — пропустить cookie. sessionid пропускать нельзя.")
    cookies = []
    for name, http_only, secure, same_site in COOKIE_FIELDS:
        value = _ask(name)
        if not value:
            if name == "sessionid":
                print("Без sessionid файл сессии не собрать.")
                raise SystemExit(1)
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".instagram.com",
                "path": "/",
                "expires": -1,
                "httpOnly": http_only,
                "secure": secure,
                "sameSite": same_site,
            }
        )

    destination = ROOT / "data" / "sessions" / f"{profile}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.write_text(
        json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        validate_storage_state(temporary)
    except ValueError as exc:
        temporary.unlink(missing_ok=True)
        print(str(exc))
        raise SystemExit(1) from exc
    temporary.replace(destination)
    print(f"Сессия записана: {destination}")
    print("Отправьте этот JSON боту кнопкой «Загрузить сессию».")


if __name__ == "__main__":
    main()

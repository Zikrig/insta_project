"""Настройки из .env. Логин и пароль Instagram здесь не читаются."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    report_hour: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    report_email: str
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.db"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def lists_dir(self) -> Path:
        return self.data_dir / "lists"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def report_marker(self) -> Path:
        return self.data_dir / "last_report_date.txt"


settings: Settings | None = None


def get_settings() -> Settings:
    if settings is None:
        raise RuntimeError("Настройки ещё не загружены")
    return settings


def load_settings() -> Settings:
    global settings
    load_dotenv(ROOT / ".env")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN пустой. Скопируйте .env.example в .env и заполните его.")

    raw_ids = os.getenv("ADMIN_IDS", "")
    admin_ids: set[int] = set()
    for part in raw_ids.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise SystemExit("ADMIN_IDS: укажите числовые id через запятую.")
        admin_ids.add(int(part))
    if not admin_ids:
        raise SystemExit("ADMIN_IDS пустой. Укажите хотя бы один Telegram id.")

    hour_raw = os.getenv("REPORT_HOUR", "9").strip()
    if not hour_raw.isdigit() or not 0 <= int(hour_raw) <= 23:
        raise SystemExit("REPORT_HOUR должен быть числом от 0 до 23.")

    port_raw = os.getenv("SMTP_PORT", "587").strip() or "587"
    if not port_raw.isdigit():
        raise SystemExit("SMTP_PORT должен быть числом.")

    data_dir = Path(os.getenv("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir

    settings = Settings(
        bot_token=token,
        admin_ids=frozenset(admin_ids),
        report_hour=int(hour_raw),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(port_raw),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        report_email=os.getenv("REPORT_EMAIL", "").strip(),
        data_dir=data_dir,
    )
    return settings


def ensure_dirs(current: Settings) -> None:
    for folder in (current.data_dir, current.sessions_dir, current.lists_dir, current.logs_dir):
        folder.mkdir(parents=True, exist_ok=True)

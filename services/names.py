"""Имена профилей и ников Instagram. Пароли сюда не попадают."""

from __future__ import annotations

import re

PROFILE_RE = re.compile(r"^[\w-]{1,40}$", re.UNICODE)
IG_USER_RE = re.compile(r"^[a-z0-9._]{1,30}$")
IG_ID_RE = re.compile(r"^\d{1,20}$")
LIST_NICK = "nick"
LIST_ID = "id"


def safe_profile_name(raw: str) -> str:
    name = raw.strip()
    if not PROFILE_RE.fullmatch(name) or name in {".", ".."}:
        raise ValueError(
            "Имя профиля: буквы, цифры, _ и -, от 1 до 40 символов, без пробелов и точек."
        )
    return name


def normalize_username(raw: str) -> str | None:
    text = str(raw).replace("\u00a0", " ").strip().lstrip("@").lower()
    if IG_USER_RE.fullmatch(text):
        return text
    return None


def normalize_user_id(raw: str) -> str | None:
    text = str(raw).strip()
    if IG_ID_RE.fullmatch(text):
        return text
    return None

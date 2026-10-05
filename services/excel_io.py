"""Чтение списка из Excel: первый столбец, со второй строки."""

from __future__ import annotations

from pathlib import Path

import openpyxl

from services.names import LIST_ID, LIST_NICK, normalize_user_id, normalize_username


def read_list(path: Path, kind: str) -> tuple[list[str], int]:
    """Вернуть уникальные значения и число отброшенных ячеек.

    Первая строка — шапка, её не читаем. Повтор того же значения берётся один раз.
    kind=nick — ник, kind=id — числовой id Instagram.
    """
    if kind not in {LIST_NICK, LIST_ID}:
        raise ValueError("Неизвестный режим списка")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows = sheet.iter_rows(min_row=2, min_col=1, max_col=1, values_only=True)
        values = [row[0] if row else None for row in rows]
    finally:
        workbook.close()

    ordered: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for value in values:
        text = _as_text(value)
        if not text:
            continue
        if kind == LIST_ID:
            parsed = normalize_user_id(text)
        else:
            parsed = normalize_username(text)
            # Сплошные цифры — это id, в режиме ников такую ячейку не берём.
            if parsed is not None and parsed.isdigit():
                parsed = None
        if parsed is None:
            skipped += 1
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        ordered.append(parsed)
    return ordered, skipped


def _as_text(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not value.is_integer():
            return ""
        return str(int(value))
    return str(value).replace("\u00a0", " ").strip()

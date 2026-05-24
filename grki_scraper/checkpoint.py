"""
Чекпоинты: возобновление парсинга без повторной обработки.

Файл checkpoint.json хранит:
  processed_reg_numbers — успешно выгруженные рег. номера
  listing_rows          — кэш строк списка (чтобы не ходить на сайт повторно)

Сохранение — после каждой успешной карточки (real-time checkpoint).
"""

import json
from pathlib import Path
from typing import Any


def load_checkpoint(path: Path) -> dict[str, Any]:
    """Загрузить чекпоинт или вернуть пустую структуру."""
    if not path.exists():
        return {"processed_reg_numbers": [], "listing_rows": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    """Сохранить текущий прогресс на диск."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_processed(checkpoint: dict[str, Any], reg_number: str) -> bool:
    """Проверить, обработан ли уже регистрационный номер."""
    return reg_number in checkpoint.get("processed_reg_numbers", [])


def mark_processed(checkpoint: dict[str, Any], reg_number: str) -> None:
    """Отметить регистрационный номер как успешно обработанный."""
    processed = checkpoint.setdefault("processed_reg_numbers", [])
    if reg_number not in processed:
        processed.append(reg_number)

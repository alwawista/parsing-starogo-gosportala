"""
Журнал ошибок парсера (errors.log).

Ошибка на одной карточке не останавливает весь прогон —
запись логируется здесь, обработка продолжается со следующей записи.
"""

from datetime import datetime
from pathlib import Path


def log_error(log_file: Path, reg_number: str, error_type: str, detail: str = "") -> None:
    """
    Записать ошибку обработки карточки в errors.log.

    Формат: [Дата/Время] — [Регистрационный номер] — [Тип ошибки]
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{timestamp}] — [{reg_number}] — [{error_type}]"
    if detail:
        message += f" — {detail}"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(message + "\n")

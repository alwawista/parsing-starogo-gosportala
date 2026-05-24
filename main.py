"""
Точка входа и оркестрация парсера ГРКИ (Росreestr).

Поток обработки одной записи:
  1. browser   — загрузка HTML (список / карточка)
  2. extractors — парсинг HTML в dataclass (без записи на диск)
  3. writers   — сериализация в CSV
  4. checkpoint — фиксация успеха; при сбое — log_error и переход к следующей

Режимы (config.SCRAPE_MODE):
  listing — первые N строк из таблицы реестра на сайте
  csv     — дополнение по рег. номерам из входного CSV
"""

from __future__ import annotations

import asyncio
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import config
from grki_scraper.browser import BrowserSession
from grki_scraper.checkpoint import is_processed, load_checkpoint, mark_processed, save_checkpoint
from grki_scraper.extractors.detail_extractor import extract_detail_card
from grki_scraper.extractors.list_extractor import ListRow, extract_list_rows
from grki_scraper.logger import log_error
from grki_scraper.writers.csv_writer import CsvWriter


@dataclass
class CsvInputRow:
    """Строка входного CSV для режима csv."""

    reg_number: str
    surname: str = ""
    name: str = ""
    patronymic: str = ""
    status: str = ""
    registration_date: str = ""
    person_id: int | None = None


def _read_csv_input(path: Path) -> list[CsvInputRow]:
    """Прочитать входной CSV с уже заполненными первыми 6 колонками."""
    rows: list[CsvInputRow] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            person_id_raw = row.get("person_id") or row.get("id") or ""
            person_id = int(person_id_raw) if str(person_id_raw).strip().isdigit() else None
            rows.append(
                CsvInputRow(
                    surname=row.get("фамилия", ""),
                    name=row.get("имя", ""),
                    patronymic=row.get("отчество", ""),
                    reg_number=str(row.get("регистрационный_номер", "")).strip(),
                    status=row.get("статус", ""),
                    registration_date=row.get("дата_регистрации", ""),
                    person_id=person_id,
                )
            )
    return rows


def _csv_row_to_list_row(item: CsvInputRow) -> ListRow:
    """Преобразовать строку CSV в ListRow для унифицированной записи."""
    full_name = " ".join(p for p in [item.surname, item.name, item.patronymic] if p)
    return ListRow(
        person_id=item.person_id or 0,
        full_name=full_name,
        reg_number=item.reg_number,
        status=item.status,
        cert_number_list="",
        membership_date_list=item.registration_date,
    )


async def collect_listing_rows(session: BrowserSession, limit: int) -> list[ListRow]:
    """
    Собрать первые `limit` строк из таблицы реестра с учётом пагинации.

    На сайте ~15 записей на страницу; переключаем страницы через setPage().
    """
    collected: list[ListRow] = []
    page_num = 1

    while len(collected) < limit:
        html = await session.goto_list_page(page_num)
        page_rows = extract_list_rows(html)
        if not page_rows:
            break

        for row in page_rows:
            collected.append(row)
            if len(collected) >= limit:
                break

        page_num += 1
        if page_num > 500:
            break
        await asyncio.sleep(config.DELAY_BETWEEN_PAGES_MS / 1000)

    return collected[:limit]


async def process_card(
    session: BrowserSession,
    list_row: ListRow,
    writer: CsvWriter,
    checkpoint: dict,
) -> bool:
    """
    Обработать одну карточку инженера (retry-safe).

    - Уже обработанные reg_number пропускаются (checkpoint).
    - При любой ошибке: запись в errors.log, return False, парсер идёт дальше.
    - При сетевой ошибке: попытка rotate_proxy() для следующих запросов.
    - Успех: запись в 4 CSV + save_checkpoint после каждой карточки.
    """
    reg_number = list_row.reg_number

    if is_processed(checkpoint, reg_number):
        print(f"  Пропуск (уже обработан): {reg_number}")
        return True

    if not list_row.person_id:
        log_error(config.ERROR_LOG_FILE, reg_number, "Parsing Error", "person_id не задан")
        return False

    try:
        html = await session.fetch_detail(list_row.person_id)
        detail = extract_detail_card(html)

        if not detail.general.cert_number and not detail.sro_history and not detail.professional_activity:
            log_error(config.ERROR_LOG_FILE, reg_number, "Parsing Error", "Карточка пуста или изменилась вёрстка")

        writer.write_all(list_row, detail)
        mark_processed(checkpoint, reg_number)
        save_checkpoint(config.CHECKPOINT_FILE, checkpoint)
        print(f"  OK: {reg_number} — {list_row.full_name}")
        return True

    except Exception as exc:
        error_type = type(exc).__name__
        if "Timeout" in error_type or "timeout" in str(exc).lower():
            error_type = "Timeout"
        elif "net::" in str(exc):
            error_type = f"HTTP / {exc}"

        log_error(config.ERROR_LOG_FILE, reg_number, error_type, str(exc))

        # Попытка сменить прокси при сетевой ошибке
        if config.PROXY_LIST and ("net::" in str(exc) or "Timeout" in error_type):
            try:
                await session.rotate_proxy()
            except Exception:
                pass

        print(f"  ОШИБКА: {reg_number} — {error_type}")
        return False


async def run_listing_mode(limit: int) -> None:
    """Тестовый/демо режим: первые N строк из таблицы реестра."""
    checkpoint = load_checkpoint(config.CHECKPOINT_FILE)
    writer = CsvWriter()
    session = BrowserSession()

    try:
        await session.start()
        print(f"Сбор списка инженеров (лимит: {limit})...")

        cached = checkpoint.get("listing_rows", [])
        if cached and len(cached) >= limit:
            list_rows = [ListRow(**row) for row in cached[:limit]]
        else:
            list_rows = await collect_listing_rows(session, limit)
            checkpoint["listing_rows"] = [
                {
                    "person_id": r.person_id,
                    "full_name": r.full_name,
                    "reg_number": r.reg_number,
                    "status": r.status,
                    "cert_number_list": r.cert_number_list,
                    "membership_date_list": r.membership_date_list,
                }
                for r in list_rows
            ]
            save_checkpoint(config.CHECKPOINT_FILE, checkpoint)

        print(f"Найдено {len(list_rows)} записей. Обработка карточек...")
        for idx, list_row in enumerate(list_rows, 1):
            print(f"[{idx}/{len(list_rows)}] {list_row.reg_number}")
            await process_card(session, list_row, writer, checkpoint)
            await session.delay_between_cards()

    finally:
        await session.close()


async def run_csv_mode(limit: int) -> None:
    """Полный режим: дополнение данных по входному CSV."""
    if not config.INPUT_CSV.exists():
        print(f"Входной файл не найден: {config.INPUT_CSV}")
        sys.exit(1)

    checkpoint = load_checkpoint(config.CHECKPOINT_FILE)
    writer = CsvWriter()
    session = BrowserSession()
    input_rows = _read_csv_input(config.INPUT_CSV)

    if limit > 0:
        input_rows = input_rows[:limit]

    try:
        await session.start()

        # Если person_id не указан во входном CSV — собираем маппинг с сайта
        need_mapping = any(r.person_id is None for r in input_rows)
        id_by_reg: dict[str, int] = {}

        if need_mapping:
            print("Построение маппинга рег. номер → person_id...")
            list_rows = await collect_listing_rows(session, max(limit, 1000) if limit else 5000)
            id_by_reg = {r.reg_number: r.person_id for r in list_rows}

        print(f"Обработка {len(input_rows)} записей из CSV...")
        for idx, item in enumerate(input_rows, 1):
            person_id = item.person_id or id_by_reg.get(item.reg_number)
            list_row = _csv_row_to_list_row(item)
            list_row.person_id = person_id or 0

            print(f"[{idx}/{len(input_rows)}] {item.reg_number}")
            await process_card(session, list_row, writer, checkpoint)
            await session.delay_between_cards()

    finally:
        await session.close()


async def main() -> None:
    """Запуск парсера согласно config.SCRAPE_MODE."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    limit = config.ROW_LIMIT
    mode = config.SCRAPE_MODE.lower()

    print("=" * 60)
    print("Парсер ГРКИ — Росreestr")
    print(f"Режим: {mode}, лимит: {limit or 'без ограничений'}")
    if config.OUTPUT_SUFFIX:
        print(f"Суффикс файлов: {config.OUTPUT_SUFFIX}")
    print("=" * 60)

    if mode == "csv":
        await run_csv_mode(limit)
    else:
        await run_listing_mode(limit)

    print("Готово. Результаты в:", config.OUTPUT_DIR)


if __name__ == "__main__":
    asyncio.run(main())

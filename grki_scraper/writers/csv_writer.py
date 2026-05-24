"""Запись результатов парсинга в CSV (отделён от extractors).

Заменяемый слой: для PostgreSQL достаточно реализовать аналог,
принимающий те же dataclass из extractors/.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

import config
from grki_scraper.extractors.detail_extractor import DetailCard, DisciplinaryRow, ProfessionalActivityRow, SroHistoryRow
from grki_scraper.extractors.list_extractor import ListRow, split_fio


class CsvWriter:
    """
    Потоковая запись в четыре связанных CSV-таблицы.

    После каждой успешно обработанной карточки данные дописываются на диск —
    это обеспечивает чекпоинтинг на уровне файлов.
    """

    @staticmethod
    def _normalize_cell(value) -> str:
        """
        Привести значение ячейки к строке для CSV.

        Отсутствие данных → пустая строка Python (""), без NaN/null/None
        в виде текстовых маркеров.
        """
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _create_writer(file) -> csv.writer:
        """
        CSV-writer с принудительным экранированием всех полей.

        QUOTE_ALL — каждое значение в двойных кавычках, чтобы точки с запятой
        и кавычки внутри текста (наименование СРО, основания и т.д.)
        не ломали структуру строки при импорте в PostgreSQL.
        """
        return csv.writer(
            file,
            delimiter=config.CSV_DELIMITER,
            quoting=csv.QUOTE_ALL,
            escapechar="\\",
            lineterminator="\n",
        )

    def __init__(self) -> None:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_headers()

    def _ensure_headers(self) -> None:
        """Создать CSV с заголовками, если файлы ещё не существуют."""
        files_columns = [
            (config.ENGINEERS_CSV, config.ENGINEERS_COLUMNS),
            (config.SRO_HISTORY_CSV, config.SRO_HISTORY_COLUMNS),
            (config.DISCIPLINARY_CSV, config.DISCIPLINARY_COLUMNS),
            (config.PROFESSIONAL_ACTIVITY_CSV, config.PROFESSIONAL_ACTIVITY_COLUMNS),
        ]
        for path, columns in files_columns:
            if not path.exists():
                with open(path, "w", encoding=config.CSV_ENCODING, newline="") as f:
                    self._create_writer(f).writerow(columns)

    @staticmethod
    def _write_row(path: Path, header: list[str], row: Iterable[str], mode: str = "a") -> None:
        write_header = mode == "w"
        with open(path, mode, encoding=config.CSV_ENCODING, newline="") as f:
            writer = CsvWriter._create_writer(f)
            if write_header:
                writer.writerow(header)
            writer.writerow([CsvWriter._normalize_cell(v) for v in row])

    def write_engineer(self, list_row: ListRow, detail: DetailCard) -> None:
        """Записать основную строку инженера (engineers.csv)."""
        surname, name, patronymic = split_fio(list_row.full_name)
        general = detail.general

        row = [
            surname,
            name,
            patronymic,
            list_row.reg_number,
            list_row.status,
            list_row.membership_date_list,
            general.cert_number or list_row.cert_number_list,
            general.cert_date,
            general.sro_reg_number,
            general.current_membership_date or list_row.membership_date_list,
        ]
        self._write_row(config.ENGINEERS_CSV, config.ENGINEERS_COLUMNS, row)

    def write_sro_history(self, reg_number: str, rows: list[SroHistoryRow]) -> None:
        """Записать историю членства в СРО."""
        for item in rows:
            self._write_row(
                config.SRO_HISTORY_CSV,
                config.SRO_HISTORY_COLUMNS,
                [
                    reg_number,
                    item.sro_name,
                    item.inclusion_date,
                    item.exclusion_date,
                    item.exclusion_reason,
                ],
            )

    def write_disciplinary(self, reg_number: str, rows: list[DisciplinaryRow]) -> None:
        """Записать дисциплинарные воздействия (если есть)."""
        for item in rows:
            self._write_row(
                config.DISCIPLINARY_CSV,
                config.DISCIPLINARY_COLUMNS,
                [
                    reg_number,
                    item.measure,
                    item.decision_date,
                    item.reason,
                    item.start_date,
                    item.end_date,
                ],
            )

    def write_professional_activity(self, reg_number: str, rows: list[ProfessionalActivityRow]) -> None:
        """Записать результаты профессиональной деятельности."""
        for item in rows:
            self._write_row(
                config.PROFESSIONAL_ACTIVITY_CSV,
                config.PROFESSIONAL_ACTIVITY_COLUMNS,
                [
                    reg_number,
                    item.year,
                    item.period,
                    item.decisions_total,
                    item.refusals_art27,
                    item.error_fix_decisions,
                    item.suspension_decisions,
                ],
            )

    def write_all(self, list_row: ListRow, detail: DetailCard) -> None:
        """Записать все таблицы для одного инженера."""
        self.write_engineer(list_row, detail)
        self.write_sro_history(list_row.reg_number, detail.sro_history)
        if detail.disciplinary:
            self.write_disciplinary(list_row.reg_number, detail.disciplinary)
        if detail.professional_activity:
            self.write_professional_activity(list_row.reg_number, detail.professional_activity)

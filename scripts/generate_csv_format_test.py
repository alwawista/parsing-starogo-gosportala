"""
Тестовые CSV (10–20 строк) для проверки кодировки, разделителя ; и кавычек.

  python -m scripts.generate_csv_format_test

Файлы: data/csv_format_test/*.csv
Отчёт: data/csv_format_validation.json
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import config
from grki_scraper.extractors.detail_extractor import (
    DetailCard,
    DisciplinaryRow,
    EngineerDetail,
    ProfessionalActivityRow,
    SroHistoryRow,
)
from grki_scraper.extractors.list_extractor import ListRow
from grki_scraper.writers.csv_writer import CsvWriter

OUT_DIR = config.DATA_DIR / "csv_format_test"
REPORT = config.DATA_DIR / "csv_format_validation.json"


def build_sample_rows() -> list[tuple[ListRow, DetailCard]]:
    """Синтетика + краевые случаи: ; и кавычки в тексте."""
    samples: list[tuple[ListRow, DetailCard]] = []

    edge_cases = [
        (
            ListRow(900001, "Тестов; Точказапятой", "99001", "включен в реестр", "01.01.2025", "01.01.2025"),
            DetailCard(
                general=EngineerDetail(cert_number="A;B", cert_date="01.01.2020"),
                sro_history=[
                    SroHistoryRow(
                        sro_name='Ассоциация "СРО; с разделителем"; ООО «Тест»',
                        inclusion_date="01.01.2020",
                        exclusion_reason="п. 1; п. 2; п. 3",
                    )
                ],
                disciplinary=[
                    DisciplinaryRow(
                        measure="Замечание",
                        decision_date="01.02.2024",
                        reason='Протокол № 1; раздел 2; подпункт "а"',
                    )
                ],
                professional_activity=[
                    ProfessionalActivityRow(year="2025", period="12", decisions_total="1"),
                ],
            ),
        ),
    ]

    # Реальные строки из production output (не из тестовых путей)
    engineers_path = config.DATA_DIR / "output" / "engineers.csv"
    if engineers_path.exists():
        with open(engineers_path, encoding=config.CSV_ENCODING, newline="") as f:
            reader = csv.DictReader(f, delimiter=config.CSV_DELIMITER)
            for i, row in enumerate(reader):
                if i >= 14:
                    break
                fio = " ".join(
                    p for p in [row.get("фамилия", ""), row.get("имя", ""), row.get("отчество", "")] if p
                )
                list_row = ListRow(
                    person_id=880000 + i,
                    full_name=fio,
                    reg_number=row.get("регистрационный_номер", ""),
                    status=row.get("статус", ""),
                    cert_number_list=row.get("номер_аттестата", ""),
                    membership_date_list=row.get("дата_регистрации", ""),
                )
                detail = DetailCard(
                    general=EngineerDetail(
                        cert_number=row.get("номер_аттестата", ""),
                        cert_date=row.get("дата_аттестата", ""),
                        sro_reg_number=row.get("реестровый_номер_СРО", ""),
                        current_membership_date=row.get("текущая_дата_членства_в_СРО", ""),
                    ),
                    sro_history=[
                        SroHistoryRow(
                            sro_name=f'СРО пример {i}; "кавычки"',
                            inclusion_date="01.01.2020",
                        )
                    ],
                    professional_activity=[
                        ProfessionalActivityRow(year="2024", period="4", decisions_total="0"),
                    ],
                )
                samples.append((list_row, detail))

    # Дополнить реальными строками из sro_history (там уже есть кавычки в названиях СРО)
    sro_path = config.DATA_DIR / "output" / "sro_history.csv"
    if sro_path.exists() and len(samples) < 15:
        with open(sro_path, encoding=config.CSV_ENCODING, newline="") as f:
            reader = csv.DictReader(f, delimiter=config.CSV_DELIMITER)
            for i, row in enumerate(reader):
                if i >= 15:
                    break
                reg = row.get("регистрационный_номер", "")
                samples.append(
                    (
                        ListRow(890000 + i, f"Инженер {reg}", reg, "включен в реестр", "", ""),
                        DetailCard(
                            sro_history=[
                                SroHistoryRow(
                                    sro_name=row.get("наименование_СРО", ""),
                                    inclusion_date=row.get("дата_включения", ""),
                                    exclusion_date=row.get("дата_исключения", ""),
                                    exclusion_reason=row.get("основание_исключения", ""),
                                )
                            ],
                        ),
                    )
                )

    return edge_cases + samples


def validate_csv_file(path: Path, expected_cols: int) -> dict:
    raw = path.read_text(encoding=config.CSV_ENCODING)
    has_bom = raw.startswith("\ufeff")

    issues = []
    rows_parsed: list[list[str]] = []
    with open(path, encoding=config.CSV_ENCODING, newline="") as f:
        reader = csv.reader(f, delimiter=config.CSV_DELIMITER, quoting=csv.QUOTE_MINIMAL)
        for i, row in enumerate(reader, 1):
            rows_parsed.append(row)
            if i > 1 and len(row) != expected_cols:
                issues.append({"line": i, "cols": len(row), "expected": expected_cols})

    # Все строки данных должны быть в двойных кавычках (QUOTE_ALL)
    data_lines = [ln for ln in raw.splitlines()[1:] if ln.strip()]
    unquoted_risk = sum(
        1
        for ln in data_lines
        if ";" in ln and not (ln.startswith('"') or ';"' in ln or ln.count('"') >= 2)
    )

    semicolon_in_fields = []
    for i, row in enumerate(rows_parsed[1:], 2):
        for cell in row:
            if ";" in cell:
                semicolon_in_fields.append({"line": i, "fragment": cell[:60]})

    return {
        "path": str(path),
        "encoding": config.CSV_ENCODING,
        "hasBom": has_bom,
        "dataRows": max(0, len(rows_parsed) - 1),
        "expectedColumns": expected_cols,
        "parseIssues": issues,
        "semicolonInsideFields": semicolon_in_fields,
        "linesMaybeUnquoted": unquoted_risk,
        "firstDataLinePreview": data_lines[0][:120] if data_lines else "",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Пути тестовых файлов
    paths = {
        "engineers": OUT_DIR / "engineers_test.csv",
        "sro": OUT_DIR / "sro_history_test.csv",
        "disciplinary": OUT_DIR / "disciplinary_actions_test.csv",
        "activity": OUT_DIR / "professional_activity_test.csv",
    }

    # Подмена config paths временно через прямую запись writer
    orig = (
        config.ENGINEERS_CSV,
        config.SRO_HISTORY_CSV,
        config.DISCIPLINARY_CSV,
        config.PROFESSIONAL_ACTIVITY_CSV,
    )
    config.ENGINEERS_CSV = paths["engineers"]
    config.SRO_HISTORY_CSV = paths["sro"]
    config.DISCIPLINARY_CSV = paths["disciplinary"]
    config.PROFESSIONAL_ACTIVITY_CSV = paths["activity"]
    config.OUTPUT_DIR = OUT_DIR

    writer = CsvWriter()

    for list_row, detail in build_sample_rows():
        writer.write_all(list_row, detail)

    config.ENGINEERS_CSV, config.SRO_HISTORY_CSV, config.DISCIPLINARY_CSV, config.PROFESSIONAL_ACTIVITY_CSV = orig

    report = {
        "quoting": "csv.QUOTE_ALL",
        "delimiter": config.CSV_DELIMITER,
        "encoding": config.CSV_ENCODING,
        "files": [
            validate_csv_file(paths["engineers"], len(config.ENGINEERS_COLUMNS)),
            validate_csv_file(paths["sro"], len(config.SRO_HISTORY_COLUMNS)),
            validate_csv_file(paths["disciplinary"], len(config.DISCIPLINARY_COLUMNS)),
            validate_csv_file(paths["activity"], len(config.PROFESSIONAL_ACTIVITY_COLUMNS)),
        ],
    }
    report["ok"] = all(
        not f["parseIssues"] for f in report["files"]
    )

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("CSV format test written to:", OUT_DIR)
    print("QUOTE_ALL + utf-8-sig + delimiter ';'")
    print("OK:", report["ok"])
    for f in report["files"]:
        print(
            f"  {Path(f['path']).name}: rows={f['dataRows']}, "
            f"semicolons in fields={len(f['semicolonInsideFields'])}, issues={len(f['parseIssues'])}"
        )
    print("Report:", REPORT)


if __name__ == "__main__":
    main()

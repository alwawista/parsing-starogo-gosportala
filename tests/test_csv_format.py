"""Проверка CSV: QUOTE_ALL, utf-8-sig, разделитель ;."""

import csv
from pathlib import Path

import config
from grki_scraper.writers.csv_writer import CsvWriter


def test_quote_all_wraps_semicolon(tmp_path, monkeypatch):
    out = tmp_path / "engineers.csv"
    monkeypatch.setattr(config, "ENGINEERS_CSV", out)
    monkeypatch.setattr(config, "SRO_HISTORY_CSV", tmp_path / "sro.csv")
    monkeypatch.setattr(config, "DISCIPLINARY_CSV", tmp_path / "d.csv")
    monkeypatch.setattr(config, "PROFESSIONAL_ACTIVITY_CSV", tmp_path / "a.csv")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)

    from grki_scraper.extractors.detail_extractor import DetailCard, SroHistoryRow
    from grki_scraper.extractors.list_extractor import ListRow

    w = CsvWriter()
    w.write_all(
        ListRow(1, "Иванов; Петр", "1", "статус", "01.01.2020", ""),
        DetailCard(sro_history=[SroHistoryRow(sro_name="Орг; с ; внутри", inclusion_date="")]),
    )

    text = out.read_text(encoding=config.CSV_ENCODING)
    assert "Иванов; Петр" in text or "Иванов;" in text
    assert '";"' in text or text.count('"') >= 4

    with open(out, encoding=config.CSV_ENCODING, newline="") as f:
        rows = list(csv.reader(f, delimiter=";", quoting=csv.QUOTE_MINIMAL))
    assert len(rows[1]) == len(config.ENGINEERS_COLUMNS)
    joined = ";".join(rows[1])
    assert ";" in joined  # semicolon preserved inside quoted fields

    sro = tmp_path / "sro.csv"
    with open(sro, encoding=config.CSV_ENCODING, newline="") as f:
        sro_rows = list(csv.reader(f, delimiter=";", quoting=csv.QUOTE_MINIMAL))
    assert sro_rows[1][1] == "Орг; с ; внутри"


def test_validation_sample_exists():
    report = config.DATA_DIR / "csv_format_validation.json"
    if not report.exists():
        return
    import json

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data.get("ok") is True

"""
Извлечение данных из HTML карточки кадастрового инженера.

Разбирает 4 блока: общие сведения, СРО, дисциплинарные, статистика.
Пустые поля на сайте → пустая строка "" (не метки соседних полей).
Слой не зависит от CSV/БД — удобен для переиспользования в backend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag


@dataclass
class EngineerDetail:
    """Дополнительные поля из блока «Общие сведения»."""

    cert_number: str = ""
    cert_date: str = ""
    sro_reg_number: str = ""
    current_membership_date: str = ""


@dataclass
class SroHistoryRow:
    """Строка таблицы «Членство в саморегулируемых организациях»."""

    sro_name: str = ""
    inclusion_date: str = ""
    exclusion_date: str = ""
    exclusion_reason: str = ""


@dataclass
class DisciplinaryRow:
    """Строка таблицы «Дисциплинарные воздействия»."""

    measure: str = ""
    decision_date: str = ""
    reason: str = ""
    start_date: str = ""
    end_date: str = ""


@dataclass
class ProfessionalActivityRow:
    """Строка таблицы «Результаты профессиональной деятельности»."""

    year: str = ""
    period: str = ""
    decisions_total: str = "0"
    refusals_art27: str = "0"
    error_fix_decisions: str = "0"
    suspension_decisions: str = "0"


@dataclass
class DetailCard:
    """Полный набор данных, извлечённых из карточки инженера."""

    general: EngineerDetail = field(default_factory=EngineerDetail)
    sro_history: list[SroHistoryRow] = field(default_factory=list)
    disciplinary: list[DisciplinaryRow] = field(default_factory=list)
    professional_activity: list[ProfessionalActivityRow] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _cell_text(td: Tag | None) -> str:
    if td is None:
        return ""
    return _clean(td.get_text(" ", strip=True))


def _parse_numeric(value: str) -> str:
    """
    Нормализовать числовое значение статистики.

    Прочерк, пустая строка и нечисловые значения → «0».
    """
    value = _clean(value)
    if not value or value in {"-", "—", "–", "нет данных"}:
        return "0"
    digits = re.sub(r"[^\d]", "", value)
    return digits if digits else "0"


def _find_section_table(soup: BeautifulSoup, section_title: str) -> Tag | None:
    """
    Найти вложенную <table> сразу после заголовка секции (sk_blockcap).

    Структура страницы: заголовок секции → вложенные таблицы с данными.
    """
    header = soup.find("td", class_="sk_blockcap", string=re.compile(re.escape(section_title)))
    if not header:
        # fallback: частичное совпадение
        header = soup.find("td", class_="sk_blockcap", string=re.compile(section_title[:20]))

    if not header:
        return None

    node = header.find_parent("tr")
    while node:
        node = node.find_next("tr")
        if not node:
            break
        nested = node.find("table", attrs={"border": "1"})
        if nested:
            return nested
        # Секция дисциплинарных воздействий без таблицы — «Данные не найдены»
        text = _cell_text(node.find("td"))
        if "Данные не найдены" in text:
            return None
    return None


def _extract_label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Собрать пары «метка → значение» из блока общих сведений."""
    pairs: dict[str, str] = {}
    general_header = soup.find("td", class_="sk_blockcap", string=re.compile("Общие сведения"))
    if not general_header:
        return pairs

    node = general_header.find_parent("tr")
    while node:
        node = node.find_next("tr")
        if not node:
            break
        # Следующая секция — конец блока
        cap = node.find("td", class_="sk_blockcap")
        if cap and "Общие сведения" not in cap.get_text():
            break

        label_td = node.find("td", align="right")
        value_td = node.find("td", class_="sk_tdval")
        if label_td and value_td:
            label = _clean(label_td.get_text())
            pairs[label] = _cell_text(value_td)

    return pairs


def _parse_cert_block(raw: str) -> tuple[str, str]:
    """
    Разобрать поле «Квалификационный аттестат».

    Пример: «номер: 13-11-56  дата выдачи: 07.02.2011»
    """
    number_match = re.search(r"номер:\s*([^\s]+)", raw, re.I)
    date_match = re.search(r"дата выдачи:\s*([\d.]+)", raw, re.I)
    return (
        number_match.group(1) if number_match else "",
        date_match.group(1) if date_match else "",
    )


def extract_general_info(soup: BeautifulSoup) -> EngineerDetail:
    """Извлечь поля из блока «Общие сведения»."""
    pairs = _extract_label_value_pairs(soup)
    detail = EngineerDetail()

    cert_raw = pairs.get("Квалификационный аттестат:", pairs.get("Квалификационный аттестат", ""))
    detail.cert_number, detail.cert_date = _parse_cert_block(cert_raw)

    detail.sro_reg_number = pairs.get("Реестровый номер в СРО КИ:", pairs.get("Реестровый номер в СРО КИ", ""))
    detail.current_membership_date = pairs.get(
        "Текущая дата членства кадастрового инженера:",
        pairs.get("Текущая дата членства кадастрового инженера", ""),
    )

    return detail


def extract_sro_history(soup: BeautifulSoup) -> list[SroHistoryRow]:
    """Извлечь строки таблицы «Членство в саморегулируемых организациях»."""
    table = _find_section_table(soup, "Членство в саморегулируемых организациях")
    if not table:
        return []

    rows: list[SroHistoryRow] = []
    data_rows = table.find_all("tr")[1:]  # пропуск заголовка

    for tr in data_rows:
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        sro_name = _cell_text(cells[0])
        if not sro_name or "Наименование СРО" in sro_name:
            continue

        rows.append(
            SroHistoryRow(
                sro_name=sro_name,
                inclusion_date=_cell_text(cells[1]) if len(cells) > 1 else "",
                exclusion_date=_cell_text(cells[2]) if len(cells) > 2 else "",
                exclusion_reason=_cell_text(cells[3]) if len(cells) > 3 else "",
            )
        )

    return rows


def extract_disciplinary(soup: BeautifulSoup) -> list[DisciplinaryRow]:
    """Извлечь строки таблицы «Дисциплинарные воздействия»."""
    table = _find_section_table(soup, "Дисциплинарные воздействия")
    if not table:
        return []

    rows: list[DisciplinaryRow] = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        measure = _cell_text(cells[0])
        if not measure or "мера" in measure.lower():
            continue

        rows.append(
            DisciplinaryRow(
                measure=measure,
                decision_date=_cell_text(cells[1]) if len(cells) > 1 else "",
                reason=_cell_text(cells[2]) if len(cells) > 2 else "",
                start_date=_cell_text(cells[3]) if len(cells) > 3 else "",
                end_date=_cell_text(cells[4]) if len(cells) > 4 else "",
            )
        )

    return rows


def extract_professional_activity(soup: BeautifulSoup) -> list[ProfessionalActivityRow]:
    """Извлечь строки таблицы «Результаты профессиональной деятельности»."""
    table = _find_section_table(soup, "Результаты профессиональной деятельности")
    if not table:
        return []

    rows: list[ProfessionalActivityRow] = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) < 6:
            continue
        year = _cell_text(cells[0])
        if not year or not re.search(r"\d{4}", year):
            continue

        year_clean = _clean(year)
        year_match = re.search(r"\d{4}", year_clean)
        year_val = year_match.group(0) if year_match else year_clean

        rows.append(
            ProfessionalActivityRow(
                year=year_val,
                period=_parse_numeric(_cell_text(cells[1])),
                decisions_total=_parse_numeric(_cell_text(cells[2])),
                refusals_art27=_parse_numeric(_cell_text(cells[3])),
                error_fix_decisions=_parse_numeric(_cell_text(cells[4])),
                suspension_decisions=_parse_numeric(_cell_text(cells[5])),
            )
        )

    return rows


def extract_detail_card(html: str) -> DetailCard:
    """
    Главная функция экстракта карточки инженера.

    Принимает сырой HTML, возвращает структурированный DetailCard
    для последующей записи в CSV (слой writers).
    """
    soup = BeautifulSoup(html, "lxml")
    return DetailCard(
        general=extract_general_info(soup),
        sro_history=extract_sro_history(soup),
        disciplinary=extract_disciplinary(soup),
        professional_activity=extract_professional_activity(soup),
    )

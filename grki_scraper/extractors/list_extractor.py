"""
Извлечение данных из HTML страницы списка инженеров.

Только парсинг — без I/O. Результат (ListRow) передаётся в writers
или используется для построения URL карточки (person_id).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class ListRow:
    """
    Строка таблицы реестра на главной странице.

    person_id — внутренний ID сайта (onclick='onEdit(826933)').
    reg_number — реестровый номер кадастрового инженера (связующий ключ CSV).
    """

    person_id: int
    full_name: str
    reg_number: str
    status: str
    cert_number_list: str
    membership_date_list: str


def split_fio(full_name: str) -> tuple[str, str, str]:
    """
    Разбить ФИО на фамилию, имя, отчество.

    Ожидаемый формат: «Фамилия Имя Отчество» (3 части).
    При нестандартном формате лишние части добавляются к отчеству.
    """
    parts = full_name.split()
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    if len(parts) == 1:
        return parts[0], "", ""
    return "", "", ""


def _clean_cell_text(td) -> str:
    """Очистить текст ячейки от лишних пробелов и переносов."""
    if td is None:
        return ""
    text = td.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_list_rows(html: str) -> list[ListRow]:
    """
    Распарсить HTML страницы списка и вернуть строки таблицы инженеров.

    Ищем <tr> с обработчиком onmouseover="changeLC(...)".
    """
    soup = BeautifulSoup(html, "lxml")
    rows: list[ListRow] = []

    for tr in soup.find_all("tr", onmouseover=re.compile(r"changeLC")):
        onclick = tr.find("td", onclick=re.compile(r"onEdit\(\d+\)"))
        if not onclick:
            continue

        match = re.search(r"onEdit\((\d+)\)", onclick.get("onclick", ""))
        if not match:
            continue

        person_id = int(match.group(1))
        cells = tr.find_all("td", class_="td")
        if len(cells) < 5:
            continue

        full_name = _clean_cell_text(cells[0])
        # Убираем артефакты от иконки user.gif
        full_name = re.sub(r"^\s*img\s*", "", full_name, flags=re.I).strip()

        rows.append(
            ListRow(
                person_id=person_id,
                full_name=full_name,
                reg_number=_clean_cell_text(cells[1]),
                status=_clean_cell_text(cells[2]),
                cert_number_list=_clean_cell_text(cells[3]),
                membership_date_list=_clean_cell_text(cells[4]),
            )
        )

    return rows

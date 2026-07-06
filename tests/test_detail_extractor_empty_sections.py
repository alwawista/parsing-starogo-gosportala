"""Проверка экстрактора на пустых/отсутствующих таблицах (без AttributeError)."""

from pathlib import Path

import pytest

from grki_scraper.extractors.detail_extractor import (
    extract_detail_card,
    extract_disciplinary,
    extract_professional_activity,
    extract_sro_history,
)

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "card_young_866551.html"

DISCIPLINE_EMPTY_HTML = """
<html><body><table>
<tr><td class="sk_blockcap">Дисциплинарные воздействия</td></tr>
<tr><td>Данные не найдены</td></tr>
</table></body></html>
"""

ACTIVITY_SMALL_HTML = """
<html><body><table>
<tr><td class="sk_blockcap">Результаты профессиональной деятельности</td></tr>
<tr><td><table border="1">
<tr><td>Год</td><td>Период</td><td>a</td><td>b</td><td>c</td><td>d</td></tr>
<tr><td>2025</td><td>12</td><td>1</td><td>0</td><td>0</td><td>0</td></tr>
</table></td></tr>
</table></body></html>
"""


def test_disciplinary_data_not_found_returns_empty_list():
    card = extract_detail_card(DISCIPLINE_EMPTY_HTML)
    assert card.disciplinary == []


def test_disciplinary_extractor_no_crash():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(DISCIPLINE_EMPTY_HTML, "lxml")
    assert extract_disciplinary(soup) == []


def test_activity_small_table():
    card = extract_detail_card(ACTIVITY_SMALL_HTML)
    assert len(card.professional_activity) == 1
    assert card.professional_activity[0].year == "2025"


@pytest.mark.skipif(not FIXTURE.exists(), reason="run rosreestr_empty_sections_probe first")
def test_young_engineer_fixture_from_site():
    html = FIXTURE.read_text(encoding="utf-8")
    card = extract_detail_card(html)

    assert len(card.sro_history) >= 1
    assert card.disciplinary == []
    assert len(card.professional_activity) == 2
    assert card.professional_activity[0].year in {"2025", "2026"}


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_young_fixture_disciplinary_has_no_data_table():
    from bs4 import BeautifulSoup

    from grki_scraper.extractors.detail_extractor import _find_section_table

    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "lxml")
    assert _find_section_table(soup, "Дисциплинарные воздействия") is None
    assert _find_section_table(soup, "Результаты профессиональной деятельности") is not None

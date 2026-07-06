"""
Проверка Фазы 1: поиск person_id по регистрационному номеру в реестре.

  python rosreestr_mapping_probe.py
  python rosreestr_mapping_probe.py --reg-number "КИ-12345"

Результат: data/mapping_probe_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

import config
from grki_scraper.extractors.list_extractor import extract_list_rows

REPORT = config.DATA_DIR / "mapping_probe_report.json"


def find_search_ui(html: str) -> dict:
    """Найти формы/поля поиска и фильтра на странице списка."""
    soup = BeautifulSoup(html, "lxml")
    forms = []
    for form in soup.find_all("form"):
        forms.append(
            {
                "name": form.get("name", ""),
                "id": form.get("id", ""),
                "action": form.get("action", ""),
                "method": form.get("method", "get").lower(),
                "inputs": [
                    {
                        "name": inp.get("name", ""),
                        "type": inp.get("type", "text"),
                        "id": inp.get("id", ""),
                        "value": (inp.get("value") or "")[:80],
                    }
                    for inp in form.find_all(["input", "select", "textarea"])
                ],
            }
        )

    keywords = ("поиск", "search", "filter", "номер", "registr", "реестр")
    text_hits = []
    for el in soup.find_all(string=re.compile("|".join(keywords), re.I)):
        parent = el.parent
        if parent and parent.name in ("label", "span", "td", "th", "button"):
            text_hits.append(_clean(parent.get_text(" ", strip=True))[:120])

    return {
        "formCount": len(forms),
        "forms": forms[:20],
        "keywordSnippets": list(dict.fromkeys(text_hits))[:25],
    }


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def find_person_id_by_reg(html: str, reg_number: str) -> list[dict]:
    """Извлечь person_id из таблицы, если reg_number есть в строке."""
    rows = extract_list_rows(html)
    reg_norm = reg_number.strip().lower()
    hits = []
    for r in rows:
        if reg_norm in r.reg_number.lower() or r.reg_number.lower() in reg_norm:
            hits.append(
                {
                    "person_id": r.person_id,
                    "reg_number": r.reg_number,
                    "full_name": r.full_name,
                }
            )
    return hits


async def try_js_search(page, reg_number: str) -> dict:
    """Попытки поиска через известные JS-хуки портала."""
    attempts = []

    # 1) setFilter / searchPerson / filterTable — частые имена на портлетах
    js_attempts = [
        ("setFilter_regNumber", f"() => {{ if (typeof setFilter === 'function') setFilter('regNumber', '{reg_number}'); }}"),
        ("setFilter_personRegNumber", f"() => {{ if (typeof setFilter === 'function') setFilter('personRegNumber', '{reg_number}'); }}"),
        ("doSearch", f"() => {{ if (typeof doSearch === 'function') doSearch('{reg_number}'); }}"),
        ("search", f"() => {{ if (typeof search === 'function') search('{reg_number}'); }}"),
    ]

    for name, js in js_attempts:
        try:
            await page.evaluate(js)
            await asyncio.sleep(2)
            html = await page.content()
            hits = find_person_id_by_reg(html, reg_number)
            attempts.append({"method": name, "hits": hits, "rowCount": len(extract_list_rows(html))})
        except Exception as e:
            attempts.append({"method": name, "error": str(e)})

    return attempts


async def try_form_fill(page, reg_number: str) -> dict:
    """Заполнить видимые поля с «номер» в name/id."""
    results = []
    selectors = [
        "input[name*='reg']",
        "input[name*='Reg']",
        "input[name*='number']",
        "input[name*='Number']",
        "input[id*='reg']",
        "input[type='text']",
    ]

    for sel in selectors:
        loc = page.locator(sel)
        count = await loc.count()
        if count == 0:
            continue
        for i in range(min(count, 5)):
            el = loc.nth(i)
            try:
                if not await el.is_visible(timeout=500):
                    continue
                name = await el.get_attribute("name") or await el.get_attribute("id") or sel
                await el.fill(reg_number)
                await asyncio.sleep(0.3)
                # Enter или кнопка рядом
                await el.press("Enter")
                await asyncio.sleep(2)
                html = await page.content()
                hits = find_person_id_by_reg(html, reg_number)
                results.append(
                    {
                        "selector": sel,
                        "field": name,
                        "hits": hits,
                        "rowCount": len(extract_list_rows(html)),
                    }
                )
                if hits:
                    return {"filledField": name, "attempts": results}
            except Exception:
                continue

    return {"filledField": None, "attempts": results}


async def search_by_filter_form(page, reg_number: str) -> dict:
    """POST filterForm.regNum + onFilter('set') → person_list.do."""
    await page.goto(config.LIST_URL, wait_until=config.NAVIGATION_WAIT, timeout=120000)
    await asyncio.sleep(config.POST_LOAD_DELAY_MS / 1000)

    async with page.expect_navigation(
        wait_until=config.NAVIGATION_WAIT,
        timeout=config.PAGE_LOAD_TIMEOUT_MS,
    ):
        await page.evaluate(
            """(reg) => {
                const f = document.forms['filterForm'];
                if (!f) throw new Error('filterForm not found');
                f.regNum.value = reg;
                if (typeof onFilter === 'function') {
                    onFilter('set');
                } else {
                    f.submit();
                }
            }""",
            reg_number,
        )
    await asyncio.sleep(config.POST_LOAD_DELAY_MS / 1000)
    html = await page.content()
    rows = extract_list_rows(html)
    exact = [r for r in rows if r.reg_number.strip() == reg_number.strip()]
    return {
        "method": "filterForm.regNum + onFilter('set')",
        "endpoint": "QCB2fperson_list.do== (POST)",
        "rowCount": len(rows),
        "exactMatches": [
            {"person_id": r.person_id, "reg_number": r.reg_number, "full_name": r.full_name}
            for r in exact
        ],
        "partialRows": [
            {"person_id": r.person_id, "reg_number": r.reg_number}
            for r in rows
            if r not in exact
        ],
        "needsExactFilter": len(rows) != len(exact),
    }


async def run_probe(reg_number: str | None) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)
        page = await browser.new_page(
            locale="ru-RU",
            ignore_https_errors=config.IGNORE_HTTPS_ERRORS,
        )

        await page.goto(config.LIST_URL, wait_until=config.NAVIGATION_WAIT, timeout=120000)
        await asyncio.sleep(config.POST_LOAD_DELAY_MS / 1000)
        list_html = await page.content()

        baseline_rows = extract_list_rows(list_html)
        sample_reg = reg_number
        if not sample_reg and baseline_rows:
            sample_reg = baseline_rows[0].reg_number
        if not sample_reg:
            sample_reg = "00000"

        report = {
            "probedAt": datetime.now(timezone.utc).isoformat(),
            "listUrl": config.LIST_URL,
            "sampleRegNumber": sample_reg,
            "baselineRowCount": len(baseline_rows),
            "baselineSample": [
                {"person_id": r.person_id, "reg_number": r.reg_number, "name": r.full_name}
                for r in baseline_rows[:3]
            ],
            "searchUi": find_search_ui(list_html),
            "inBaselineTable": find_person_id_by_reg(list_html, sample_reg),
            "formFillSearch": None,
            "jsSearch": None,
            "paginationNote": "person_id доступен в onclick onEdit(N) в <tr> таблицы",
        }

        # Поиск через встроенный filterForm (главный путь Фазы 1)
        report["filterFormSearch"] = await search_by_filter_form(page, sample_reg)

        # Доп. тест: person_id 824174 — это НЕ рег. номер (рег. 23120 → id 824174)
        report["filterFormSearch23120"] = await search_by_filter_form(page, "23120")

        ff = report["filterFormSearch"]
        if ff.get("exactMatches"):
            report["verdict"] = (
                "FILTER_FORM_OK: POST filterForm.regNum -> HTML таблицы person_list.do; "
                "person_id берется из onEdit(N) через extract_list_rows() - в карточку заходить не нужно. "
                "При частичных совпадениях фильтровать exact match по колонке reg_number."
            )
        elif report["inBaselineTable"]:
            report["verdict"] = (
                "BS4_FROM_TABLE: person_id в onEdit(ID) на странице списка без фильтра; "
                "для остальных номеров — filterForm.regNum."
            )
        else:
            report["formFillSearch"] = await try_form_fill(page, sample_reg)
            report["jsSearch"] = await try_js_search(page, sample_reg)
            report["verdict"] = (
                "FALLBACK_PAGINATION: filterForm не дал exact match; резерв — обход setPage() "
                "и сбор id_map.json."
            )

        # Сохранить HTML фрагмент с onEdit для документации
        soup = BeautifulSoup(list_html, "lxml")
        tr = soup.find("tr", onmouseover=re.compile(r"changeLC"))
        if tr:
            onclick_td = tr.find("td", onclick=re.compile(r"onEdit"))
            report["htmlSnippet"] = str(onclick_td)[:400] if onclick_td else str(tr)[:400]

        await browser.close()
        return report


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reg-number", default="")
    args = parser.parse_args()

    report = await run_probe(args.reg_number.strip() or None)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== MAPPING PROBE ===")
    print(f"Sample reg: {report['sampleRegNumber']}")
    print(f"Baseline rows on page 1: {report['baselineRowCount']}")
    print(f"In baseline: {report['inBaselineTable']}")
    print(f"Forms on page: {report['searchUi']['formCount']}")
    print(f"\nVERDICT: {report['verdict']}")
    print(f"Report -> {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())

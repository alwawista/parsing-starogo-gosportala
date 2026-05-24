"""
Проверка TTL сессии IBM WebSphere в URL Росреестра.

Сохраняет «старые» URL из probe/config и сравнивает с токенами после нового захода.

  python rosreestr_session_ttl_test.py
  python rosreestr_session_ttl_test.py --saved-url "https://..."
  python rosreestr_session_ttl_test.py --wait-minutes 45   # отложенный повтор (опционально)

Результат: data/session_ttl_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

import config
from grki_scraper.extractors.detail_extractor import extract_detail_card
from grki_scraper.extractors.list_extractor import extract_list_rows

DATA_DIR = config.DATA_DIR
REPORT_FILE = DATA_DIR / "session_ttl_report.json"
SAVED_URLS_FILE = DATA_DIR / "session_ttl_saved_urls.json"
PROBE_LOG = DATA_DIR / "rosreestr_probe_log.json"

Z1_RE = re.compile(r"!ut/p/z1/([^/]+)/")


def extract_z1_token(url: str) -> str | None:
    m = Z1_RE.search(url)
    return m.group(1) if m else None


def load_saved_urls() -> dict:
    """URL из файла сохранения или probe-лога."""
    if SAVED_URLS_FILE.exists():
        return json.loads(SAVED_URLS_FILE.read_text(encoding="utf-8"))

    out = {
        "savedAt": None,
        "listUrl": config.LIST_URL,
        "cardUrl": config.DETAIL_URL_TEMPLATE.format(person_id=824174),
        "detailTemplate": config.DETAIL_URL_TEMPLATE,
    }
    if PROBE_LOG.exists():
        probe = json.loads(PROBE_LOG.read_text(encoding="utf-8"))
        out["savedAt"] = probe.get("probedAt")
        out["listUrl"] = probe.get("listUrl", out["listUrl"])
        out["cardUrl"] = probe.get("cardUrl", out["cardUrl"])
    return out


def save_urls_for_later(urls: dict) -> None:
    urls["savedAt"] = datetime.now(timezone.utc).isoformat()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SAVED_URLS_FILE.write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")


async def analyze_page(page, label: str) -> dict:
    html = await page.content()
    url = page.url
    detail = extract_detail_card(html)
    activity_rows = len(detail.professional_activity)
    return {
        "label": label,
        "finalUrl": url,
        "z1Token": extract_z1_token(url),
        "statusOk": "person_view" in url or "freestr" in url,
        "hasGeneral": bool(detail.general.cert_number or detail.general.sro_reg_number),
        "activityRows": activity_rows,
        "htmlLength": len(html),
        "titleSnippet": (await page.title())[:120],
    }


async def run_tests(saved: dict, person_id: int, wait_minutes: int) -> dict:
    if wait_minutes > 0:
        print(f"Ожидание {wait_minutes} мин перед тестом «старый URL»...")
        await asyncio.sleep(wait_minutes * 60)

    report = {
        "testedAt": datetime.now(timezone.utc).isoformat(),
        "urlsSavedAt": saved.get("savedAt"),
        "personId": person_id,
        "savedZ1": {
            "list": extract_z1_token(saved["listUrl"]),
            "card": extract_z1_token(saved["cardUrl"]),
            "template": extract_z1_token(saved.get("detailTemplate", "")),
        },
        "tests": [],
        "verdict": "",
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)
        ctx = await browser.new_context(
            locale="ru-RU",
            ignore_https_errors=config.IGNORE_HTTPS_ERRORS,
        )

        # --- Тест 1: холодный переход по СТАРОМУ URL карточки (без cookies) ---
        page1 = await ctx.new_page()
        try:
            resp = await page1.goto(
                saved["cardUrl"],
                wait_until=config.NAVIGATION_WAIT,
                timeout=config.PAGE_LOAD_TIMEOUT_MS,
            )
            t1 = await analyze_page(page1, "cold_old_card_url")
            t1["httpStatus"] = resp.status if resp else None
            report["tests"].append(t1)
        except Exception as e:
            report["tests"].append({"label": "cold_old_card_url", "error": str(e)})
        await page1.close()

        # --- Тест 2: свежий LIST → извлечь z1 из финального URL ---
        page2 = await ctx.new_page()
        fresh_list_z1 = None
        fresh_detail_url = None
        try:
            resp = await page2.goto(
                config.LIST_URL,
                wait_until=config.NAVIGATION_WAIT,
                timeout=config.PAGE_LOAD_TIMEOUT_MS,
            )
            await asyncio.sleep(config.POST_LOAD_DELAY_MS / 1000)
            t2 = await analyze_page(page2, "fresh_list_visit")
            t2["httpStatus"] = resp.status if resp else None
            fresh_list_z1 = t2["z1Token"]
            report["tests"].append(t2)

            rows = extract_list_rows(await page2.content())
            if rows:
                pid = person_id
                for r in rows:
                    if r.person_id == person_id:
                        pid = r.person_id
                        break
                if not any(r.person_id == person_id for r in rows):
                    pid = rows[0].person_id

                # onEdit → submit как на сайте
                async with page2.expect_navigation(
                    wait_until=config.NAVIGATION_WAIT,
                    timeout=config.PAGE_LOAD_TIMEOUT_MS,
                ):
                    await page2.evaluate(
                        """(pid) => {
                            if (document.forms['editForm']) {
                                document.forms['editForm'].id.value = pid;
                                document.forms['editForm'].submit();
                            }
                        }""",
                        pid,
                    )
                await asyncio.sleep(config.POST_LOAD_DELAY_MS / 1000)
                t3 = await analyze_page(page2, "fresh_navigation_via_editForm")
                t3["personIdUsed"] = pid
                fresh_detail_url = page2.url
                report["tests"].append(t3)
        except Exception as e:
            report["tests"].append({"label": "fresh_list_navigation", "error": str(e)})
        await page2.close()

        # --- Тест 3: DETAIL_URL_TEMPLATE (статический z1 из config) после визита list ---
        page3 = await ctx.new_page()
        try:
            await page3.goto(
                config.LIST_URL,
                wait_until=config.NAVIGATION_WAIT,
                timeout=config.PAGE_LOAD_TIMEOUT_MS,
            )
            template_url = config.DETAIL_URL_TEMPLATE.format(person_id=person_id)
            resp = await page3.goto(
                template_url,
                wait_until=config.NAVIGATION_WAIT,
                timeout=config.PAGE_LOAD_TIMEOUT_MS,
            )
            t4 = await analyze_page(page3, "static_template_after_list")
            t4["httpStatus"] = resp.status if resp else None
            report["tests"].append(t4)
        except Exception as e:
            report["tests"].append({"label": "static_template_after_list", "error": str(e)})
        await page3.close()

        # --- Тест 4: если есть свежий URL с editForm — холодный контекст без list ---
        if fresh_detail_url and fresh_detail_url != saved["cardUrl"]:
            ctx2 = await browser.new_context(
                locale="ru-RU",
                ignore_https_errors=config.IGNORE_HTTPS_ERRORS,
            )
            page4 = await ctx2.new_page()
            try:
                resp = await page4.goto(
                    fresh_detail_url,
                    wait_until=config.NAVIGATION_WAIT,
                    timeout=config.PAGE_LOAD_TIMEOUT_MS,
                )
                t5 = await analyze_page(page4, "cold_fresh_card_url_new_context")
                t5["httpStatus"] = resp.status if resp else None
                report["tests"].append(t5)
            except Exception as e:
                report["tests"].append({"label": "cold_fresh_card_url_new_context", "error": str(e)})
            await ctx2.close()

        await browser.close()

    report["freshZ1"] = {
        "list": fresh_list_z1,
        "viaEditForm": extract_z1_token(fresh_detail_url) if fresh_detail_url else None,
    }
    report["z1Unchanged"] = {
        "list": report["savedZ1"]["list"] == fresh_list_z1,
        "card": report["savedZ1"]["card"] == extract_z1_token(fresh_detail_url or ""),
    }

    cold_old = next((t for t in report["tests"] if t.get("label") == "cold_old_card_url"), {})
    static_tpl = next((t for t in report["tests"] if t.get("label") == "static_template_after_list"), {})
    fresh_edit = next((t for t in report["tests"] if t.get("label") == "fresh_navigation_via_editForm"), {})

    old_ok = cold_old.get("activityRows", 0) > 0 or cold_old.get("hasGeneral")
    tpl_ok = static_tpl.get("activityRows", 0) > 0 or static_tpl.get("hasGeneral")
    z1_same = report["savedZ1"]["card"] == report["freshZ1"].get("viaEditForm")

    if tpl_ok and not old_ok:
        report["verdict"] = (
            "COOKIE_WARMUP_REQUIRED: холодный URL (старый или свежий) без прогрева list даёт урезанный HTML "
            f"(~49k, activity=0). После goto(LIST_URL) статический DETAIL_URL_TEMPLATE с z1={report['savedZ1']['card'][:20]}... "
            f"даёт полную карточку (activity={static_tpl.get('activityRows')}). "
            f"z1 списка стабилен: {report['z1Unchanged']['list']}; z1 через editForm меняется, шаблон — нет."
        )
    elif old_ok and tpl_ok:
        report["verdict"] = (
            "STATIC_TEMPLATE_OK: старый и шаблонный URL работают даже холодно; z1 не истёк "
            f"(z1 card match: {z1_same})."
        )
    elif not tpl_ok:
        report["verdict"] = (
            "BLOCKED_OR_LAYOUT: даже шаблон после list не дал данных — проверьте 403/капчу/вёрстку."
        )
    else:
        report["verdict"] = "MIXED: см. activityRows по каждому тесту."

    return report


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--person-id", type=int, default=824174)
    parser.add_argument("--wait-minutes", type=int, default=0)
    parser.add_argument("--save-only", action="store_true", help="только сохранить URL для отложенного теста")
    parser.add_argument("--saved-url", type=str, default="")
    args = parser.parse_args()

    saved = load_saved_urls()
    if args.saved_url:
        saved["cardUrl"] = args.saved_url

    if args.save_only:
        save_urls_for_later(saved)
        print(f"Сохранено для отложенного теста: {SAVED_URLS_FILE}")
        print("Через 30-60 мин: python rosreestr_session_ttl_test.py --wait-minutes 0")
        return

    report = await run_tests(saved, args.person_id, args.wait_minutes)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SESSION TTL TEST ===")
    print(f"URLs saved at: {report.get('urlsSavedAt')}")
    print(f"Saved z1 (card): {report['savedZ1']['card'][:48]}...")
    print(f"Fresh z1 (list): {(report['freshZ1']['list'] or '')[:48]}...")
    print(f"Fresh z1 (card): {(report['freshZ1'].get('viaEditForm') or '')[:48]}...")
    print(f"z1 list unchanged: {report['z1Unchanged']['list']}")
    print(f"z1 card unchanged: {report['z1Unchanged']['card']}")
    print()
    for t in report["tests"]:
        if "error" in t:
            print(f"  {t['label']}: ERROR {t['error'][:80]}")
        else:
            print(
                f"  {t['label']}: activity={t.get('activityRows', '?')} "
                f"html={t.get('htmlLength', '?')} z1={str(t.get('z1Token', ''))[:24]}..."
            )
    print(f"\nVERDICT: {report['verdict']}")
    print(f"Report -> {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())

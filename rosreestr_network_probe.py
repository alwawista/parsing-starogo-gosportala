"""
Перехват сети Росреестра + проверка прямого replay без UI.

  python rosreestr_network_probe.py
  python rosreestr_network_probe.py --person-id 824174 --replay
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Request, Response, async_playwright

import config

DATA_DIR = config.DATA_DIR
PROBE_LOG = DATA_DIR / "rosreestr_probe_log.json"

TRASH = ("/themeModules/", ".gif", ".png", ".jpg", ".woff", "yandex.ru")
API_HINTS = (
    "contenthandler",
    ".do==",
    "spf_ActionListener",
    "person_view",
    "freestr.do",
)


@dataclass
class NetEntry:
    phase: str
    method: str
    url: str
    resource_type: str = ""
    status: int | None = None
    content_type: str = ""
    post_data: str | None = None
    referer: str = ""
    body_preview: str = ""
    score: int = 0


def is_interesting(req: Request) -> bool:
    url = req.url
    if any(t in url for t in TRASH):
        return False
    if req.resource_type in ("xhr", "fetch"):
        return True
    if req.method == "POST":
        return True
    return any(h in url for h in API_HINTS)


def score_entry(e: NetEntry) -> int:
    s = 0
    if e.resource_type in ("xhr", "fetch"):
        s += 3
    if e.method == "POST":
        s += 2
    if "person_view" in e.url:
        s += 5
    if ".do==" in e.url:
        s += 3
    if e.post_data:
        s += 2
    if "Результаты профессиональной" in e.body_preview:
        s += 4
    if "sk_blockcap" in e.body_preview:
        s += 2
    return s


async def run_probe(person_id: int, headless: bool, wait_sec: int) -> dict:
    card_url = config.DETAIL_URL_TEMPLATE.format(person_id=person_id)
    captured: list[NetEntry] = []
    seen: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="ru-RU",
            ignore_https_errors=config.IGNORE_HTTPS_ERRORS,
        )
        page = await context.new_page()

        async def on_response(response: Response) -> None:
            req = response.request
            if not is_interesting(req):
                return
            key = f"resp|{req.method}|{response.url}|{response.status}"
            if key in seen:
                return
            seen.add(key)

            body_preview = ""
            ctype = response.headers.get("content-type", "")
            try:
                if any(x in ctype for x in ("text", "json", "xml", "html")):
                    body_preview = (await response.text())[:800]
            except Exception:
                pass

            entry = NetEntry(
                phase="response",
                method=req.method,
                url=response.url,
                resource_type=req.resource_type,
                status=response.status,
                content_type=ctype,
                post_data=req.post_data,
                referer=req.headers.get("referer", ""),
                body_preview=body_preview,
            )
            entry.score = score_entry(entry)
            captured.append(entry)

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        await page.goto(config.LIST_URL, wait_until=config.NAVIGATION_WAIT, timeout=120000)
        await asyncio.sleep(2)
        await page.goto(card_url, wait_until=config.NAVIGATION_WAIT, timeout=120000)
        await asyncio.sleep(3)

        tab_clicked = False
        for label in (
            "Результаты профессиональной деятельности",
            "Результаты деятельности",
        ):
            loc = page.get_by_text(label, exact=False).first
            if await loc.is_visible(timeout=2000):
                await loc.click()
                tab_clicked = True
                break

        await asyncio.sleep(wait_sec)
        html = await page.content()
        cookies = await context.cookies()
        final_url = page.url
        await browser.close()

    ranked = sorted(captured, key=lambda e: e.score, reverse=True)
    return {
        "probedAt": datetime.now(timezone.utc).isoformat(),
        "personId": person_id,
        "listUrl": config.LIST_URL,
        "cardUrl": card_url,
        "tabClicked": tab_clicked,
        "finalUrl": final_url,
        "pageHasActivitySection": "Результаты профессиональной деятельности" in html,
        "cookieCount": len(cookies),
        "topCandidates": [asdict(e) for e in ranked[:15]],
        "allCaptured": [asdict(e) for e in captured],
        "cookiesForReplay": cookies,
    }


async def replay_direct(person_id: int, cookies: list[dict]) -> dict:
    """Прямой GET person_view без Playwright (через APIRequestContext)."""
    from playwright.async_api import async_playwright

    url = config.DETAIL_URL_TEMPLATE.format(person_id=person_id)
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Referer": config.LIST_URL,
    }
    if cookie_header:
        headers["Cookie"] = cookie_header

    async with async_playwright() as p:
        req = await p.request.new_context(ignore_https_errors=True)
        r = await req.get(url, headers=headers, timeout=120000)
        text = await r.text()
        status = r.status
        ctype = r.headers.get("content-type", "")
        final_url = r.url
        await req.dispose()
    has_activity = "Результаты профессиональной деятельности" in text
    years = re.findall(r"<td[^>]*>\s*(\d{4})\s*</td>", text)
    return {
        "url": final_url,
        "status": status,
        "contentType": ctype,
        "responseKind": "json" if "application/json" in ctype else "html",
        "hasActivitySection": has_activity,
        "yearCellsFound": years[:10],
        "bodyLength": len(text),
        "preview": text[:400],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--person-id", type=int, default=824174)
    parser.add_argument("--headless", action="store_true", default=config.HEADLESS)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--wait", type=int, default=20)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()

    headless = config.HEADLESS if not args.no_headless else False
    if args.headless:
        headless = True

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    report = await run_probe(args.person_id, headless=headless, wait_sec=args.wait)

    if args.replay and report.get("cookiesForReplay"):
        report["directReplay"] = await replay_direct(
            args.person_id, report["cookiesForReplay"]
        )
    elif args.replay:
        report["directReplay"] = await replay_direct(args.person_id, [])

    # cookies не нужны в логе целиком
    report.pop("cookiesForReplay", None)
    PROBE_LOG.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== TOP CANDIDATES ===")
    for c in report.get("topCandidates", [])[:8]:
        print(f"score={c.get('score')} {c.get('method')} {c.get('status')} {c.get('url', '')[:120]}")

    if "directReplay" in report:
        dr = report["directReplay"]
        print("\n=== DIRECT REPLAY ===")
        print(f"status={dr['status']} kind={dr['responseKind']} activity={dr['hasActivitySection']}")
        print(f"years sample: {dr.get('yearCellsFound')}")

    print(f"\nLog -> {PROBE_LOG}")


if __name__ == "__main__":
    asyncio.run(main())

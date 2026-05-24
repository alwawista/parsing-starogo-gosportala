import asyncio
import re

from grki_scraper.browser import BrowserSession
from grki_scraper.extractors.detail_extractor import extract_detail_card
import config


async def main():
    s = BrowserSession()
    await s.start()
    page = s._page
    await s.goto(config.LIST_URL)
    async with page.expect_navigation(timeout=120000):
        await page.evaluate(
            """() => {
                document.forms['editForm'].id.value = 826933;
                document.forms['editForm'].submit();
            }"""
        )
    await asyncio.sleep(2)
    html = await page.content()
    with open("tmp_onedit.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("url:", page.url[:150])
    print("Квалификацион:", "Квалификацион" in html)
    print("дата выдачи:", "дата выдачи" in html)
    d = extract_detail_card(html)
    print("parsed cert:", repr(d.general.cert_number), repr(d.general.cert_date))
    await s.close()


if __name__ == "__main__":
    asyncio.run(main())

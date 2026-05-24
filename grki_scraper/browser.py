"""
Обёртка Playwright: навигация, пагинация, прокси.

Сайт отдаёт 403 без браузера; используем headless Chromium.
Пагинация списка — через JS setPage('page', N) (форма pageForm на сайте).
Карточки — прямой URL с person_id (внутренний ID из onclick='onEdit(...)').
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

import config


class BrowserSession:
    """
    Управление сессией браузера с поддержкой ротации прокси.

    При ошибке сети можно пересоздать контекст со следующим прокси из пула.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._proxy_index = 0

    async def start(self) -> Page:
        """Запустить браузер и вернуть активную страницу."""
        self._playwright = await async_playwright().start()
        await self._create_context()
        return self._page  # type: ignore[return-value]

    async def _create_context(self) -> None:
        """Создать (или пересоздать) контекст браузера."""
        if self._context:
            await self._context.close()

        launch_kwargs: dict = {"headless": config.HEADLESS}
        proxy = self._next_proxy()
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}

        if not self._browser:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        elif proxy:
            # При смене прокси перезапускаем браузер
            await self._browser.close()
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        self._context = await self._browser.new_context(
            ignore_https_errors=config.IGNORE_HTTPS_ERRORS,
            locale="ru-RU",
        )
        self._page = await self._context.new_page()

    def _next_proxy(self) -> Optional[str]:
        """Взять следующий прокси из пула (round-robin)."""
        if not config.PROXY_LIST:
            return None
        proxy = config.PROXY_LIST[self._proxy_index % len(config.PROXY_LIST)]
        self._proxy_index += 1
        return proxy

    async def rotate_proxy(self) -> Page:
        """Переключиться на следующий прокси после сбоя."""
        await self._create_context()
        return self._page  # type: ignore[return-value]

    async def goto(self, url: str) -> str:
        """Перейти по URL и вернуть HTML страницы."""
        assert self._page is not None
        await self._page.goto(
            url,
            wait_until=config.NAVIGATION_WAIT,
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        )
        await asyncio.sleep(config.POST_LOAD_DELAY_MS / 1000)
        return await self._page.content()

    async def goto_list_page(self, page_number: int = 1) -> str:
        """
        Открыть страницу списка инженеров.

        page_number=1 — прямой переход по URL.
        page_number>1 — setPage() от текущей страницы списка (без повторной загрузки).
        """
        assert self._page is not None
        if page_number == 1:
            return await self.goto(config.LIST_URL)

        async with self._page.expect_navigation(
            wait_until=config.NAVIGATION_WAIT,
            timeout=config.PAGE_LOAD_TIMEOUT_MS,
        ):
            await self._page.evaluate(
                """(pageNum) => {
                    if (typeof setPage === 'function') {
                        setPage('page', pageNum);
                    }
                }""",
                page_number,
            )
        await asyncio.sleep(config.POST_LOAD_DELAY_MS / 1000)
        return await self._page.content()

    async def fetch_detail(self, person_id: int) -> str:
        """Загрузить HTML карточки инженера по внутреннему ID сайта."""
        url = config.DETAIL_URL_TEMPLATE.format(person_id=person_id)
        return await self.goto(url)

    async def delay_between_cards(self) -> None:
        """Пауза между обработкой карточек."""
        jitter = random.uniform(0, 0.3)
        await asyncio.sleep(config.DELAY_BETWEEN_CARDS_MS / 1000 + jitter)

    async def close(self) -> None:
        """Корректно закрыть браузер."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

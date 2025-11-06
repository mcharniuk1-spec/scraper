#!/usr/bin/env python3
# src/scrapers/fora_scraper.py
import asyncio
import logging
from playwright.async_api import async_playwright
from src.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

class ForaScraper(BaseScraper):
    """Playwright-based scraper for fora.ua"""

    async def _scrape_page(self, page, url):
        """Scrape a single product listing page."""
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_selector("div.product-item", timeout=15000)

        elements = await page.query_selector_all("div.product-item")
        products = []
        for el in elements:
            title = await el.query_selector_eval("a.product-item__title", "el => el.textContent.trim()") or ""
            price = await el.query_selector_eval("span.price__value", "el => el.textContent.trim()") or ""
            href = await el.query_selector_eval("a.product-item__title", "el => el.href") or None
            image = await el.query_selector_eval("img", "el => el.src") or None
            products.append({
                "title": title,
                "url": href,
                "snippet": "",
                "image_url": image,
                "price": price,
                "currency": "грн",
                "date_posted": None,
            })
        return products

    async def _scrape_all(self, start_url, max_pages):
        all_products = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=self.user_agent)
            current_page = 1
            url = start_url

            while True:
                logger.info(f"Scraping page {current_page}: {url}")
                products = await self._scrape_page(page, url)
                if not products:
                    break
                all_products.extend(products)
                if 0 < max_pages <= current_page:
                    break

                # try to navigate to the next page
                next_btn = await page.query_selector("a.pagination__next")
                if not next_btn:
                    break
                next_href = await next_btn.get_attribute("href")
                if not next_href:
                    break
                url = self.base_url + next_href
                current_page += 1

            await browser.close()
        return all_products

    def scrape(self, start_url, max_pages=0):
        """Entry point for synchronous invocation"""
        return asyncio.run(self._scrape_all(start_url, max_pages))

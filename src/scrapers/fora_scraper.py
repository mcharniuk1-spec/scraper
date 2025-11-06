#!/usr/bin/env python3
"""
Updated Fora scraper using Playwright for dynamic JS rendering.
Works independently of Novus scraper.
"""

import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from src.core.scraper_base import BaseScraper

logger = logging.getLogger(__name__)

class ForaScraper(BaseScraper):
    """Dynamic scraper for Fora.ua using Playwright (Chromium)."""

    def scrape_products(self, max_pages=10):
        products = []
        self.log_progress(f"🚀 Starting dynamic scraping of Fora.ua for {max_pages} pages")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            for page_num in range(1, max_pages + 1):
                url = f"{self.config['base_url']}?page={page_num}"
                try:
                    page.goto(url, timeout=45000)
                    page.wait_for_selector("div.product-card, .product-item", timeout=10000)
                    html = page.content()
                except Exception as e:
                    self.log_error(f"⚠️ Could not load page {page_num}: {e}")
                    break

                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select("div.product-card, .product-item")
                if not cards:
                    self.log_progress(f"⚠️ No cards found on page {page_num}")
                    break

                for card in cards:
                    try:
                        link_tag = card.select_one("a[href]")
                        title_tag = card.select_one(".product-card__name, h3, .product-title")
                        price_tag = card.select_one("span[class*='price']")

                        if not (link_tag and title_tag):
                            continue

                        product = {
                            "url": urljoin(self.config["base_url"], link_tag["href"]),
                            "product_name": title_tag.get_text(strip=True),
                            "price": self.extract_price(price_tag.get_text() if price_tag else ""),
                            "currency": "₴",
                            "availability": "unknown",
                            "category": "Молочні продукти та яйця"
                        }
                        products.append(product)
                    except Exception as err:
                        self.log_error(f"Error parsing card: {err}")

                self.log_progress(f"✅ Page {page_num}: {len(cards)} products scraped")

            browser.close()

        self.products_found = len(products)
        self.log_progress(f"🎉 Finished Fora scraping. Total: {len(products)} products")
        return products

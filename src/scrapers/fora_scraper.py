#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
from typing import List, Dict
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

from src.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class ForaScraper(BaseScraper):
    """
    Scraper for Fora.ua
    """

    def __init__(self, **kwargs):
        defaults = {
            "base_url": "https://fora.ua",
            "start_url": "https://fora.ua/category/molochni-produkty-ta-iaitsia-2656",
            "user_agent": "fora-scraper/1.0",
            "timeout": 20,
            "sleep_between_requests": 1.0,
            "max_retries": 5,
            "max_pages": 0,
            "site": "fora",
            "category": "molochni-produkty-ta-iaitsia",
        }
        defaults.update(kwargs)
        super().__init__(**defaults)

    # -----------------------------
    # Internal page parsing helpers
    # -----------------------------

    def parse_product_card(self, card) -> Dict:
        """
        Extract structured product data from a single card element.
        """
        title = card.select_one(".product-card__title")
        title = title.get_text(strip=True) if title else None

        price_el = card.select_one(".product-card__price-current")
        price = None
        if price_el:
            try:
                price = float(price_el.get_text(strip=True).replace("грн", "").replace(",", "."))
            except ValueError:
                price = None

        link_el = card.select_one("a")
        url = None
        if link_el and link_el.get("href"):
            url = requests.compat.urljoin(self.base_url, link_el["href"])

        image_el = card.select_one("img")
        img_url = None
        if image_el and image_el.get("src"):
            img_url = requests.compat.urljoin(self.base_url, image_el["src"])

        return {
            "title": title,
            "url": url,
            "snippet": None,
            "image_url": img_url,
            "price": price,
            "currency": "грн",
            "date_posted": None,
        }

    # -----------------------------
    # Core scraping
    # -----------------------------

    def scrape(self, start_url: str, max_pages: int = 0) -> List[Dict]:
        """
        Scrape product listings from Fora.ua dynamically rendered pages.
        """
        all_results = []
        page_number = 1

        logger.info("Starting Fora scraper at %s", start_url)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            while True:
                paged_url = f"{start_url}?page={page_number}"
                logger.info("Scraping page %d: %s", page_number, paged_url)
                page.goto(paged_url, timeout=60000)
                try:
                    page.wait_for_selector(".product-card__title", timeout=15000)
                except Exception:
                    logger.warning("Timeout waiting for products on page %d", page_number)
                    break

                html = page.content()
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select(".product-card__content")

                if not cards:
                    logger.info("No products found on page %d, stopping.", page_number)
                    break

                for card in cards:
                    try:
                        product = self.pars

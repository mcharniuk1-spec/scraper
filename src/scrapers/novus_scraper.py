#!/usr/bin/env python3
"""
Novus Zakaz.ua Scraper

Scrapes product listings from Novus Zakaz.ua category pages.
"""
import re
from typing import Dict, List, Optional, Set
import requests
from bs4 import BeautifulSoup

import logging

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Price pattern matching
CURRENCY_RE = re.compile(r"(\d[\d\s,\.]*)\s*(₴|грн|uah|UAH)", re.IGNORECASE)


class NovusScraper(BaseScraper):
    """Scraper for Novus Zakaz.ua category pages."""

    def __init__(self, **kwargs):
        """Initialize Novus scraper with default settings."""
        defaults = {
            "base_url": "https://novus.zakaz.ua",
            "user_agent": "novus-scraper/1.0 (+https://github.com/yourname/novus-scraper) Python-requests",
            "sleep_between_requests": 0.5,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)
        self.max_pages = 100  # Safety cap

    def parse_category_page(self, html: str, base_url: str) -> List[str]:
        """
        Parse category page and extract product URLs.

        Args:
            html: HTML content
            base_url: Base URL for resolving relative URLs

        Returns:
            List of product page URLs
        """
        soup = self.parse_html(html)
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/products/" in href:
                full_url = requests.compat.urljoin(base_url, href)
                links.add(full_url)
        return list(links)

    def find_next_page_url(self, soup: BeautifulSoup, current_url: str, page_num: int) -> Optional[str]:
        """Find next page URL from pagination."""
        # Try to find next page link
        next_link = soup.find("a", href=True, string=lambda x: x and x.strip() == str(page_num + 1))
        if next_link:
            return requests.compat.urljoin(self.base_url, next_link["href"])
        
        # Fallback: construct URL with ?page= parameter
        base_url = current_url.split('?')[0].rstrip('/')
        return f"{base_url}?page={page_num + 1}"

    def get_max_page_number(self, soup: BeautifulSoup) -> Optional[int]:
        """Get maximum page number from pagination."""
        pagination_links = soup.find_all("a", href=True, string=lambda x: x and x.strip().isdigit())
        if pagination_links:
            page_nums = [int(link.get_text(strip=True)) for link in pagination_links]
            return max(page_nums) if page_nums else None
        return None

    def scrape_category(
        self, start_url: str, max_pages: int = 0
    ) -> List[str]:
        """
        Scrape category pages to collect product URLs.

        Args:
            start_url: Starting category URL
            max_pages: Maximum pages to scrape (0 = no limit)

        Returns:
            List of product page URLs
        """
        page_num = 1
        all_links: Set[str] = set()
        max_page_found = None

        while True:
            if page_num == 1:
                url = start_url
            else:
                url = f"{start_url.rstrip('/')}?page={page_num}"

            if max_pages and page_num > max_pages:
                logger.info("Reached max pages limit (%s). Stopping.", max_pages)
                break
            if page_num > self.max_pages:
                logger.warning(
                    "Reached safety MAX_PAGES (%s). Stopping.", self.max_pages
                )
                break

            try:
                html = self.fetch(url)
                soup = self.parse_html(html)
            except Exception as e:
                logger.exception(
                    "Failed to fetch category page %s: %s", url, e
                )
                break

            # Get max page number on first page if not set
            if max_page_found is None and page_num == 1:
                max_page_found = self.get_max_page_number(soup)
                if max_page_found:
                    logger.info("Found %d total pages in category", max_page_found)
                    if max_pages == 0:
                        # Set to max pages found, but we'll continue until we hit it
                        pass  # Will check max_page_found in loop condition

            links = self.parse_category_page(html, self.base_url)
            logger.info("Found %d product links on page %d", len(links), page_num)

            new_links = [link for link in links if link not in all_links]
            if not new_links:
                logger.info(
                    "No new product links found on page %d. Stopping.", page_num
                )
                break

            all_links.update(new_links)
            
            # Check if we've reached the last page
            if max_page_found and page_num >= max_page_found:
                logger.info("Reached last page (%d). Stopping.", max_page_found)
                break
                
            page_num += 1

        logger.info("Collected %d unique product URLs from %d pages", len(all_links), page_num - 1)
        return list(all_links)

    def parse_product_page(self, html: str, url: str) -> Dict:
        """
        Parse product page and extract details.

        Args:
            html: HTML content
            url: Product page URL

        Returns:
            Dictionary with product details
        """
        soup = self.parse_html(html)

        # Title - try multiple selectors
        title = None
        title_tag = soup.find("h1")
        if title_tag:
            title = title_tag.get_text(strip=True)
        if not title:
            title_tag = soup.find("h2")
            if title_tag:
                title = title_tag.get_text(strip=True)
        if not title:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.get("content"):
                title = meta_title["content"].strip()

        # Description
        description = None
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()
        if not description:
            meta_og_desc = soup.find("meta", property="og:description")
            if meta_og_desc and meta_og_desc.get("content"):
                description = meta_og_desc["content"].strip()

        # Price - try to find in price-specific classes
        price = None
        currency = None
        
        # Try finding price in specific Novus price classes
        price_element = soup.find(class_=lambda x: x and "price" in str(x).lower() and "value" in str(x).lower())
        if price_element:
            price_text = price_element.get_text(strip=True)
            currency_element = soup.find(class_=lambda x: x and "currency" in str(x).lower())
            if currency_element:
                currency = currency_element.get_text(strip=True)
            
            # Extract price number
            m = CURRENCY_RE.search(price_text.replace("\xa0", " "))
            if m:
                num_str = m.group(1).replace(" ", "").replace(",", ".")
                try:
                    price = float(num_str)
                except ValueError:
                    price = None
                if not currency:
                    currency = m.group(2) or "грн"
        
        # Fallback: search in all text
        if price is None:
            text_content = soup.get_text(" ", strip=True)
            m = CURRENCY_RE.search(text_content.replace("\xa0", " "))
            if m:
                num_str = m.group(1).replace(" ", "").replace(",", ".")
                try:
                    price = float(num_str)
                except ValueError:
                    price = None
                currency = m.group(2) or "грн"

        # Image - try multiple sources
        img_url = None
        # Try og:image first
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            img_url = og_image["content"]
        if not img_url:
            # Try product image classes
            img = soup.find("img", class_=lambda x: x and ("product" in str(x).lower() or "main" in str(x).lower()))
            if img and img.get("src"):
                img_url = requests.compat.urljoin(url, img.get("src"))
        if not img_url:
            # Fallback: first image
            img = soup.find("img")
            if img and img.get("src"):
                img_url = requests.compat.urljoin(url, img.get("src"))

        return {
            "title": title,
            "url": url,
            "snippet": description,
            "image_url": img_url,
            "price": price,
            "currency": currency or "грн",
            "date_posted": None,
        }

    def scrape(self, start_url: str, max_pages: int = 0) -> List[Dict]:
        """
        Scrape product listings from category.

        Args:
            start_url: Starting category URL
            max_pages: Maximum pages to scrape (0 = no limit)

        Returns:
            List of listing dictionaries
        """
        # First, collect product URLs
        product_urls = self.scrape_category(start_url, max_pages)
        logger.info("Collected %d product URLs", len(product_urls))

        # Then, scrape each product page
        results = []
        for url in product_urls:
            try:
                html = self.fetch(url)
                item = self.parse_product_page(html, url)
                results.append(item)
            except Exception as e:
                logger.exception("Error scraping product %s: %s", url, e)

        return results

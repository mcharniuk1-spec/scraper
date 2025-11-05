#!/usr/bin/env python3
"""
Fora.ua Scraper

Scrapes product listings from Fora.ua category pages.
"""
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dateutil import parser as dateparser
import requests
from bs4 import BeautifulSoup

import logging

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Price pattern matching
CURRENCY_RE = re.compile(r"(\d[\d\s,\.]*)\s*(грн|uah|UAH|₴)?", re.IGNORECASE)


def extract_text_from_tag(tag) -> str:
    """Extract text from a BeautifulSoup tag."""
    if not tag:
        return ""
    return " ".join(tag.stripped_strings)


def normalize_price(text: str) -> Tuple[Optional[float], Optional[str]]:
    """Normalize price string to float value and currency."""
    if not text:
        return None, None
    m = CURRENCY_RE.search(text.replace("\xa0", " "))
    if not m:
        return None, None
    num = m.group(1)
    # Normalize number: remove spaces, replace comma with dot
    num = num.replace(" ", "").replace(",", ".")
    try:
        price = float(num)
    except ValueError:
        price = None
    currency = m.group(2) if m.group(2) else None
    return price, currency


class ForaScraper(BaseScraper):
    """Scraper for Fora.ua category pages."""

    def __init__(self, **kwargs):
        """Initialize Fora scraper with default settings."""
        defaults = {
            "base_url": "https://fora.ua",
            "user_agent": "fora-scraper/1.0 (+https://github.com/yourname/fora-scraper) Python-requests",
            "sleep_between_requests": 1.0,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)
        self.max_pages = 100  # Safety cap

    def find_pagination_next(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Find next page URL from pagination links."""
        selectors = [
            'a[rel="next"]',
            "a.next",
            "a.pagination__next",
            "li.next a",
        ]
        for selector in selectors:
            found = soup.select_one(selector)
            if found and found.get("href"):
                return requests.compat.urljoin(current_url, found["href"])

        # Fallback: search by link text
        for a in soup.find_all("a"):
            if a.string:
                text = a.string.strip().lower()
                if text in ("next", "далее", "вперёд", "вперед", "»", ">>"):
                    if a.get("href"):
                        return requests.compat.urljoin(current_url, a["href"])
        return None

    def extract_candidate_items(self, soup: BeautifulSoup) -> List[BeautifulSoup]:
        """Extract candidate item blocks from page."""
        selectors = [
            "article",
            "div.post",
            "div.post-item",
            "div.card",
            "div.product-item",
            "div.listing-item",
            "li.item",
            "div[class*='product']",
            "div[class*='item']",
            "div[class*='card']",
            "div[class*='post']",
            "div.col-",
            "div[data-product]",
            "div[data-item]",
        ]
        found = []
        for selector in selectors:
            try:
                items = soup.select(selector)
                found.extend(items)
            except Exception:
                continue

        # More aggressive fallback: find all links with product-like patterns
        if not found or len(found) < 3:
            main = soup.find("main") or soup.find(id="content") or soup.find("div", class_="content") or soup.body
            if main:
                # Look for divs containing links that might be products
                links = main.find_all("a", href=True)
                for link in links:
                    href = link.get("href", "")
                    # Check if link looks like a product/category link
                    if any(keyword in href.lower() for keyword in ["product", "item", "goods", "category", "offer", "/p/", "/prod"]):
                        # Find parent container
                        parent = link.find_parent(["div", "article", "li"])
                        if parent and parent not in found:
                            found.append(parent)

        # Another fallback: find divs with links and some content
        if not found or len(found) < 3:
            main = soup.find("main") or soup.find(id="content") or soup.body
            if main:
                divs = main.find_all("div", recursive=True)
                for div in divs:
                    # Check if div has a link and some text content
                    if div.find("a", href=True) and len(div.get_text(strip=True)) > 20:
                        # Avoid very large containers
                        if len(div.get_text(strip=True)) < 5000:
                            found.append(div)

        # Deduplicate
        unique = []
        seen = set()
        for f in found:
            key = str(f)[:300]
            if key not in seen:
                unique.append(f)
                seen.add(key)
        
        logger.debug(f"Extracted {len(unique)} candidate items")
        return unique

    def parse_item_block(self, block: BeautifulSoup, base_url: str) -> Dict:
        """Parse a single item block into a dictionary."""
        title = None
        link = None
        image = None
        snippet = None
        price = None
        currency = None
        date_posted = None

        # Find link and title - try multiple approaches
        a = block.find("a", href=True)
        if a:
            link = requests.compat.urljoin(base_url, a["href"])
            # Try header inside link
            header = a.find(["h1", "h2", "h3", "h4", "span", "div"])
            if header:
                title = extract_text_from_tag(header)
            else:
                title = extract_text_from_tag(a)
            
            # Clean up title
            if title:
                title = title.strip()

        # Title fallback - look in parent block
        if not title:
            header = block.find(["h1", "h2", "h3", "h4", "span"], class_=lambda x: x and any(kw in str(x).lower() for kw in ["title", "name", "heading"]))
            if header:
                title = extract_text_from_tag(header)
        
        # Another fallback - any header in block
        if not title:
            headers = block.find_all(["h1", "h2", "h3", "h4"])
            if headers:
                title = extract_text_from_tag(headers[0])
        
        # Last resort - first non-empty text
        if not title:
            text = extract_text_from_tag(block)
            # Take first 100 chars as title
            if text and len(text.strip()) > 10:
                title = text.strip()[:100].split('\n')[0].strip()

        # Snippet
        p = block.find("p")
        if p:
            snippet = extract_text_from_tag(p)

        # Image
        img = block.find("img")
        if img and img.get("src"):
            image = requests.compat.urljoin(base_url, img.get("src"))

        # Price
        text_all = extract_text_from_tag(block)
        price_val, currency_val = normalize_price(text_all)
        if price_val:
            price = price_val
            currency = currency_val or "грн"

        # Date
        time_tag = block.find("time")
        if time_tag and time_tag.get("datetime"):
            try:
                date_posted = dateparser.parse(time_tag["datetime"])
            except Exception:
                date_posted = None
        else:
            date_match = re.search(r"\b(\d{1,2}\.\d{1,2}\.\d{2,4})\b", text_all)
            if date_match:
                try:
                    date_posted = dateparser.parse(date_match.group(1), dayfirst=True)
                except Exception:
                    date_posted = None

        return {
            "title": title.strip() if title else None,
            "url": link,
            "snippet": snippet.strip() if snippet else None,
            "image_url": image,
            "price": price,
            "currency": currency,
            "date_posted": date_posted.isoformat() if date_posted else None,
        }

    def _check_javascript_required(self, html: str, soup: BeautifulSoup) -> bool:
        """Check if page requires JavaScript to render content."""
        # Check for common JavaScript-required indicators
        body_text = soup.body.get_text(strip=True).lower() if soup.body else ""
        js_indicators = [
            "you need to enable javascript",
            "увімкніть javascript",
            "необхідно увімкнути javascript",
            "please enable javascript",
            "noscript",
        ]
        
        # Check HTML for React/SPA indicators
        html_lower = html.lower()
        spa_indicators = [
            "react",
            "__next__",
            "reactroot",
            "data-react",
            "root",
        ]
        
        # Check if body is mostly empty or has JavaScript requirement message
        if any(indicator in body_text for indicator in js_indicators):
            return True
        
        # Check if it's a React/SPA with minimal content
        if any(indicator in html_lower for indicator in spa_indicators):
            # If HTML is very short and has few links, likely JS-rendered
            links_count = len(soup.find_all("a", href=True))
            if len(html) < 15000 and links_count < 5:
                return True
        
        return False

    def scrape(self, start_url: str, max_pages: int = 0) -> List[Dict]:
        """
        Scrape category pages.

        Args:
            start_url: Starting category URL
            max_pages: Maximum pages to scrape (0 = no limit)

        Returns:
            List of listing dictionaries
        """
        if not self.is_allowed_by_robots(start_url):
            logger.warning("Scraping disallowed by robots.txt. Aborting.")
            return []

        results = []
        url = start_url
        page_count = 0

        while url:
            if 0 < max_pages <= page_count:
                logger.info("Reached max pages (%s). Stopping.", max_pages)
                break
            if page_count >= self.max_pages:
                logger.warning(
                    "Reached safety MAX_PAGES (%s). Stopping.", self.max_pages
                )
                break

            try:
                html = self.fetch(url)
            except Exception as e:
                logger.exception("Failed fetching page %s: %s", url, e)
                break

            soup = self.parse_html(html)
            
            # Check if page requires JavaScript
            if page_count == 0 and self._check_javascript_required(html, soup):
                logger.error(
                    "=" * 60 + "\n"
                    "ERROR: Fora.ua requires JavaScript to render content.\n"
                    "The page is a Single Page Application (SPA) that loads\n"
                    "content dynamically via JavaScript.\n\n"
                    "To scrape Fora.ua, you need to use a headless browser\n"
                    "such as Selenium or Playwright instead of simple HTTP requests.\n\n"
                    "Current solution: Consider using selenium-wire or playwright\n"
                    "to render the page before scraping.\n"
                    "=" * 60
                )
                logger.warning(
                    "Skipping Fora scraper. Use --skip-fora to suppress this message."
                )
                return []
            
            blocks = self.extract_candidate_items(soup)
            logger.info("Found %s candidate blocks on page %s", len(blocks), url)

            for block in blocks:
                item = self.parse_item_block(block, self.base_url)
                # Accept item if it has either URL or title (or both)
                if item.get("url") is None and item.get("title") is None:
                    continue
                # Don't skip items with just URL but no title (might be valid products)
                if item.get("url"):
                    results.append(item)
                    logger.debug(f"Added item: {item.get('title', 'No title')[:50]} - {item.get('url', 'No URL')[:60]}")
                elif item.get("title"):
                    # If no URL but has title, try to create URL from title or skip
                    # For now, we'll include it but log it
                    logger.debug(f"Item with title but no URL: {item.get('title')[:50]}")
                    results.append(item)

            page_count += 1
            next_url = self.find_pagination_next(soup, url)
            if not next_url:
                logger.info("No next page found. Stopping after %d pages.", page_count)
                break
            if next_url == url:
                logger.warning("Next URL equals current URL; stopping to avoid loop.")
                break
            url = next_url

        return results

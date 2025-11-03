#!/usr/bin/env python3
"""
Novus dairy and eggs category scraper

This script scrapes product pages from the Novus Zakaz.ua dairy and eggs category and stores the results in a local SQLite database by default. It also has an option to export results to an Excel file. It navigates category pages, collects product links, visits each product page to extract details such as title, price, currency, and description, and writes them to the database. Logs are emitted to track progress.
"""
import argparse
import logging
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Set

import requests
from bs4 import BeautifulSoup
import backoff
import pandas as pd

BASE_CATEGORY_URL = "https://novus.zakaz.ua/uk/categories/dairy-and-eggs/"
DEFAULT_DB_PATH = os.path.join("data", "novus_listings.db")
USER_AGENT = "novus-scraper/1.0 (+https://github.com/yourname/novus-scraper) Python-requests"
REQUESTS_TIMEOUT = 20  # seconds
SLEEP_BETWEEN_REQUESTS = 0.5
MAX_PAGES = 100  # safety cap

logger = logging.getLogger("novus_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def ensure_data_dir(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)


def get_session(user_agent: str = USER_AGENT) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"})
    adapter = requests.adapters.HTTPAdapter(
        max_retries=requests.adapters.Retry(
            total=5,
            backoff_factor=0.8,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "HEAD"])
        )
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


@backoff.on_exception(backoff.expo, (requests.exceptions.RequestException,), max_time=60)
def fetch(session: requests.Session, url: str) -> str:
    logger.info("Fetching %s", url)
    r = session.get(url, timeout=REQUESTS_TIMEOUT)
    r.raise_for_status()
    return r.text


def parse_category_page(html: str) -> List[str]:
    """Parse a category page and return a list of product page URLs."""
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/products/" in href:
            full_url = requests.compat.urljoin(BASE_CATEGORY_URL, href)
            links.add(full_url)
    return list(links)


def scrape_category(session: requests.Session, start_url: str, max_pages: int = 0) -> List[str]:
    """Iterate over pagination in the category and collect product links."""
    page_num = 1
    all_links: Set[str] = set()
    while True:
        url = start_url if page_num == 1 else f"{start_url}?page={page_num}"
        if max_pages and page_num > max_pages:
            logger.info("Reached max pages (%s). Stopping.", max_pages)
            break
        if page_num > MAX_PAGES:
            logger.warning("Reached safety MAX_PAGES (%s). Stopping.", MAX_PAGES)
            break
        try:
            html = fetch(session, url)
        except Exception as e:
            logger.exception("Failed to fetch category page %s: %s", url, e)
            break
        links = parse_category_page(html)
        logger.info("Found %d product links on page %d", len(links), page_num)
        new_links = [link for link in links if link not in all_links]
        if not new_links:
            logger.info("No new product links found on page %d. Stopping.", page_num)
            break
        all_links.update(new_links)
        page_num += 1
        time.sleep(SLEEP_BETWEEN_REQUESTS)
    return list(all_links)


CURRENCY_RE = re.compile(r"(\d[\d\s,\.]*)\s*(₴|грн|uah|UAH)", re.IGNORECASE)


def parse_product_page(session: requests.Session, url: str) -> Dict[str, Optional[str]]:
    html = get_with_backoff(session, url)
    soup = BeautifulSoup(html, "lxml")
    # Назва товару
    title = soup.find("h1")
    title_text = title.get_text(strip=True) if title else None
    # Пошук ціни регулярним виразом
    price_match = re.search(r"([0-9]+[,.]?[0-9]*)\s*₴", soup.get_text())
    price = float(price_match.group(1).replace(",", ".")) if price_match else None
    currency = "₴" if price_match else None
    # Опис
    desc_el = soup.find("p", class_="product-description") or soup.find("div", {"data-testid": "product-description"})
    description = desc_el.get_text(strip=True) if desc_el else None
    # Зображення
    img_el = soup.find("img", {"data-testid": "product-image"})
    img_url = img_el["src"] if img_el else None
    return {
        "title": title_text,
        "price": price,
        "currency": currency,
        "description": description,
        "image_url": img_url,
        "url": url,
    }



def init_db(db_path: str) -> sqlite3.Connection:
    ensure_data_dir(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            snippet TEXT,
            image_url TEXT,
            price REAL,
            currency TEXT,
            date_posted TEXT,
            scraped_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def upsert_listing(conn: sqlite3.Connection, item: Dict) -> None:
    cur = conn.cursor()
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        cur.execute(
            """
            INSERT INTO listings (url, title, snippet, image_url, price, currency, date_posted, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              title=excluded.title,
              snippet=excluded.snippet,
              image_url=excluded.image_url,
              price=excluded.price,
              currency=excluded.currency,
              date_posted=excluded.date_posted,
              scraped_at=excluded.scraped_at
            """,
            (
                item.get("url"),
                item.get("title"),
                item.get("snippet"),
                item.get("image_url"),
                item.get("price"),
                item.get("currency"),
                item.get("date_posted"),
                now,
            ),
        )
    except sqlite3.Error as e:
        logger.exception("DB insert failed for %s: %s", item.get("url"), e)
    conn.commit()


def export_excel(conn: sqlite3.Connection, path: str) -> None:
    cur = conn.cursor()
    cur.execute("SELECT url, title, snippet, image_url, price, currency, date_posted, scraped_at FROM listings ORDER BY scraped_at DESC")
    rows = cur.fetchall()
    columns = ["url", "title", "snippet", "image_url", "price", "currency", "date_posted", "scraped_at"]
    df = pd.DataFrame(rows, columns=columns)
    ensure_data_dir(path)
    df.to_excel(path, index=False)
    logger.info("Exported %d rows to %s", len(df), path)


def parse_args():
    p = argparse.ArgumentParser(description="Novus Zakaz.ua dairy and eggs category scraper")
    p.add_argument("--start-url", default=BASE_CATEGORY_URL)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--excel", help="Export Excel file path after scraping")
    p.add_argument("--max-pages", type=int, default=0, help="Max pages to fetch (0 = no limit)")
    p.add_argument("--user-agent", default=USER_AGENT)
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if args.quiet:
        logger.setLevel(logging.WARNING)

    session = get_session(args.user_agent)
    ensure_data_dir(args.db)
    conn = init_db(args.db)
    # scrape category for product URLs
    try:
        product_links = scrape_category(session, args.start_url, args.max_pages)
        logger.info("Collected %d product links", len(product_links))
        for link in product_links:
            try:
                html = fetch(session, link)
                item = parse_product_page(html, link)
                upsert_listing(conn, item)
            except Exception as e:
                logger.exception("Error scraping product %s: %s", link, e)
    except Exception as e:
        logger.exception("Scraping failed: %s", e)
        sys.exit(2)

    if args.excel:
        export_excel(conn, args.excel)

    conn.close()


if __name__ == "__main__":
    main()

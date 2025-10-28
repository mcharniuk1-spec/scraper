#!/usr/bin/env python3
"""
Fora.ua category scraper

Stores results into a local SQLite DB (data/fora_listings.db) by default.
Respects robots.txt, uses retries/backoff, and de-duplicates by URL.
"""
import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import backoff
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# Configuration
BASE_CATEGORY_URL = "https://fora.ua/category/molochni-produkty-ta-iaitsia-2656"
DEFAULT_DB_PATH = os.path.join("data", "fora_listings.db")
USER_AGENT = "fora-scraper/1.0 (+https://github.com/yourname/fora-scraper) Python-requests"
REQUESTS_TIMEOUT = 20  # seconds
SLEEP_BETWEEN_PAGES = 1.0  # polite pause between page fetches
MAX_PAGES = 100  # safety cap if pagination loop misbehaves

logger = logging.getLogger("fora_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def ensure_data_dir(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)


def get_session(user_agent: str = USER_AGENT) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"})
    # Requests Retry via urllib3
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


def is_allowed_by_robots(session: requests.Session, url: str, user_agent: str = "*") -> bool:
    # Basic robots.txt check
    try:
        parsed = requests.utils.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        r = session.get(robots_url, timeout=REQUESTS_TIMEOUT)
        if r.status_code != 200:
            logger.debug("robots.txt not found or returned %s; proceeding", r.status_code)
            return True
        lines = r.text.splitlines()
        allow = True
        ua = None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("user-agent:"):
                ua = line.split(":", 1)[1].strip()
            elif ua and (ua == "*" or user_agent.lower().startswith(ua.lower())):
                if line.lower().startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    if path and parsed.path.startswith(path):
                        allow = False
                        logger.info("Blocked by robots.txt: %s", path)
                        return False
        return allow
    except Exception as e:
        logger.warning("Failed to check robots.txt: %s. Proceeding cautiously.", e)
        return True


@backoff.on_exception(backoff.expo, (requests.exceptions.RequestException,), max_time=60)
def fetch(session: requests.Session, url: str) -> str:
    logger.info("Fetching %s", url)
    r = session.get(url, timeout=REQUESTS_TIMEOUT)
    r.raise_for_status()
    return r.text


def find_pagination_next(soup: BeautifulSoup) -> Optional[str]:
    # Common patterns for next page links
    selectors = [
        'a[rel="next"]',
        "a.next",
        "a.pagination__next",
        "li.next a",
        "a:contains('>>')",
    ]
    # BeautifulSoup doesn't support :contains easily; we'll do custom fallback
    for s in selectors:
        found = soup.select_one(s)
        if found and found.get("href"):
            return requests.compat.urljoin(BASE_CATEGORY_URL, found["href"])
    # Fallback: link text
    for a in soup.find_all("a"):
        if a.string:
            text = a.string.strip().lower()
            if text in ("next", "далее", "вперёд", "вперед", "»", ">>"):
                if a.get("href"):
                    return requests.compat.urljoin(BASE_CATEGORY_URL, a["href"])
    return None


def extract_candidate_items(soup: BeautifulSoup) -> List[BeautifulSoup]:
    # Try multiple heuristics for finding item blocks
    selectors = [
        "article",
        "div.post",
        "div.post-item",
        "div.card",
        "div.product-item",
        "div.listing-item",
        "li.item",
        "div.col-",
    ]
    found = []
    for sel in selectors:
        found.extend(soup.select(sel))
    # fallback: find all links inside the main content area
    if not found:
        main = soup.find("main") or soup.find(id="content") or soup.body
        if main:
            found = [tag for tag in main.find_all("div", recursive=False) if tag.find("a")]
    # Deduplicate by object id
    unique = []
    seen = set()
    for f in found:
        key = str(f)[:300]  # coarse dedup
        if key not in seen:
            unique.append(f)
            seen.add(key)
    return unique


CURRENCY_RE = re.compile(r"(\d[\d\s,\.]*)\s*(грн|uah|UAH|₴)?", re.IGNORECASE)


def extract_text_from_tag(tag):
    if not tag:
        return ""
    return " ".join(tag.stripped_strings)


def normalize_price(text: str) -> Tuple[Optional[float], Optional[str]]:
    if not text:
        return None, None
    m = CURRENCY_RE.search(text.replace("\xa0", " "))
    if not m:
        return None, None
    num = m.group(1)
    # Normalize number: remove spaces, replace comma with dot, remove thousands separators
    num = num.replace(" ", "").replace(",", ".")
    try:
        price = float(num)
    except ValueError:
        price = None
    currency = m.group(2) if m.group(2) else None
    return price, currency


def parse_item_block(block: BeautifulSoup) -> Dict:
    # Try to extract title and link
    title = None
    link = None
    image = None
    snippet = None
    price = None
    currency = None
    date_posted = None

    # first look for link + title
    a = block.find("a", href=True)
    if a:
        link = requests.compat.urljoin(BASE_CATEGORY_URL, a["href"])
        # prefer inner header tags
        header = a.find(["h1", "h2", "h3", "h4"])
        if header:
            title = extract_text_from_tag(header)
        else:
            # fallback: a's text
            title = extract_text_from_tag(a)

    # title fallback: header elements not within <a>
    if not title:
        header = block.find(["h1", "h2", "h3", "h4"])
        if header:
            title = extract_text_from_tag(header)

    # snippet / description
    p = block.find("p")
    if p:
        snippet = extract_text_from_tag(p)

    # image
    img = block.find("img")
    if img and img.get("src"):
        image = requests.compat.urljoin(BASE_CATEGORY_URL, img.get("src"))

    # price detection: search inside block for patterns like "грн" or numbers
    text_all = extract_text_from_tag(block)
    price_val, currency_val = normalize_price(text_all)
    if price_val:
        price = price_val
        currency = currency_val

    # date: try time/abbr or patterns
    time_tag = block.find("time")
    if time_tag and time_tag.get("datetime"):
        try:
            date_posted = dateparser.parse(time_tag["datetime"])
        except Exception:
            date_posted = None
    else:
        # look for date-like text
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
    now = datetime.now(timezone.utc).isoformat()
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


def scrape_category(start_url: str, conn: sqlite3.Connection, max_pages: int = 0, session: Optional[requests.Session] = None) -> List[Dict]:
    if session is None:
        session = get_session()
    if not is_allowed_by_robots(session, start_url):
        raise SystemExit("Scraping disallowed by robots.txt. Aborting.")

    results = []
    url = start_url
    page_count = 0
    while url:
        if 0 < max_pages <= page_count:
            logger.info("Reached max pages (%s). Stopping.", max_pages)
            break
        if page_count >= MAX_PAGES:
            logger.warning("Reached safety MAX_PAGES (%s). Stopping.", MAX_PAGES)
            break
        try:
            html = fetch(session, url)
        except Exception as e:
            logger.exception("Failed fetching page %s: %s", url, e)
            break
        soup = BeautifulSoup(html, "lxml")
        blocks = extract_candidate_items(soup)
        logger.info("Found %s candidate blocks on page %s", len(blocks), url)
        for b in blocks:
            item = parse_item_block(b)
            if item.get("url") is None and item.get("title") is None:
                # skip useless blocks
                continue
            # if url missing, try to create a synthetic slug from title
            upsert_listing(conn, item)
            results.append(item)
        page_count += 1
        next_url = find_pagination_next(soup)
        if not next_url:
            logger.info("No next page found. Stopping after %d pages.", page_count)
            break
        if next_url == url:
            logger.warning("Next URL equals current URL; stopping to avoid loop.")
            break
        url = next_url
        time.sleep(SLEEP_BETWEEN_PAGES)
    return results


def export_json(conn: sqlite3.Connection, path: str) -> None:
    cur = conn.cursor()
    cur.execute("SELECT url, title, snippet, image_url, price, currency, date_posted, scraped_at FROM listings ORDER BY scraped_at DESC")
    rows = cur.fetchall()
    keys = ["url", "title", "snippet", "image_url", "price", "currency", "date_posted", "scraped_at"]
    out = [dict(zip(keys, r)) for r in rows]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    logger.info("Exported %d rows to %s", len(out), path)


def export_csv(conn: sqlite3.Connection, path: str) -> None:
    import csv
    cur = conn.cursor()
    cur.execute("SELECT url, title, snippet, image_url, price, currency, date_posted, scraped_at FROM listings ORDER BY scraped_at DESC")
    rows = cur.fetchall()
    keys = ["url", "title", "snippet", "image_url", "price", "currency", "date_posted", "scraped_at"]
    with open(path, "w", encoding="utf-8', newline='") as f:  # noqa: W605
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerows(rows)
    logger.info("Exported %d rows to %s", len(rows), path)


def parse_args():
    p = argparse.ArgumentParser(description="Fora.ua category scraper")
    p.add_argument("--start-url", default=BASE_CATEGORY_URL)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--json", help="Export JSON file path after scraping")
    p.add_argument("--csv", help="Export CSV file path after scraping")
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

    try:
        results = scrape_category(args.start_url, conn, max_pages=args.max_pages, session=session)
        logger.info("Scraped total items: %d", len(results))
    except SystemExit as e:
        logger.error("Aborted: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.exception("Scraping failed: %s", e)
        sys.exit(2)

    if args.json:
        export_json(conn, args.json)
    if args.csv:
        export_csv(conn, args.csv)
    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Скрапер для категорії «Молочні продукти та яйця» на Novus (Zakaz.ua).

- Збирає назву, ціну, валюту, опис, посилання на зображення та URL.
- Зберігає дані інкрементально у SQLite та експортує у Excel.
- Веде файл прогресу.

Запуск:
    python novus_scraper.py --db data/novus_listings.db \
                            --excel data/novus_listings.xlsx \
                            --progress data/novus_progress.txt
"""

import argparse
import logging
import os
import re
import sqlite3
import time
from typing import Dict, List, Optional

import backoff
import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_CATEGORY_URL = "https://novus.zakaz.ua/uk/categories/dairy-and-eggs/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/118.0.0.0 Safari/537.36"
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")


def log_progress(progress_path: str, message: str) -> None:
    os.makedirs(os.path.dirname(progress_path), exist_ok=True)
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


@backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=5)
def fetch(session: requests.Session, url: str) -> str:
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text


def extract_product_links(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/uk/products/"):
            full_url = "https://novus.zakaz.ua" + href
            links.append(full_url)
    # унікальні
    return list(dict.fromkeys(links))


def parse_product_page(session: requests.Session, url: str) -> Dict[str, Optional[str]]:
    html = fetch(session, url)
    soup = BeautifulSoup(html, "lxml")
    title = None
    price = None
    currency = None
    description = None
    image_url = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    text = soup.get_text(" ", strip=True)
    m = re.search(r"([\d,.]+)\s*₴", text)
    if m:
        price = float(m.group(1).replace(",", "."))
        currency = "₴"
    desc_el = (
        soup.find("p", class_=re.compile("product-description"))
        or soup.find("div", {"data-testid": "product-description"})
        or soup.find("p")
    )
    if desc_el:
        description = desc_el.get_text(strip=True)
    img_el = soup.find("img", {"src": re.compile(r"^https://")})
    if img_el:
        image_url = img_el["src"]
    return {
        "title": title,
        "price": price,
        "currency": currency,
        "description": description,
        "image_url": image_url,
        "url": url,
    }


def scrape_category(max_pages: Optional[int], progress_path: str) -> List[Dict[str, Optional[str]]]:
    session = get_session()
    all_products: List[Dict[str, Optional[str]]] = []
    page_num = 1
    while True:
        url = BASE_CATEGORY_URL + (f"?page={page_num}" if page_num > 1 else "")
        logging.info(f"Завантаження сторінки {page_num}: {url}")
        log_progress(progress_path, f"Категорія Novus: сторінка {page_num} ({url})")
        try:
            html = fetch(session, url)
        except requests.HTTPError as e:
            logging.error(f"Не вдалося завантажити {url}: {e}")
            break
        product_links = extract_product_links(html)
        if not product_links:
            logging.info("Немає нових посилань на товари. Завершення скрапінгу.")
            break
        for link in product_links:
            try:
                data = parse_product_page(session, link)
                all_products.append(data)
                log_progress(progress_path, f"Отримано товар Novus: {data['title']} ({link})")
            except requests.HTTPError as e:
                logging.error(f"Помилка завантаження товару {link}: {e}")
            time.sleep(0.2)
        page_num += 1
        if max_pages is not None and page_num > max_pages:
            break
    return all_products


def save_to_db(products: List[Dict[str, Optional[str]]], db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            price REAL,
            currency TEXT,
            description TEXT,
            image_url TEXT,
            url TEXT UNIQUE
        )
        """
    )
    for p in products:
        cur.execute(
            """
            INSERT OR REPLACE INTO products
            (title, price, currency, description, image_url, url)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                p["title"],
                p["price"],
                p["currency"],
                p["description"],
                p["image_url"],
                p["url"],
            ),
        )
    conn.commit()
    conn.close()


def export_to_excel(products: List[Dict[str, Optional[str]]], excel_path: str) -> None:
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    df = pd.DataFrame(products)
    df.to_excel(excel_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Novus/Zakaz.ua category scraper")
    parser.add_argument("--db", default="data/novus_listings.db", help="Шлях до SQLite-бази")
    parser.add_argument("--excel", default="data/novus_listings.xlsx", help="Шлях до Excel-файлу")
    parser.add_argument("--progress", default="data/novus_progress.txt", help="Файл для прогресу")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Максимальна кількість сторінок для скрапінгу")
    args = parser.parse_args()

    products = scrape_category(args.max_pages, args.progress)
    save_to_db(products, args.db)
    export_to_excel(products, args.excel)
    logging.info(f"Зібрано {len(products)} товарів на Novus.")


if __name__ == "__main__":
    main()

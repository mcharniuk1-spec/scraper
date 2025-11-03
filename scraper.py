#!/usr/bin/env python3
"""
Скрапер для категорії «Молочні продукти та яйця» на Fora.ua.

- Збирає назву, повну назву, ціну, валюту, опис та URL товару.
- Підтримує інкрементальне оновлення бази даних (використовує URL як унікальний ключ).
- Експортує результати у SQLite та Excel.
- Логує прогрес у текстовий файл.

Запуск:
    python scraper.py --db data/fora_listings.db --excel data/fora_listings.xlsx \
                      --progress data/progress_fora.txt --max-pages 3
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

# Базова URL-адреса категорії
BASE_CATEGORY_URL = "https://fora.ua/category/molochni-produkty-ta-iaitsia-2656"

# Заголовок User-Agent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/118.0.0.0 Safari/537.36"
)

# Налаштування логування (у консоль)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def log_progress(progress_path: str, message: str) -> None:
    """Додає запис про прогрес у текстовий файл."""
    os.makedirs(os.path.dirname(progress_path), exist_ok=True)
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")


def get_session() -> requests.Session:
    """Створює HTTP-сесію з потрібним заголовком User-Agent."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


@backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=5)
def fetch(session: requests.Session, url: str) -> str:
    """Завантажує HTML сторінки з повторними спробами у випадку помилки."""
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text


def parse_item_block(block: BeautifulSoup) -> Dict[str, Optional[str]]:
    """
    Виймає з блоку товару (карточки) основні дані:
    назва, повна назва, ціна, валюта та URL на сторінку товару.
    """
    # Назва товару
    title_el = block.find("div", class_=re.compile(r"(product-card__title|product-card__name)"))
    title = title_el.get_text(strip=True) if title_el else None

    # Посилання
    link_el = block.find("a", href=True)
    url = "https://fora.ua" + link_el["href"] if link_el else None

    # Початкова ціна і валюта
    price = None
    currency = None
    price_el = block.find("span", class_=re.compile(r"price"))
    if price_el:
        text = price_el.get_text(strip=True)
        match = re.search(r"([\d,.]+)\s*₴", text)
        if match:
            price = float(match.group(1).replace(",", "."))
            currency = "₴"

    return {
        "title": title,
        "full_name": None,
        "price": price,
        "currency": currency,
        "description": None,
        "url": url,
    }


def parse_product_page(session: requests.Session, url: str) -> Dict[str, Optional[str]]:
    """
    Завантажує сторінку товару для отримання повної назви, опису
    та точнішої ціни (якщо не було на карточці).
    """
    html = fetch(session, url)
    soup = BeautifulSoup(html, "lxml")

    full_name = None
    description = None
    price = None
    currency = None

    # Повна назва товару
    name_el = soup.find("h1")
    if name_el:
        full_name = name_el.get_text(strip=True)

    # Опис товару
    desc_el = (
        soup.find("p", class_=re.compile("product-description"))
        or soup.find("div", class_=re.compile("product-description"))
        or soup.find("p")
    )
    if desc_el:
        description = desc_el.get_text(strip=True)

    # Ціна на сторінці товару
    page_text = soup.get_text(" ", strip=True)
    match = re.search(r"([\d,.]+)\s*₴", page_text)
    if match:
        price = float(match.group(1).replace(",", "."))
        currency = "₴"

    return {
        "full_name": full_name,
        "description": description,
        "price": price,
        "currency": currency,
    }


def scrape_category(max_pages: Optional[int], progress_path: str) -> List[Dict[str, Optional[str]]]:
    """
    Ітерується по сторінках категорії та збирає інформацію про всі товари.
    max_pages: максимальна кількість сторінок для перегляду (None = усі доступні).
    progress_path: шлях до txt-файлу для логування прогресу.
    """
    session = get_session()
    products: List[Dict[str, Optional[str]]] = []
    page_num = 1

    while True:
        url = BASE_CATEGORY_URL + (f"?page={page_num}" if page_num > 1 else "")
        logging.info(f"Завантаження сторінки {page_num}: {url}")
        log_progress(progress_path, f"Категорія: сторінка {page_num} ({url})")
        try:
            html = fetch(session, url)
        except requests.HTTPError as e:
            logging.error(f"Помилка завантаження {url}: {e}")
            break

        soup = BeautifulSoup(html, "lxml")
        blocks = soup.find_all("div", class_=re.compile(r"product-card"))
        if not blocks:
            logging.info("На сторінці немає товарних карточок. Завершення.")
            break

        logging.info(f"Знайдено {len(blocks)} товарів на сторінці {page_num}")
        for block in blocks:
            item_data = parse_item_block(block)
            # Якщо дані не повні – переходимо на сторінку товару
            if (item_data["full_name"] is None or item_data["price"] is None) and item_data["url"]:
                try:
                    extra = parse_product_page(session, item_data["url"])
                    # доповнюємо відсутні значення
                    for key, value in extra.items():
                        if item_data.get(key) in (None, "") and value:
                            item_data[key] = value
                except requests.HTTPError as e:
                    logging.error(f"Помилка завантаження товару {item_data['url']}: {e}")

            products.append(item_data)
            # Логування поштучного запису прогресу
            log_progress(progress_path, f"Отримано товар: {item_data['title']} ({item_data['url']})")
            time.sleep(0.2)

        page_num += 1
        if max_pages is not None and page_num > max_pages:
            break

    return products


def save_to_db(products: List[Dict[str, Optional[str]]], db_path: str) -> None:
    """
    Створює таблицю (якщо треба) та зберігає/оновлює дані в SQLite.
    Використовує URL як унікальний ключ.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            full_name TEXT,
            price REAL,
            currency TEXT,
            description TEXT,
            url TEXT UNIQUE
        )
        """
    )
    for prod in products:
        cur.execute(
            """
            INSERT OR REPLACE INTO products
            (title, full_name, price, currency, description, url)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                prod.get("title"),
                prod.get("full_name"),
                prod.get("price"),
                prod.get("currency"),
                prod.get("description"),
                prod.get("url"),
            ),
        )
    conn.commit()
    conn.close()


def export_to_excel(products: List[Dict[str, Optional[str]]], excel_path: str) -> None:
    """Експортує список словників у Excel (формат .xlsx)."""
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    df = pd.DataFrame(products)
    df.to_excel(excel_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fora.ua category scraper")
    parser.add_argument("--db", default="data/fora_listings.db", help="Шлях до SQLite-бази")
    parser.add_argument("--excel", default="data/fora_listings.xlsx", help="Шлях до Excel-файлу")
    parser.add_argument("--progress", default="data/progress_fora.txt", help="Файл для запису прогресу")
    parser.add_argument("--max-pages", type=int, default=None, help="Максимальна кількість сторінок")
    args = parser.parse_args()

    products = scrape_category(args.max_pages, args.progress)
    save_to_db(products, args.db)
    export_to_excel(products, args.excel)
    logging.info(f"Зібрано {len(products)} товарів.")


if __name__ == "__main__":
    main()

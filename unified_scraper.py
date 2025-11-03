#!/usr/bin/env python3
"""
Об'єднаний скрапер для українських інтернет-магазинів.

Підтримувані сайти:
- Fora.ua (Молочні продукти та яйця)
- Novus/Zakaz.ua (Молочні продукти та яйця)
- Готовий до розширення для інших сайтів

Особливості:
- Інкрементальне оновлення бази даних
- Експорт у SQLite та Excel
- Детальне логування прогресу
- Відновлення після збоїв
- Конфігурація через JSON
- Ротація User-Agent

Запуск:
    python unified_scraper.py --config config.json --max-pages 10
"""

import argparse
import json
import logging
import os
import random
import re
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import backoff
import pandas as pd
import requests
from bs4 import BeautifulSoup

# Константи
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0"
]

DEFAULT_CONFIG = {
    "sites": {
        "fora": {
            "name": "Fora.ua",
            "base_url": "https://fora.ua/category/molochni-produkty-ta-iaitsia-2656",
            "enabled": True,
            "max_pages": 5,
            "delay": 0.2,
            "selectors": {
                "product_cards": "div[class*='product-card']",
                "title": "div[class*='product-card__title'], div[class*='product-card__name']",
                "price": "span[class*='price']",
                "link": "a[href]",
                "page_title": "h1",
                "description": "p[class*='product-description'], div[class*='product-description'], p"
            }
        },
        "novus": {
            "name": "Novus/Zakaz.ua",
            "base_url": "https://novus.zakaz.ua/uk/categories/dairy-and-eggs/",
            "enabled": True,
            "max_pages": 10,
            "delay": 0.1,
            "selectors": {
                "product_links": "a[href*='/uk/products/']",
                "page_title": "h1",
                "description": "p[class*='product-description'], div[data-testid='product-description'], p",
                "image": "img[src^='https://']"
            }
        }
    },
    "database": {
        "path": "data/unified_products.db",
        "backup_enabled": True
    },
    "export": {
        "excel_path": "data/unified_products.xlsx",
        "progress_path": "data/unified_progress.txt"
    },
    "scraping": {
        "request_timeout": 10,
        "max_retries": 5,
        "user_agent_rotation": True,
        "session_renewal_interval": 50
    }
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler('data/scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ProgressTracker:
    """Клас для відстеження прогресу скрапінгу."""
    
    def __init__(self, progress_path: str):
        self.progress_path = progress_path
        self.stats = {
            "start_time": None,
            "sites": {},
            "total_products": 0,
            "errors": 0,
            "last_update": None
        }
        self._ensure_directory()
        self._load_existing_progress()
    
    def _ensure_directory(self):
        os.makedirs(os.path.dirname(self.progress_path), exist_ok=True)
    
    def _load_existing_progress(self):
        """Завантажуємо існуючий прогрес, якщо є."""
        if os.path.exists(self.progress_path):
            try:
                with open(self.progress_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        last_line = lines[-1].strip()
                        if "Total products:" in last_line:
                            match = re.search(r"Total products: (\d+)", last_line)
                            if match:
                                self.stats["total_products"] = int(match.group(1))
            except Exception as e:
                logger.warning(f"Не вдалося завантажити прогрес: {e}")
    
    def start_scraping(self):
        self.stats["start_time"] = datetime.now()
        self._log_message("=== Початок скрапінгу ===")
    
    def start_site(self, site_name: str):
        self.stats["sites"][site_name] = {
            "start_time": datetime.now(),
            "pages_processed": 0,
            "products_found": 0,
            "errors": 0
        }
        self._log_message(f"Початок скрапінгу сайту: {site_name}")
    
    def log_page(self, site_name: str, page_num: int, products_count: int):
        if site_name in self.stats["sites"]:
            self.stats["sites"][site_name]["pages_processed"] += 1
            self.stats["sites"][site_name]["products_found"] += products_count
            self.stats["total_products"] += products_count
        
        self._log_message(f"{site_name}: Сторінка {page_num} - знайдено {products_count} товарів")
    
    def log_product(self, site_name: str, product_title: str, url: str):
        self._log_message(f"{site_name}: Оброблено товар '{product_title}' ({url})")
    
    def log_error(self, site_name: str, error_msg: str):
        self.stats["errors"] += 1
        if site_name in self.stats["sites"]:
            self.stats["sites"][site_name]["errors"] += 1
        self._log_message(f"ПОМИЛКА {site_name}: {error_msg}")
    
    def finish_site(self, site_name: str):
        if site_name in self.stats["sites"]:
            site_stats = self.stats["sites"][site_name]
            duration = datetime.now() - site_stats["start_time"]
            self._log_message(
                f"Завершено {site_name}: {site_stats['pages_processed']} сторінок, "
                f"{site_stats['products_found']} товарів, {site_stats['errors']} помилок. "
                f"Тривалість: {duration}"
            )
    
    def finish_scraping(self):
        if self.stats["start_time"]:
            duration = datetime.now() - self.stats["start_time"]
            self._log_message(
                f"=== Скрапінг завершено за {duration} ==="
            )
            self._log_message(
                f"Total products: {self.stats['total_products']}, "
                f"Total errors: {self.stats['errors']}"
            )
    
    def _log_message(self, message: str):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.progress_path, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} - {message}\n")
        logger.info(message)


class DatabaseManager:
    """Менеджер бази даних з підтримкою резервного копіювання."""
    
    def __init__(self, db_path: str, backup_enabled: bool = True):
        self.db_path = db_path
        self.backup_enabled = backup_enabled
        self._ensure_directory()
        self._init_database()
    
    def _ensure_directory(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    def _init_database(self):
        """Ініціалізуємо базу даних з покращеною схемою."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Створюємо основну таблицю товарів
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_name TEXT NOT NULL,
                title TEXT,
                full_name TEXT,
                price REAL,
                currency TEXT,
                description TEXT,
                image_url TEXT,
                url TEXT NOT NULL UNIQUE,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Створюємо індекси для покращення продуктивності
        cur.execute("CREATE INDEX IF NOT EXISTS idx_site_name ON products(site_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_url ON products(url)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_last_updated ON products(last_updated)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_is_active ON products(is_active)")
        
        # Таблиця для логування скрапінгу
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scraping_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_name TEXT NOT NULL,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                pages_processed INTEGER DEFAULT 0,
                products_found INTEGER DEFAULT 0,
                products_updated INTEGER DEFAULT 0,
                errors_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"База даних ініціалізована: {self.db_path}")
    
    def save_products(self, products: List[Dict], site_name: str) -> Tuple[int, int]:
        """Зберігаємо товари з підрахунком нових та оновлених записів."""
        if not products:
            return 0, 0
        
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        new_count = 0
        updated_count = 0
        
        for product in products:
            # Перевіряємо, чи існує товар
            cur.execute("SELECT id, price FROM products WHERE url = ?", (product['url'],))
            existing = cur.fetchone()
            
            if existing:
                # Оновлюємо існуючий товар
                cur.execute("""
                    UPDATE products SET 
                        title = COALESCE(?, title),
                        full_name = COALESCE(?, full_name),
                        price = COALESCE(?, price),
                        currency = COALESCE(?, currency),
                        description = COALESCE(?, description),
                        image_url = COALESCE(?, image_url),
                        last_updated = CURRENT_TIMESTAMP,
                        is_active = 1
                    WHERE url = ?
                """, (
                    product.get('title'),
                    product.get('full_name'),
                    product.get('price'),
                    product.get('currency'),
                    product.get('description'),
                    product.get('image_url'),
                    product['url']
                ))
                updated_count += 1
            else:
                # Вставляємо новий товар
                cur.execute("""
                    INSERT INTO products 
                    (site_name, title, full_name, price, currency, description, image_url, url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    site_name,
                    product.get('title'),
                    product.get('full_name'),
                    product.get('price'),
                    product.get('currency'),
                    product.get('description'),
                    product.get('image_url'),
                    product['url']
                ))
                new_count += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"Збережено в БД: {new_count} нових, {updated_count} оновлених товарів")
        return new_count, updated_count
    
    def get_all_products(self) -> pd.DataFrame:
        """Отримуємо всі активні товари для експорту."""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM products WHERE is_active = 1 ORDER BY site_name, last_updated DESC",
            conn
        )
        conn.close()
        return df
    
    def create_backup(self):
        """Створюємо резервну копію бази даних."""
        if not self.backup_enabled or not os.path.exists(self.db_path):
            return
        
        backup_path = f"{self.db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            import shutil
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"Створено резервну копію: {backup_path}")
        except Exception as e:
            logger.error(f"Помилка створення резервної копії: {e}")


class UnifiedScraper:
    """Головний клас скрапера з підтримкою множинних сайтів."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.session = self._create_session()
        self.requests_count = 0
        
        # Ініціалізуємо менеджерів
        self.db_manager = DatabaseManager(
            self.config['database']['path'],
            self.config['database']['backup_enabled']
        )
        self.progress_tracker = ProgressTracker(
            self.config['export']['progress_path']
        )
    
    def _create_session(self) -> requests.Session:
        """Створюємо сесію з налаштуваннями."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        return session
    
    def _renew_session(self):
        """Оновлюємо сесію для уникнення блокування."""
        self.session.close()
        self.session = self._create_session()
        logger.info("Сесію оновлено")
    
    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        max_tries=5
    )
    def _fetch_page(self, url: str) -> str:
        """Завантажуємо сторінку з обробкою помилок."""
        # Оновлюємо User-Agent при потребі
        if (self.config['scraping']['user_agent_rotation'] and 
            self.requests_count % 10 == 0):
            self.session.headers['User-Agent'] = random.choice(USER_AGENTS)
        
        # Оновлюємо сесію при потребі
        if self.requests_count % self.config['scraping']['session_renewal_interval'] == 0:
            self._renew_session()
        
        response = self.session.get(
            url, 
            timeout=self.config['scraping']['request_timeout']
        )
        response.raise_for_status()
        self.requests_count += 1
        
        return response.text
    
    def _extract_price(self, text: str) -> Tuple[Optional[float], Optional[str]]:
        """Витягуємо ціну та валюту з тексту."""
        price_patterns = [
            r"([\d,]+\.?\d*)\s*₴",
            r"([\d,]+\.?\d*)\s*грн",
            r"([\d,]+\.?\d*)\s*UAH"
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    price = float(match.group(1).replace(',', '.'))
                    currency = "₴" if "₴" in match.group(0) else "грн"
                    return price, currency
                except ValueError:
                    continue
        
        return None, None
    
    def _scrape_fora_products(self, site_config: Dict, max_pages: Optional[int]) -> List[Dict]:
        """Скрапимо товари з Fora.ua."""
        products = []
        page_num = 1
        max_pages = max_pages or site_config['max_pages']
        
        while page_num <= max_pages:
            url = site_config['base_url']
            if page_num > 1:
                url += f"?page={page_num}"
            
            try:
                html = self._fetch_page(url)
                soup = BeautifulSoup(html, 'lxml')
                
                # Знаходимо товарні картки
                product_cards = soup.select(site_config['selectors']['product_cards'])
                
                if not product_cards:
                    logger.info(f"Fora: Сторінка {page_num} не містить товарів, завершуємо")
                    break
                
                page_products = []
                for card in product_cards:
                    product = self._parse_fora_product_card(card, site_config)
                    if product and product['url']:
                        # Доповнюємо інформацію зі сторінки товару
                        try:
                            detailed_info = self._parse_fora_product_page(
                                product['url'], site_config
                            )
                            product.update(detailed_info)
                            time.sleep(site_config['delay'])
                        except Exception as e:
                            self.progress_tracker.log_error(
                                "Fora", f"Помилка парсингу товару {product['url']}: {e}"
                            )
                        
                        page_products.append(product)
                        self.progress_tracker.log_product(
                            "Fora", product.get('title', 'Без назви'), product['url']
                        )
                
                products.extend(page_products)
                self.progress_tracker.log_page("Fora", page_num, len(page_products))
                
                page_num += 1
                time.sleep(site_config['delay'])
                
            except Exception as e:
                self.progress_tracker.log_error(
                    "Fora", f"Помилка завантаження сторінки {page_num}: {e}"
                )
                break
        
        return products
    
    def _parse_fora_product_card(self, card: BeautifulSoup, site_config: Dict) -> Dict:
        """Парсимо картку товару Fora."""
        # Назва товару
        title_element = card.select_one(site_config['selectors']['title'])
        title = title_element.get_text(strip=True) if title_element else None
        
        # Посилання на товар
        link_element = card.select_one(site_config['selectors']['link'])
        url = None
        if link_element and link_element.get('href'):
            url = urljoin("https://fora.ua", link_element['href'])
        
        # Ціна
        price_element = card.select_one(site_config['selectors']['price'])
        price, currency = None, None
        if price_element:
            price, currency = self._extract_price(price_element.get_text(strip=True))
        
        return {
            'title': title,
            'full_name': None,
            'price': price,
            'currency': currency,
            'description': None,
            'image_url': None,
            'url': url
        }
    
    def _parse_fora_product_page(self, url: str, site_config: Dict) -> Dict:
        """Парсимо детальну сторінку товару Fora."""
        html = self._fetch_page(url)
        soup = BeautifulSoup(html, 'lxml')
        
        # Повна назва товару
        title_element = soup.select_one(site_config['selectors']['page_title'])
        full_name = title_element.get_text(strip=True) if title_element else None
        
        # Опис товару
        desc_element = soup.select_one(site_config['selectors']['description'])
        description = desc_element.get_text(strip=True) if desc_element else None
        
        # Ціна зі сторінки (якщо не було на картці)
        page_text = soup.get_text(" ", strip=True)
        price, currency = self._extract_price(page_text)
        
        return {
            'full_name': full_name,
            'description': description,
            'price': price,
            'currency': currency
        }
    
    def _scrape_novus_products(self, site_config: Dict, max_pages: Optional[int]) -> List[Dict]:
        """Скрапимо товари з Novus/Zakaz.ua."""
        products = []
        page_num = 1
        max_pages = max_pages or site_config['max_pages']
        
        while page_num <= max_pages:
            url = site_config['base_url']
            if page_num > 1:
                url += f"?page={page_num}"
            
            try:
                html = self._fetch_page(url)
                product_links = self._extract_novus_product_links(html)
                
                if not product_links:
                    logger.info(f"Novus: Сторінка {page_num} не містить товарів, завершуємо")
                    break
                
                page_products = []
                for link in product_links:
                    try:
                        product = self._parse_novus_product_page(link, site_config)
                        if product:
                            page_products.append(product)
                            self.progress_tracker.log_product(
                                "Novus", product.get('title', 'Без назви'), product['url']
                            )
                        time.sleep(site_config['delay'])
                    except Exception as e:
                        self.progress_tracker.log_error(
                            "Novus", f"Помилка парсингу товару {link}: {e}"
                        )
                
                products.extend(page_products)
                self.progress_tracker.log_page("Novus", page_num, len(page_products))
                
                page_num += 1
                time.sleep(site_config['delay'])
                
            except Exception as e:
                self.progress_tracker.log_error(
                    "Novus", f"Помилка завантаження сторінки {page_num}: {e}"
                )
                break
        
        return products
    
    def _extract_novus_product_links(self, html: str) -> List[str]:
        """Витягуємо посилання на товари Novus."""
        soup = BeautifulSoup(html, 'lxml')
        links = set()
        
        for link in soup.select("a[href*='/uk/products/']"):
            href = link.get('href')
            if href and '/uk/products/' in href:
                full_url = urljoin("https://novus.zakaz.ua", href)
                links.add(full_url)
        
        return list(links)
    
    def _parse_novus_product_page(self, url: str, site_config: Dict) -> Dict:
        """Парсимо сторінку товару Novus."""
        html = self._fetch_page(url)
        soup = BeautifulSoup(html, 'lxml')
        
        # Назва товару
        title_element = soup.select_one(site_config['selectors']['page_title'])
        title = title_element.get_text(strip=True) if title_element else None
        
        # Ціна
        page_text = soup.get_text(" ", strip=True)
        price, currency = self._extract_price(page_text)
        
        # Опис
        desc_element = soup.select_one(site_config['selectors']['description'])
        description = desc_element.get_text(strip=True) if desc_element else None
        
        # Зображення
        img_element = soup.select_one(site_config['selectors']['image'])
        image_url = img_element.get('src') if img_element else None
        
        return {
            'title': title,
            'full_name': title,
            'price': price,
            'currency': currency,
            'description': description,
            'image_url': image_url,
            'url': url
        }
    
    def scrape_site(self, site_key: str, max_pages: Optional[int] = None):
        """Скрапимо один сайт."""
        if site_key not in self.config['sites']:
            logger.error(f"Сайт {site_key} не знайдений у конфігурації")
            return
        
        site_config = self.config['sites'][site_key]
        if not site_config.get('enabled', True):
            logger.info(f"Сайт {site_key} вимкнений, пропускаємо")
            return
        
        self.progress_tracker.start_site(site_config['name'])
        
        try:
            if site_key == 'fora':
                products = self._scrape_fora_products(site_config, max_pages)
            elif site_key == 'novus':
                products = self._scrape_novus_products(site_config, max_pages)
            else:
                logger.error(f"Невідомий тип сайту: {site_key}")
                return
            
            if products:
                self.db_manager.save_products(products, site_config['name'])
            
            self.progress_tracker.finish_site(site_config['name'])
            
        except Exception as e:
            self.progress_tracker.log_error(
                site_config['name'], f"Критична помилка скрапінгу: {e}"
            )
    
    def scrape_all_sites(self, max_pages: Optional[int] = None):
        """Скрапимо всі увімкнені сайти."""
        self.progress_tracker.start_scraping()
        
        # Створюємо резервну копію перед початком
        self.db_manager.create_backup()
        
        for site_key in self.config['sites']:
            if self.config['sites'][site_key].get('enabled', True):
                self.scrape_site(site_key, max_pages)
        
        # Експортуємо результати
        self.export_to_excel()
        
        self.progress_tracker.finish_scraping()
        self.session.close()
    
    def export_to_excel(self):
        """Експортуємо дані в Excel."""
        try:
            df = self.db_manager.get_all_products()
            if not df.empty:
                excel_path = self.config['export']['excel_path']
                os.makedirs(os.path.dirname(excel_path), exist_ok=True)
                
                # Створюємо кілька листів для різних сайтів
                with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                    # Загальний лист
                    df.to_excel(writer, sheet_name='Всі товари', index=False)
                    
                    # Окремі листи для кожного сайту
                    for site in df['site_name'].unique():
                        site_df = df[df['site_name'] == site]
                        sheet_name = site[:30]  # Excel обмежує назви листів
                        site_df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                logger.info(f"Дані експортовані в Excel: {excel_path} ({len(df)} товарів)")
            else:
                logger.warning("Немає даних для експорту")
        except Exception as e:
            logger.error(f"Помилка експорту в Excel: {e}")


def load_config(config_path: str) -> Dict:
    """Завантажуємо конфігурацію з файлу або створюємо за замовчуванням."""
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info(f"Конфігурація завантажена з {config_path}")
            return config
        except Exception as e:
            logger.error(f"Помилка завантаження конфігурації: {e}")
    
    # Створюємо конфігурацію за замовчуванням
    logger.info("Використовуємо конфігурацію за замовчуванням")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    logger.info(f"Конфігурацію збережено в {config_path}")
    
    return DEFAULT_CONFIG


def main():
    parser = argparse.ArgumentParser(
        description="Об'єднаний скрапер українських інтернет-магазинів"
    )
    parser.add_argument(
        "--config", 
        default="config.json", 
        help="Шлях до файлу конфігурації"
    )
    parser.add_argument(
        "--site", 
        choices=['fora', 'novus', 'all'], 
        default="all",
        help="Який сайт скрапити (за замовчуванням: всі)"
    )
    parser.add_argument(
        "--max-pages", 
        type=int, 
        help="Максимальна кількість сторінок для скрапінгу"
    )
    parser.add_argument(
        "--export-only", 
        action="store_true",
        help="Тільки експортувати існуючі дані в Excel"
    )
    
    args = parser.parse_args()
    
    # Завантажуємо конфігурацію
    config = load_config(args.config)
    
    # Створюємо скрапер
    scraper = UnifiedScraper(config)
    
    if args.export_only:
        # Тільки експорт
        scraper.export_to_excel()
        return
    
    # Запускаємо скрапінг
    if args.site == 'all':
        scraper.scrape_all_sites(args.max_pages)
    else:
        scraper.scrape_site(args.site, args.max_pages)


if __name__ == "__main__":
    main()
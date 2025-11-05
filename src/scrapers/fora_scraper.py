from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from src.core.scraper_base import BaseScraper
import logging

logger = logging.getLogger(__name__)

class ForaScraper(BaseScraper):
    """Scraper for Fora.ua using Playwright."""
    def __init__(self, config: Dict, progress_file: str):
        super().__init__(config, progress_file)
        self.base_url = config['base_url']
        self.site_name = config['site_name']
        self.selectors = config['selectors']

    def scrape_products(self, max_pages: Optional[int] = None) -> List[Dict]:
        """Скрапінг сторінок каталогу методом headless."""
        products = []
        max_pages = max_pages or self.config.get('max_pages', 10)
        self.log_progress(f"🚀 Запускаємо скрейпінг Fora до {max_pages} сторінок")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for page_num in range(1, max_pages + 1):
                url = self._build_page_url(page_num)
                self.log_progress(f"📄 Опрацьовуємо сторінку {page_num}/{max_pages}: {url}")
                try:
                    page.goto(url, timeout=self.config.get('timeout', 30000))
                    # дочекаємося, поки з’являться картки товарів
                    page.wait_for_selector(self.selectors['product_cards'], timeout=15000)
                    html = page.content()
                except Exception as e:
                    self.log_error(f"Не вдалося завантажити сторінку {page_num}: {e}")
                    break

                soup = BeautifulSoup(html, 'html.parser')
                cards = self._find_product_cards(soup)
                if not cards:
                    self.log_progress(f"⚠️ На сторінці {page_num} немає товарів, зупиняємось")
                    break

                for i, card in enumerate(cards, 1):
                    try:
                        product = self._parse_product_card(card)
                        if product and product.get('url'):
                            details = self.parse_product_page(product['url'], page)
                            if details:
                                product.update(details)
                            products.append(product)
                            self.log_progress(f"  ✅ Товар {i}: {product.get('product_name')[:50]}")
                    except Exception as e:
                        self.log_error(f"Помилка при обробці картки {i} на сторінці {page_num}: {e}")
                self.products_found += len(cards)
            browser.close()

        self.log_progress(f"🎉 Завершено Fora: знайдено {len(products)} товарів")
        return products

    def parse_product_page(self, url: str, page) -> Optional[Dict]:
        """Відкриває сторінку товару у вже відкритому браузері."""
        try:
            page.goto(url, timeout=self.config.get('timeout', 30000))
            page.wait_for_load_state('domcontentloaded')
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            data = {}
            title = self._extract_page_title(soup)
            if title:
                data['product_name'] = title
            description = self._extract_description(soup)
            if description:
                data['description'] = description
            price = self._extract_page_price(soup)
            if price:
                data['price'] = price
            img = self._extract_image(soup)
            if img:
                data['image_url'] = img
            availability = self._extract_page_availability(soup)
            data['availability'] = availability
            return data
        except Exception as e:
            self.log_error(f"Не вдалося розібрати сторінку {url}: {e}")
            return None

from src.core.scraper_base import BaseScraper
from src.core.database import DatabaseManager
from bs4 import BeautifulSoup

class ForaScraper(BaseScraper):
    def scrape(self, start_url, max_pages=0):
        records, page = [], 1
        while True:
            html = self.fetch(f"{start_url}?page={page}")
            soup = self.parse_html(html)
            items = soup.select(".product-card__content")
            if not items:
                break
            for it in items:
                title = it.select_one(".product-card__title").get_text(strip=True)
                price_tag = it.select_one(".product-card__price-current")
                price = float(price_tag.text.split()[0].replace(",", ".")) if price_tag else 0.0
                link = it.select_one("a")["href"]
                records.append({
                    "title": title,
                    "price": price,
                    "url": f"https://fora.ua{link}"
                })
            if max_pages and page >= max_pages:
                break
            page += 1
            self.delay()
        return records

def run_fora(config):
    scraper = ForaScraper(**config)
    data = scraper.scrape(config["start_url"], config.get("max_pages", 0))
    db = DatabaseManager("data/fora_history.db")
    db.init_db()
    db.save_records("fora", data)
    db.export_to_excel("data/exports/fora_listings.xlsx")

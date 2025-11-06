import time, random, backoff, requests
from typing import List, Dict
from bs4 import BeautifulSoup

class BaseScraper:
    def __init__(self, base_url, user_agent, timeout=15, sleep_between_requests=1.0):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.timeout = timeout
        self.sleep_between_requests = sleep_between_requests

    @backoff.on_exception(backoff.expo, (requests.RequestException,), max_tries=5)
    def fetch(self, url):
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def random_delay(self):
        time.sleep(self.sleep_between_requests + random.uniform(0.3, 1.1))

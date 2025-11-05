#!/usr/bin/env python3
"""
Base Scraper Class

Provides common functionality for all scrapers including:
- HTTP session management with retries
- Robots.txt checking
- Rate limiting
- Error handling
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import backoff
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all scrapers."""

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout: int = 20,
        sleep_between_requests: float = 1.0,
        max_retries: int = 5,
    ):
        """
        Initialize base scraper.

        Args:
            base_url: Base URL for the site
            user_agent: User agent string
            timeout: Request timeout in seconds
            sleep_between_requests: Sleep time between requests
            max_retries: Maximum number of retries
        """
        self.base_url = base_url
        self.user_agent = user_agent
        self.timeout = timeout
        self.sleep_between_requests = sleep_between_requests
        self.max_retries = max_retries
        self.session = self._create_session()
        self._last_request_time = 0

    def _create_session(self) -> requests.Session:
        """Create and configure HTTP session."""
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=self.max_retries,
                backoff_factor=0.8,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=frozenset(["GET", "HEAD"]),
            )
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.sleep_between_requests:
            sleep_time = self.sleep_between_requests - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def is_allowed_by_robots(self, url: str, user_agent: str = "*") -> bool:
        """
        Check if URL is allowed by robots.txt.

        Args:
            url: URL to check
            user_agent: User agent to check (default: "*")

        Returns:
            True if allowed, False otherwise
        """
        try:
            parsed = requests.utils.urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            r = self.session.get(robots_url, timeout=self.timeout)
            if r.status_code != 200:
                logger.debug(
                    "robots.txt not found or returned %s; proceeding", r.status_code
                )
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
                elif ua and (
                    ua == "*" or self.user_agent.lower().startswith(ua.lower())
                ):
                    if line.lower().startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path and parsed.path.startswith(path):
                            allow = False
                            logger.info("Blocked by robots.txt: %s", path)
                            return False
            return allow
        except Exception as e:
            logger.warning(
                "Failed to check robots.txt: %s. Proceeding cautiously.", e
            )
            return True

    @backoff.on_exception(
        backoff.expo,
        (requests.exceptions.RequestException,),
        max_time=60,
    )
    def fetch(self, url: str) -> str:
        """
        Fetch HTML content from URL with retry logic.

        Args:
            url: URL to fetch

        Returns:
            HTML content as string

        Raises:
            requests.exceptions.RequestException: On fetch failure
        """
        self._rate_limit()
        logger.info("Fetching %s", url)
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    def parse_html(self, html: str) -> BeautifulSoup:
        """
        Parse HTML into BeautifulSoup object.

        Args:
            html: HTML content

        Returns:
            BeautifulSoup object
        """
        return BeautifulSoup(html, "lxml")

    @abstractmethod
    def scrape(self, start_url: str, max_pages: int = 0) -> List[Dict]:
        """
        Scrape listings from the site.

        Args:
            start_url: Starting URL
            max_pages: Maximum pages to scrape (0 = no limit)

        Returns:
            List of listing dictionaries
        """
        pass

    def cleanup(self):
        """Clean up resources."""
        if self.session:
            self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()

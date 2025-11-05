#!/usr/bin/env python3
"""
Main script to run scrapers

Usage:
    python scripts/run_scraper.py --site fora
    python scripts/run_scraper.py --site novus
    python scripts/run_scraper.py --site fora --config config/fora.json
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.historical_db import HistoricalDB
from src.scrapers.fora_scraper import ForaScraper
from src.scrapers.novus_scraper import NovusScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = os.path.join("data", "listings.db")


def load_config(config_path: str) -> dict:
    """Load configuration from JSON file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_default_config_path(site: str) -> str:
    """Get default configuration path for site."""
    return os.path.join("config", f"{site}.json")


def run_scraper(site: str, config_path: str = None, db_path: str = None, max_pages: int = 0):
    """
    Run scraper for specified site.

    Args:
        site: Site identifier ('fora' or 'novus')
        config_path: Path to configuration file (optional)
        db_path: Path to database file (optional)
        max_pages: Maximum pages to scrape (0 = no limit)
    """
    # Load configuration
    if config_path is None:
        config_path = get_default_config_path(site)
    
    if not os.path.exists(config_path):
        logger.error("Configuration file not found: %s", config_path)
        sys.exit(1)

    config = load_config(config_path)
    logger.info("Loaded configuration from %s", config_path)

    # Initialize database
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    # Determine max pages
    if max_pages == 0 and config.get("max_pages"):
        max_pages = config["max_pages"]

    # Initialize scraper
    scraper_class = {"fora": ForaScraper, "novus": NovusScraper}.get(site.lower())
    if not scraper_class:
        logger.error("Unknown site: %s. Supported sites: fora, novus", site)
        sys.exit(1)

    scraper = scraper_class(
        base_url=config.get("base_url"),
        user_agent=config.get("user_agent"),
        timeout=config.get("timeout", 20),
        sleep_between_requests=config.get("sleep_between_requests", 1.0),
        max_retries=config.get("max_retries", 5),
    )

    # Run scraper
    try:
        logger.info("Starting scraper for %s", site)
        start_url = config.get("start_url")
        results = scraper.scrape(start_url, max_pages=max_pages)
        logger.info("Scraped %d items", len(results))

        # Save to database
        with HistoricalDB(db_path) as db:
            new_count = 0
            updated_count = 0
            for item in results:
                is_new, listing_id = db.upsert_listing(
                    item,
                    site=config.get("site", site),
                    category=config.get("category"),
                )
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

            logger.info(
                "Database update: %d new, %d updated", new_count, updated_count
            )
            stats = db.get_stats(site=config.get("site", site))
            logger.info("Database stats: %s", stats)

    except Exception as e:
        logger.exception("Scraping failed: %s", e)
        sys.exit(2)
    finally:
        scraper.cleanup()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run scraper for specified site")
    parser.add_argument(
        "--site",
        required=True,
        choices=["fora", "novus"],
        help="Site to scrape",
    )
    parser.add_argument(
        "--config",
        help="Path to configuration file (default: config/{site}.json)",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Maximum pages to scrape (0 = no limit)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce logging output",
    )

    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    run_scraper(
        site=args.site,
        config_path=args.config,
        db_path=args.db,
        max_pages=args.max_pages,
    )


if __name__ == "__main__":
    main()

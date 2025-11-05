#!/usr/bin/env python3
"""
Monitoring Script

Monitors scraper progress and generates statistics reports.
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.historical_db import HistoricalDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join("data", "listings.db")
DEFAULT_PROGRESS_DIR = os.path.join("data")


def log_progress(db_path: str, site: str, progress_dir: str):
    """
    Log current progress to file.

    Args:
        db_path: Path to database
        site: Site identifier
        progress_dir: Directory for progress files
    """
    os.makedirs(progress_dir, exist_ok=True)
    progress_file = os.path.join(progress_dir, f"{site}_progress.txt")

    with HistoricalDB(db_path) as db:
        stats = db.get_stats(site=site)
        count = stats["total_listings"]

    timestamp = datetime.now(timezone.utc).isoformat()
    with open(progress_file, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{count}\n")

    logger.info("Logged progress for %s: %d listings", site, count)


def show_stats(db_path: str, site: str = None):
    """
    Display statistics about stored listings.

    Args:
        db_path: Path to database
        site: Site identifier (optional)
    """
    with HistoricalDB(db_path) as db:
        stats = db.get_stats(site=site)
        listings = db.get_listings(site=site, limit=10)

    print(f"\n{'='*60}")
    if site:
        print(f"Statistics for {site.upper()}")
    else:
        print("Overall Statistics")
    print(f"{'='*60}")
    print(f"Total listings: {stats['total_listings']}")
    print(f"Unique URLs: {stats['unique_urls']}")
    if stats["average_price"]:
        print(f"Average price: {stats['average_price']} грн")
    print(f"\nRecent listings:")
    print(f"{'-'*60}")
    for listing in listings:
        print(f"Title: {listing.get('title', 'N/A')[:50]}")
        print(f"URL: {listing.get('url', 'N/A')[:60]}")
        if listing.get("price"):
            print(f"Price: {listing.get('price')} {listing.get('currency', 'грн')}")
        print(f"Scraped: {listing.get('scraped_at', 'N/A')}")
        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Monitor scraper progress")
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--site",
        choices=["fora", "novus"],
        help="Site to monitor (optional)",
    )
    parser.add_argument(
        "--log-progress",
        action="store_true",
        help="Log progress to file",
    )
    parser.add_argument(
        "--progress-dir",
        default=DEFAULT_PROGRESS_DIR,
        help=f"Directory for progress files (default: {DEFAULT_PROGRESS_DIR})",
    )

    args = parser.parse_args()

    if args.log_progress:
        if not args.site:
            logger.error("--site required when using --log-progress")
            sys.exit(1)
        log_progress(args.db, args.site, args.progress_dir)
    else:
        show_stats(args.db, args.site)


if __name__ == "__main__":
    main()

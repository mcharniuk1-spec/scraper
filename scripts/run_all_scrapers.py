#!/usr/bin/env python3
"""
Unified script to run all scrapers

Runs both Fora and Novus scrapers, shows total products count,
and exports combined data to Excel.
"""
import argparse
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

DEFAULT_DB_PATH = os.path.join("data", "listings.db")
DEFAULT_EXCEL_PATH = os.path.join("data", "all_listings.xlsx")


def load_config(config_path: str) -> dict:
    """Load configuration from JSON file."""
    import json
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_fora_scraper(config_path: str, db_path: str, max_pages: int = 10):
    """
    Run Fora scraper specifically.
    
    Args:
        config_path: Path to Fora config file
        db_path: Path to database file
        max_pages: Maximum pages to scrape (default: 10)
    
    Returns:
        Number of items scraped
    """
    return run_scraper("fora", config_path, db_path, max_pages)


def run_novus_scraper(config_path: str, db_path: str, max_pages: int = 10):
    """
    Run Novus scraper specifically.
    
    Args:
        config_path: Path to Novus config file
        db_path: Path to database file
        max_pages: Maximum pages to scrape (default: 10)
    
    Returns:
        Number of items scraped
    """
    return run_scraper("novus", config_path, db_path, max_pages)


def run_scraper(site: str, config_path: str, db_path: str, max_pages: int = 10):
    """
    Run scraper for a specific site.
    
    Args:
        site: Site identifier ('fora' or 'novus')
        config_path: Path to config file
        db_path: Path to database file
        max_pages: Maximum pages to scrape (default: 10, 0 = no limit)
    
    Returns:
        Number of items scraped
    """
    config = load_config(config_path)
    
    # If max_pages is 0, use config default or 10
    if max_pages == 0:
        max_pages = config.get("max_pages", 10)
    
    scraper_class = {"fora": ForaScraper, "novus": NovusScraper}.get(site.lower())
    if not scraper_class:
        logger.error("Unknown site: %s", site)
        return 0

    scraper = scraper_class(
        base_url=config.get("base_url"),
        user_agent=config.get("user_agent"),
        timeout=config.get("timeout", 20),
        sleep_between_requests=config.get("sleep_between_requests", 1.0),
        max_retries=config.get("max_retries", 5),
    )

    try:
        logger.info("Starting scraper for %s (max_pages: %d)", site, max_pages)
        start_url = config.get("start_url")
        results = scraper.scrape(start_url, max_pages=max_pages)
        logger.info("Scraped %d items from %s", len(results), site)

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

            logger.info("%s: %d new, %d updated", site, new_count, updated_count)
            return len(results)
    except Exception as e:
        logger.exception("Scraping failed for %s: %s", site, e)
        return 0
    finally:
        scraper.cleanup()


def export_to_excel(db_path: str, excel_path: str):
    """Export all listings to Excel."""
    import pandas as pd
    
    with HistoricalDB(db_path) as db:
        listings = db.get_listings()
    
    if not listings:
        logger.warning("No listings to export")
        return
    
    os.makedirs(os.path.dirname(excel_path) or ".", exist_ok=True)
    df = pd.DataFrame(listings)
    df.to_excel(excel_path, index=False)
    logger.info("Exported %d listings to %s", len(listings), excel_path)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run all scrapers and export to Excel"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Maximum pages to scrape per site (default: 10, 0 = no limit)",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--excel",
        default=DEFAULT_EXCEL_PATH,
        help=f"Path to Excel output file (default: {DEFAULT_EXCEL_PATH})",
    )
    parser.add_argument(
        "--skip-fora",
        action="store_true",
        help="Skip Fora scraper",
    )
    parser.add_argument(
        "--skip-novus",
        action="store_true",
        help="Skip Novus scraper",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce logging output",
    )

    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    # Resolve paths relative to script location (project root)
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)  # Change to project root for consistent paths
    
    # Resolve database and Excel paths relative to project root
    if not os.path.isabs(args.db):
        args.db = os.path.join(script_dir, args.db)
    if not os.path.isabs(args.excel):
        args.excel = os.path.join(script_dir, args.excel)
    
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)

    total_products = 0
    scraper_errors = []
    
    # Use provided max_pages (default is 10, 0 means use config default)
    max_pages = args.max_pages
    
    # Run Fora scraper
    if not args.skip_fora:
        fora_config = os.path.join(script_dir, "config", "fora.json")
        if os.path.exists(fora_config):
            products = run_fora_scraper(fora_config, args.db, max_pages)
            total_products += products
            if products == 0:
                scraper_errors.append("Fora scraper found 0 items")
        else:
            logger.warning("Fora config not found: %s", fora_config)
            scraper_errors.append(f"Fora config not found: {fora_config}")
    else:
        logger.info("Skipping Fora scraper")

    # Run Novus scraper
    if not args.skip_novus:
        novus_config = os.path.join(script_dir, "config", "novus.json")
        if os.path.exists(novus_config):
            products = run_novus_scraper(novus_config, args.db, max_pages)
            total_products += products
        else:
            logger.warning("Novus config not found: %s", novus_config)
            scraper_errors.append(f"Novus config not found: {novus_config}")
    else:
        logger.info("Skipping Novus scraper")

    # Get final stats from database
    with HistoricalDB(args.db) as db:
        stats = db.get_stats()
        fora_stats = db.get_stats(site="fora")
        novus_stats = db.get_stats(site="novus")

    # Export to Excel
    export_to_excel(args.db, args.excel)

    # Print summary
    print("\n" + "="*60)
    print("SCRAPING SUMMARY")
    print("="*60)
    print(f"Total products scraped this run: {total_products}")
    print(f"\nDatabase Statistics:")
    print(f"  Total listings: {stats['total_listings']}")
    print(f"  Unique URLs: {stats['unique_urls']}")
    print(f"  Fora listings: {fora_stats['total_listings']}")
    print(f"  Novus listings: {novus_stats['total_listings']}")
    if stats["average_price"]:
        print(f"  Average price: {stats['average_price']} грн")
    print(f"\nData exported to: {args.excel}")
    
    if scraper_errors:
        print("\n⚠️  ISSUES DETECTED:")
        for error in scraper_errors:
            print(f"  - {error}")
    
    print("="*60 + "\n")


if __name__ == "__main__":
    main()

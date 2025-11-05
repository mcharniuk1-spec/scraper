#!/usr/bin/env python3
"""
Data Analysis Script

Analyzes scraped data and exports to various formats (JSON, CSV, Excel).
"""
import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.historical_db import HistoricalDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join("data", "listings.db")


def export_json(db_path: str, output_path: str, site: str = None):
    """Export listings to JSON file."""
    with HistoricalDB(db_path) as db:
        listings = db.get_listings(site=site)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)

    logger.info("Exported %d listings to %s", len(listings), output_path)


def export_csv(db_path: str, output_path: str, site: str = None):
    """Export listings to CSV file."""
    with HistoricalDB(db_path) as db:
        listings = db.get_listings(site=site)

    if not listings:
        logger.warning("No listings to export")
        return

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    keys = listings[0].keys()

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(listings)

    logger.info("Exported %d listings to %s", len(listings), output_path)


def export_excel(db_path: str, output_path: str, site: str = None):
    """Export listings to Excel file."""
    with HistoricalDB(db_path) as db:
        listings = db.get_listings(site=site)

    if not listings:
        logger.warning("No listings to export")
        return

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df = pd.DataFrame(listings)
    df.to_excel(output_path, index=False)

    logger.info("Exported %d listings to %s", len(listings), output_path)


def analyze_price_changes(db_path: str, site: str = None):
    """Analyze price changes from history."""
    with HistoricalDB(db_path) as db:
        listings = db.get_listings(site=site)

    changes = []
    for listing in listings:
        if not listing.get("url"):
            continue
        history = db.get_price_history(listing["url"], limit=2)
        if len(history) >= 2:
            old_price = history[1]["price"]
            new_price = history[0]["price"]
            if old_price and new_price and old_price != new_price:
                change_pct = ((new_price - old_price) / old_price) * 100
                changes.append(
                    {
                        "url": listing["url"],
                        "title": listing.get("title", "N/A"),
                        "old_price": old_price,
                        "new_price": new_price,
                        "change_percent": round(change_pct, 2),
                    }
                )

    if changes:
        print(f"\n{'='*80}")
        print(f"Price Changes Found: {len(changes)}")
        print(f"{'='*80}")
        for change in sorted(changes, key=lambda x: abs(x["change_percent"]), reverse=True)[:10]:
            print(f"Title: {change['title'][:50]}")
            print(f"Price: {change['old_price']} -> {change['new_price']} ({change['change_percent']:+.2f}%)")
            print(f"URL: {change['url'][:70]}")
            print()
    else:
        print("No price changes found.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Analyze and export scraped data")
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--site",
        choices=["fora", "novus"],
        help="Filter by site",
    )
    parser.add_argument(
        "--export-json",
        help="Export to JSON file",
    )
    parser.add_argument(
        "--export-csv",
        help="Export to CSV file",
    )
    parser.add_argument(
        "--export-excel",
        help="Export to Excel file",
    )
    parser.add_argument(
        "--analyze-prices",
        action="store_true",
        help="Analyze price changes",
    )

    args = parser.parse_args()

    if args.export_json:
        export_json(args.db, args.export_json, args.site)

    if args.export_csv:
        export_csv(args.db, args.export_csv, args.site)

    if args.export_excel:
        export_excel(args.db, args.export_excel, args.site)

    if args.analyze_prices:
        analyze_price_changes(args.db, args.site)

    if not any([args.export_json, args.export_csv, args.export_excel, args.analyze_prices]):
        parser.print_help()


if __name__ == "__main__":
    main()

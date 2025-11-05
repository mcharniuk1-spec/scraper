#!/usr/bin/env python3
"""
Historical Database Module

Manages SQLite database for storing scraped listings with historical tracking.
Supports versioning and price change tracking.
"""
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HistoricalDB:
    """Manages historical database for scraped listings."""

    def __init__(self, db_path: str):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_data_dir()
        self.conn = self._init_db()

    def _ensure_data_dir(self) -> None:
        """Ensure data directory exists."""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

    def _init_db(self) -> sqlite3.Connection:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Main listings table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                snippet TEXT,
                image_url TEXT,
                price REAL,
                currency TEXT,
                date_posted TEXT,
                scraped_at TEXT,
                site TEXT,
                category TEXT
            )
        """
        )

        # Price history table for tracking changes
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER,
                url TEXT NOT NULL,
                price REAL,
                currency TEXT,
                recorded_at TEXT,
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            )
        """
        )

        # Create indexes
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_listings_url ON listings(url)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_listings_site ON listings(site)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_price_history_url ON price_history(url)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_price_history_recorded ON price_history(recorded_at)"
        )

        conn.commit()
        return conn

    def upsert_listing(
        self,
        item: Dict,
        site: str,
        category: Optional[str] = None
    ) -> Tuple[bool, Optional[int]]:
        """
        Insert or update a listing, tracking price changes.

        Args:
            item: Dictionary with listing data
            site: Site identifier (e.g., 'fora', 'novus')
            category: Category identifier (optional)

        Returns:
            Tuple of (is_new, listing_id)
        """
        cur = self.conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        # Check if listing exists and get current price
        cur.execute("SELECT id, price FROM listings WHERE url = ?", (item.get("url"),))
        existing = cur.fetchone()
        is_new = existing is None
        old_price = existing[1] if existing else None

        try:
            if is_new:
                # Insert new listing
                cur.execute(
                    """
                    INSERT INTO listings 
                    (url, title, snippet, image_url, price, currency, date_posted, scraped_at, site, category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.get("url"),
                        item.get("title"),
                        item.get("snippet"),
                        item.get("image_url"),
                        item.get("price"),
                        item.get("currency"),
                        item.get("date_posted"),
                        now,
                        site,
                        category,
                    ),
                )
                listing_id = cur.lastrowid
            else:
                # Update existing listing
                listing_id = existing[0]
                cur.execute(
                    """
                    UPDATE listings SET
                        title = ?,
                        snippet = ?,
                        image_url = ?,
                        price = ?,
                        currency = ?,
                        date_posted = ?,
                        scraped_at = ?,
                        site = ?,
                        category = ?
                    WHERE url = ?
                    """,
                    (
                        item.get("title"),
                        item.get("snippet"),
                        item.get("image_url"),
                        item.get("price"),
                        item.get("currency"),
                        item.get("date_posted"),
                        now,
                        site,
                        category,
                        item.get("url"),
                    ),
                )

                # Track price changes
                new_price = item.get("price")
                if new_price is not None and old_price != new_price:
                    cur.execute(
                        """
                        INSERT INTO price_history (listing_id, url, price, currency, recorded_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (listing_id, item.get("url"), new_price, item.get("currency"), now),
                    )
                    logger.info(
                        "Price change detected for %s: %s -> %s %s",
                        item.get("url"),
                        old_price,
                        new_price,
                        item.get("currency"),
                    )

            self.conn.commit()
            return is_new, listing_id

        except sqlite3.Error as e:
            logger.exception("DB operation failed for %s: %s", item.get("url"), e)
            self.conn.rollback()
            return False, None

    def get_listings(
        self,
        site: Optional[str] = None,
        category: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Query listings from database.

        Args:
            site: Filter by site (optional)
            category: Filter by category (optional)
            limit: Limit number of results (optional)

        Returns:
            List of listing dictionaries
        """
        cur = self.conn.cursor()
        query = "SELECT * FROM listings WHERE 1=1"
        params = []

        if site:
            query += " AND site = ?"
            params.append(site)

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY scraped_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_price_history(self, url: str, limit: int = 100) -> List[Dict]:
        """
        Get price history for a listing.

        Args:
            url: Listing URL
            limit: Maximum number of history entries

        Returns:
            List of price history entries
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM price_history
            WHERE url = ?
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (url, limit),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_stats(self, site: Optional[str] = None) -> Dict:
        """
        Get statistics about stored listings.

        Args:
            site: Filter by site (optional)

        Returns:
            Dictionary with statistics
        """
        cur = self.conn.cursor()

        if site:
            cur.execute("SELECT COUNT(*) FROM listings WHERE site = ?", (site,))
            total = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(DISTINCT url) FROM listings WHERE site = ?", (site,)
            )
            unique = cur.fetchone()[0]

            cur.execute(
                "SELECT AVG(price) FROM listings WHERE site = ? AND price IS NOT NULL",
                (site,),
            )
            avg_price = cur.fetchone()[0] or 0
        else:
            cur.execute("SELECT COUNT(*) FROM listings")
            total = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT url) FROM listings")
            unique = cur.fetchone()[0]

            cur.execute(
                "SELECT AVG(price) FROM listings WHERE price IS NOT NULL"
            )
            avg_price = cur.fetchone()[0] or 0

        return {
            "total_listings": total,
            "unique_urls": unique,
            "average_price": round(avg_price, 2) if avg_price else None,
        }

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

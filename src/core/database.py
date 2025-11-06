import sqlite3, pandas as pd
from pathlib import Path

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site TEXT,
                title TEXT,
                price REAL,
                url TEXT,
                date_scraped TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()

    def save_records(self, site: str, records: list[dict]):
        with sqlite3.connect(self.db_path) as conn:
            for r in records:
                conn.execute("""
                    INSERT INTO listings (site, title, price, url)
                    VALUES (?, ?, ?, ?)
                """, (site, r["title"], r["price"], r["url"]))
            conn.commit()

    def export_to_excel(self, path: str):
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql("SELECT * FROM listings", conn)
        df.to_excel(path, index=False)

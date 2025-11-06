#!/usr/bin/env python3
import os
import glob
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_FORA = ROOT / 'data' / 'fora'
DATA_MON = ROOT / 'data' / 'monitoring'
DB_PATH = DATA_FORA / 'fora_products.db'
XLSX_PATH = DATA_FORA / 'fora_products.xlsx'

DATA_FORA.mkdir(parents=True, exist_ok=True)
DATA_MON.mkdir(parents=True, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS products_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_url TEXT NOT NULL,
        product_name TEXT,
        price REAL,
        currency TEXT,
        image_url TEXT,
        category TEXT,
        site_name TEXT,
        scraped_at TEXT,
        session_id TEXT NOT NULL,
        data_hash TEXT
    )
    """)

    # Вигляд поточного стану
    cur.execute("""
    CREATE VIEW IF NOT EXISTS products_current AS
    SELECT p1.product_url,
           p1.product_name,
           p1.price,
           p1.currency,
           p1.image_url,
           p1.category,
           p1.site_name,
           p1.scraped_at,
           p1.session_id,
           p1.data_hash
    FROM products_history p1
    WHERE p1.scraped_at = (
      SELECT MAX(p2.scraped_at)
      FROM products_history p2
      WHERE p2.product_url = p1.product_url
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS scrape_sessions (
        session_id TEXT PRIMARY KEY,
        site_name TEXT,
        start_time TEXT,
        end_time TEXT,
        pages_scraped INTEGER,
        products_found INTEGER,
        errors_count INTEGER,
        status TEXT
    )
    """)

    conn.commit()
    conn.close()

def md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def upsert_session(conn, session_id, site_name, pages, products, errors):
    cur = conn.cursor()

    # start_time = now if not exists
    now = datetime.utcnow().isoformat()
    cur.execute("SELECT session_id FROM scrape_sessions WHERE session_id = ?", (session_id,))
    exists = cur.fetchone()

    if not exists:
        cur.execute("""
          INSERT INTO scrape_sessions (session_id, site_name, start_time, status)
          VALUES (?, ?, ?, ?)
        """, (session_id, site_name, now, 'running'))

    # complete
    cur.execute("""
      UPDATE scrape_sessions
      SET end_time = ?, pages_scraped = ?, products_found = ?, errors_count = ?, status = 'completed'
      WHERE session_id = ?
    """, (now, pages, products, errors, session_id))

    conn.commit()

def ingest_json_files():
    json_files = sorted(glob.glob(str(DATA_FORA / "fora_products_*.json")))
    if not json_files:
        print("[Ingest] No Fora JSON found. Skip.")
        return None

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    total_inserted = 0
    last_summary = None

    for jf in json_files:
        with open(jf, 'r', encoding='utf-8') as f:
            payload = json.load(f)

        items = payload.get('items', [])
        site = payload.get('site', 'Fora.ua')
        session_id = payload.get('session_id')
        scraped_at = payload.get('scraped_at')
        max_pages = payload.get('max_pages', None)
        fails = payload.get('fails', [])

        new_rows = 0
        for it in items:
            product_url = it.get('url')
            if not product_url:
                continue

            # Хешуємо "основні" поля для версіонування
            key = json.dumps({
                'url': product_url,
                'name': it.get('product_name'),
                'price': it.get('price'),
            }, ensure_ascii=False, sort_keys=True)
            h = md5(key)

            # Чи вже існує така версія?
            cur.execute("""
              SELECT COUNT(*) FROM products_history
              WHERE product_url = ? AND data_hash = ?
            """, (product_url, h))
            (cnt,) = cur.fetchone()
            if cnt > 0:
                continue  # ця версія вже є

            cur.execute("""
            INSERT INTO products_history
              (product_url, product_name, price, currency, image_url, category,
               site_name, scraped_at, session_id, data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_url,
                it.get('product_name'),
                it.get('price'),
                it.get('currency', '₴'),
                it.get('image_url'),
                it.get('category', 'Молочні продукти та яйця'),
                it.get('site_name', site),
                it.get('scraped_at', scraped_at),
                it.get('session_id', session_id),
                h
            ))
            new_rows += 1

        # Сесія
        pages = max_pages or 0
        errors = len(fails)
        upsert_session(conn, session_id, site, pages, len(items), errors)

        total_inserted += new_rows
        last_summary = {
            'session_id': session_id,
            'site': site,
            'scraped_at': scraped_at,
            'products_in_json': len(items),
            'new_versions_inserted': new_rows,
            'pages_scraped_reported': pages,
            'errors_reported': errors
        }

        print(f"[Ingest] {os.path.basename(jf)} -> {new_rows} new rows")

    conn.close()
    return last_summary

def export_excel():
    conn = sqlite3.connect(DB_PATH)
    df_current = pd.read_sql_query("""
      SELECT product_name AS 'Назва',
             price AS 'Ціна',
             currency AS 'Валюта',
             category AS 'Категорія',
             site_name AS 'Сайт',
             product_url AS 'URL',
             scraped_at AS 'Оновлено'
      FROM products_current
      ORDER BY scraped_at DESC
    """, conn)

    df_sessions = pd.read_sql_query("""
      SELECT session_id AS 'Сесія',
             site_name AS 'Сайт',
             start_time AS 'Початок',
             end_time AS 'Кінець',
             pages_scraped AS 'Сторінок',
             products_found AS 'Знайдено',
             errors_count AS 'Помилок',
             status AS 'Статус'
      FROM scrape_sessions
      WHERE site_name='Fora.ua'
      ORDER BY start_time DESC
      LIMIT 50
    """, conn)

    with pd.ExcelWriter(XLSX_PATH, engine='openpyxl') as wr:
        df_current.to_excel(wr, sheet_name='Поточні Продукти', index=False)
        df_sessions.to_excel(wr, sheet_name='Сесії', index=False)

    conn.close()
    print(f"[Export] Excel saved: {XLSX_PATH}, rows={len(df_current)}")

def write_monitoring(summary):
    # агреговані показники
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT product_url) FROM products_current")
    (unique_now,) = cur.fetchone()

    cur.execute("SELECT COUNT(*) FROM products_history")
    (history_rows,) = cur.fetchone()

    conn.close()

    out = {
        'updated_at': datetime.utcnow().isoformat(),
        'last_session': summary,
        'current_unique_products': unique_now,
        'history_rows_total': history_rows
    }

    out_path = DATA_MON / 'fora_last_run.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[Monitoring] {out_path} written")

def main():
    init_db()
    summary = ingest_json_files()
    if summary:
        export_excel()
        write_monitoring(summary)
    else:
        print("[Ingest] Nothing to do.")

if __name__ == "__main__":
    main()

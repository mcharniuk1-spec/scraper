#!/usr/bin/env python3
import logging
import pandas as pd
import sqlite3
from typing import Dict
from src.core.database import HistoricalDatabase

logger = logging.getLogger(__name__)

class DataQualityAnalyzer:
    def __init__(self, db: HistoricalDatabase):
        self.db = db

    def analyze_session_quality(self, session_id: str) -> Dict[str, float]:
        conn = sqlite3.connect(self.db.db_path)
        df = pd.read_sql_query(
            "SELECT product_name, price, availability FROM products_history WHERE scrape_session_id = ?",
            conn,
            params=(session_id,)
        )
        conn.close()
        if df.empty:
            completeness = 0.0
            price_validity = 0.0
        else:
            completeness = ((df['product_name'].notnull().mean()) + (df['price'].notnull().mean())) / 2 * 100
            price_validity = df['price'].apply(lambda x: 1 if x and 1 <= x <= 10000 else 0).mean() * 100
        overall_score = round((completeness + price_validity) / 2, 2)
        self.db.record_quality_metric(session_id, 'completeness', completeness)
        self.db.record_quality_metric(session_id, 'price_validity', price_validity)
        self.db.record_quality_metric(session_id, 'overall_quality_score', overall_score)
        return {
            'completeness': completeness,
            'price_validity': price_validity,
            'overall_quality_score': overall_score
        }

    def generate_quality_report(self, session_id: str) -> str:
        metrics = self.analyze_session_quality(session_id)
        lines = [
            f"Сесія: {session_id}",
            f"Повнота даних: {metrics['completeness']:.2f}%",
            f"Правильність цін: {metrics['price_validity']:.2f}%",
            f"Загальна оцінка якості: {metrics['overall_quality_score']:.2f}/100"
        ]
        return '\n'.join(lines)

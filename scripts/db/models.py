"""
SQLite schema for shopping-browser price tracking.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "prices.db"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    product_id TEXT NOT NULL,
    title TEXT,
    url TEXT,
    tracked_since TEXT DEFAULT (datetime('now')),
    active INTEGER DEFAULT 1,
    alert_threshold REAL DEFAULT 5.0,
    UNIQUE(site, product_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    price REAL,
    list_price REAL,
    discount_pct TEXT,
    in_stock INTEGER,
    seller TEXT,
    shipping TEXT,
    deal_badge TEXT,
    coupon TEXT,
    recorded_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_price_history_product_time
    ON price_history(product_id, recorded_at);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    alert_type TEXT NOT NULL,
    message TEXT,
    old_value TEXT,
    new_value TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    acknowledged INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_alerts_unack
    ON alerts(acknowledged, created_at);
"""


def get_connection() -> sqlite3.Connection:
    """Get a database connection, creating schema if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Check if tables exist
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {row["name"] for row in tables}
    if "products" not in table_names:
        conn.executescript(SCHEMA)
    return conn

"""Load the cleaned Superstore CSV into a SQLite database.

Creates retail_sales.db with an `orders` table (one row per order line item,
matching the grain of the cleaned CSV), adds indexes on the columns used for
filtering/joining in analysis, and verifies that the database row count
matches the source CSV.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANED_CSV_PATH = PROJECT_ROOT / "data" / "cleaned_superstore.csv"
DB_PATH = PROJECT_ROOT / "retail_sales.db"
TABLE_NAME = "orders"

CREATE_TABLE_SQL = f"""
CREATE TABLE {TABLE_NAME} (
    row_id              INTEGER PRIMARY KEY,
    order_id            TEXT NOT NULL,
    order_date          TEXT NOT NULL,
    ship_date           TEXT,
    ship_mode           TEXT,
    customer_id         TEXT NOT NULL,
    customer_name       TEXT,
    segment             TEXT,
    country             TEXT,
    city                TEXT,
    state               TEXT,
    postal_code         INTEGER,
    region              TEXT,
    product_id          TEXT NOT NULL,
    category             TEXT,
    sub_category        TEXT,
    product_name        TEXT,
    sales               REAL,
    quantity            INTEGER,
    discount            REAL,
    profit              REAL,
    order_year          INTEGER,
    order_month         INTEGER,
    order_quarter       INTEGER,
    shipping_days       INTEGER,
    profit_margin_pct   REAL,
    is_profitable       INTEGER,
    discount_band       TEXT
);
"""

INDEX_STATEMENTS = [
    f"CREATE INDEX idx_{TABLE_NAME}_order_id ON {TABLE_NAME}(order_id);",
    f"CREATE INDEX idx_{TABLE_NAME}_customer_id ON {TABLE_NAME}(customer_id);",
    f"CREATE INDEX idx_{TABLE_NAME}_product_id ON {TABLE_NAME}(product_id);",
    f"CREATE INDEX idx_{TABLE_NAME}_order_date ON {TABLE_NAME}(order_date);",
    f"CREATE INDEX idx_{TABLE_NAME}_region ON {TABLE_NAME}(region);",
    f"CREATE INDEX idx_{TABLE_NAME}_category ON {TABLE_NAME}(category);",
]


def load_cleaned_data(csv_path: Path) -> pd.DataFrame:
    """Load the cleaned CSV, ready for insertion into SQLite."""
    logger.info("Loading cleaned data from %s", csv_path)
    df = pd.read_csv(csv_path, parse_dates=["order_date", "ship_date"])
    df["order_date"] = df["order_date"].dt.strftime("%Y-%m-%d")
    df["ship_date"] = df["ship_date"].dt.strftime("%Y-%m-%d")
    df["is_profitable"] = df["is_profitable"].astype(int)
    logger.info("Loaded %d rows for insertion", len(df))
    return df


def create_database(df: pd.DataFrame, db_path: Path) -> None:
    """(Re)create the SQLite database, table, and indexes, then load rows."""
    if db_path.exists():
        logger.info("Removing existing database at %s", db_path)
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(CREATE_TABLE_SQL)
        for stmt in INDEX_STATEMENTS:
            cursor.execute(stmt)
        conn.commit()

        df.to_sql(TABLE_NAME, conn, if_exists="append", index=False)
        conn.commit()
        logger.info("Inserted %d rows into '%s' table", len(df), TABLE_NAME)
    finally:
        conn.close()


def verify_row_counts(db_path: Path, csv_row_count: int) -> int:
    """Verify the database row count matches the CSV row count. Returns DB count."""
    conn = sqlite3.connect(db_path)
    try:
        db_count = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    finally:
        conn.close()

    if db_count != csv_row_count:
        raise ValueError(
            f"Row count mismatch: CSV has {csv_row_count} rows, "
            f"database has {db_count} rows"
        )
    logger.info("Row count verified: CSV=%d, database=%d (match)", csv_row_count, db_count)
    return db_count


def main() -> None:
    """Build retail_sales.db from the cleaned CSV and verify the load."""
    if not CLEANED_CSV_PATH.exists():
        raise FileNotFoundError(
            f"Cleaned data file not found: {CLEANED_CSV_PATH}. Run clean_data.py first."
        )

    df = load_cleaned_data(CLEANED_CSV_PATH)
    csv_row_count = len(df)

    create_database(df, DB_PATH)
    db_count = verify_row_counts(DB_PATH, csv_row_count)

    print("=" * 60)
    print("DATABASE CREATION SUMMARY")
    print("=" * 60)
    print(f"  Database path: {DB_PATH}")
    print(f"  Table:         {TABLE_NAME}")
    print(f"  Indexes:       {len(INDEX_STATEMENTS)}")
    print(f"  CSV rows:      {csv_row_count}")
    print(f"  DB rows:       {db_count}")
    print(f"  Match:         {csv_row_count == db_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()

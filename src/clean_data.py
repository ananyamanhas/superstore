"""Clean the raw Superstore dataset and engineer analysis-ready columns.

Reads data/superstore.csv, standardizes and validates it, engineers a small
set of derived columns used throughout the analysis, and writes
data/cleaned_superstore.csv. Prints a before/after data-quality summary.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_CSV_PATH = PROJECT_ROOT / "data" / "superstore.csv"
CLEANED_CSV_PATH = PROJECT_ROOT / "data" / "cleaned_superstore.csv"

# Superstore dates are stored as M/D/YYYY (verified during dataset inspection).
DATE_FORMAT = "%m/%d/%Y"

# Columns whose presence identifies a row as a usable business record.
CRITICAL_ID_COLUMNS = ["order_id", "customer_id", "product_id"]

DISCOUNT_BAND_LABELS = ["No Discount", "Low (0-20%)", "Medium (20-40%)", "High (40%+)"]
DISCOUNT_BAND_BINS = [-0.001, 0.0, 0.20, 0.40, 1.0]


def to_snake_case(column_name: str) -> str:
    """Convert a raw column header (e.g. 'Order ID') to snake_case ('order_id')."""
    name = column_name.strip()
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return name.strip("_").lower()


def load_raw_data(csv_path: Path) -> pd.DataFrame:
    """Load the raw CSV, tolerating the file's cp1252 encoding."""
    logger.info("Loading raw data from %s", csv_path)
    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
    except UnicodeDecodeError:
        logger.info("UTF-8 decode failed, retrying with cp1252 encoding")
        df = pd.read_csv(csv_path, encoding="cp1252")
    logger.info("Loaded %d rows, %d columns", *df.shape)
    return df


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename all columns to snake_case."""
    df = df.copy()
    df.columns = [to_snake_case(c) for c in df.columns]
    return df


def remove_exact_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop fully duplicate rows. Returns the deduplicated frame and count removed."""
    before = len(df)
    df = df.drop_duplicates()
    removed = before - len(df)
    if removed:
        logger.warning("Removed %d exact duplicate rows", removed)
    else:
        logger.info("No exact duplicate rows found")
    return df, removed


def parse_dates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Parse order_date/ship_date columns; report rows with invalid dates."""
    df = df.copy()
    invalid_count = 0
    for col in ("order_date", "ship_date"):
        if col not in df.columns:
            continue
        parsed = pd.to_datetime(df[col], format=DATE_FORMAT, errors="coerce")
        invalid = parsed.isna() & df[col].notna()
        invalid_count += int(invalid.sum())
        if invalid.any():
            logger.warning("%d invalid values found in %s", int(invalid.sum()), col)
        df[col] = parsed
    return df, invalid_count


def parse_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce known numeric columns to numeric dtypes."""
    df = df.copy()
    for col in ("sales", "quantity", "discount", "profit", "postal_code"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def handle_missing_values(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Conservatively handle missing values: drop rows missing critical IDs or
    core numeric fields; leave descriptive text fields untouched.

    Returns the cleaned frame and a dict of {column: rows_dropped_for_column}.
    """
    df = df.copy()
    dropped: dict[str, int] = {}

    id_cols_present = [c for c in CRITICAL_ID_COLUMNS if c in df.columns]
    for col in id_cols_present:
        missing_mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
        n = int(missing_mask.sum())
        if n:
            dropped[col] = n
            df = df[~missing_mask]

    for col in ("order_date", "sales"):
        if col in df.columns:
            missing_mask = df[col].isna()
            n = int(missing_mask.sum())
            if n:
                dropped[col] = dropped.get(col, 0) + n
                df = df[~missing_mask]

    # postal_code is descriptive/location metadata, not a critical key -
    # keep the row but leave any missing value as-is (no assumed default).
    return df, dropped


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add order_year, order_month, order_quarter, shipping_days,
    profit_margin_pct, is_profitable, and discount_band columns."""
    df = df.copy()

    df["order_year"] = df["order_date"].dt.year
    df["order_month"] = df["order_date"].dt.month
    df["order_quarter"] = df["order_date"].dt.quarter

    if "ship_date" in df.columns:
        df["shipping_days"] = (df["ship_date"] - df["order_date"]).dt.days

    if "profit" in df.columns and "sales" in df.columns:
        df["profit_margin_pct"] = (df["profit"] / df["sales"]).replace(
            [float("inf"), float("-inf")], pd.NA
        ) * 100
        df["is_profitable"] = df["profit"] > 0

    if "discount" in df.columns:
        df["discount_band"] = pd.cut(
            df["discount"],
            bins=DISCOUNT_BAND_BINS,
            labels=DISCOUNT_BAND_LABELS,
        )

    return df


def detect_quality_issues(df: pd.DataFrame) -> dict[str, int]:
    """Detect (without removing) invalid dates, negative shipping days, and
    missing critical IDs remaining after cleaning. Returns issue counts."""
    issues: dict[str, int] = {}

    if "order_date" in df.columns:
        issues["invalid_order_dates"] = int(df["order_date"].isna().sum())
    if "ship_date" in df.columns:
        issues["invalid_ship_dates"] = int(df["ship_date"].isna().sum())
    if "shipping_days" in df.columns:
        issues["negative_shipping_days"] = int((df["shipping_days"] < 0).sum())
    for col in CRITICAL_ID_COLUMNS:
        if col in df.columns:
            issues[f"missing_{col}"] = int(
                df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum()
            )
    return issues


def print_quality_summary(
    before_rows: int,
    before_cols: int,
    after_df: pd.DataFrame,
    duplicates_removed: int,
    missing_dropped: dict[str, int],
    invalid_dates: int,
    remaining_issues: dict[str, int],
) -> None:
    """Print a before/after data-quality summary to stdout."""
    print("=" * 60)
    print("DATA QUALITY SUMMARY")
    print("=" * 60)
    print("BEFORE CLEANING")
    print(f"  Rows:    {before_rows}")
    print(f"  Columns: {before_cols}")
    print()
    print("CLEANING ACTIONS")
    print(f"  Exact duplicate rows removed: {duplicates_removed}")
    print(f"  Invalid date values found:    {invalid_dates}")
    if missing_dropped:
        for col, n in missing_dropped.items():
            print(f"  Rows dropped (missing/invalid {col}): {n}")
    else:
        print("  Rows dropped for missing critical fields: 0")
    print()
    print("AFTER CLEANING")
    print(f"  Rows:    {len(after_df)}")
    print(f"  Columns: {after_df.shape[1]}")
    print()
    print("REMAINING DATA-QUALITY ISSUES (flagged, not removed)")
    for k, v in remaining_issues.items():
        print(f"  {k}: {v}")
    print("=" * 60)


def main() -> None:
    """Run the full cleaning pipeline and write the cleaned CSV."""
    if not RAW_CSV_PATH.exists():
        raise FileNotFoundError(f"Raw data file not found: {RAW_CSV_PATH}")

    raw_df = load_raw_data(RAW_CSV_PATH)
    before_rows, before_cols = raw_df.shape

    df = standardize_columns(raw_df)
    df, duplicates_removed = remove_exact_duplicates(df)
    df, invalid_dates = parse_dates(df)
    df = parse_numeric_columns(df)
    df, missing_dropped = handle_missing_values(df)
    df = add_derived_columns(df)
    remaining_issues = detect_quality_issues(df)

    CLEANED_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEANED_CSV_PATH, index=False)
    logger.info("Wrote cleaned data to %s (%d rows)", CLEANED_CSV_PATH, len(df))

    print_quality_summary(
        before_rows,
        before_cols,
        df,
        duplicates_removed,
        missing_dropped,
        invalid_dates,
        remaining_issues,
    )


if __name__ == "__main__":
    main()

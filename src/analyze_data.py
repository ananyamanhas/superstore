"""Run SQL-based analysis over retail_sales.db and export results.

Computes KPIs, time trends, dimensional performance breakdowns, top
products/customers, loss-making products, discount/shipping analysis, and a
Pareto (80/20) product analysis. Every table is exported as a CSV under
outputs/summaries/, and every claim written to outputs/insights.txt is
derived directly from a query result computed in this script (no hardcoded
numbers).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "retail_sales.db"
CLEANED_CSV_PATH = PROJECT_ROOT / "data" / "cleaned_superstore.csv"
SUMMARIES_DIR = PROJECT_ROOT / "outputs" / "summaries"
INSIGHTS_PATH = PROJECT_ROOT / "outputs" / "insights.txt"

TABLE = "orders"


def run_query(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    """Execute a SQL query and return the result as a DataFrame."""
    return pd.read_sql_query(sql, conn)


def export_table(df: pd.DataFrame, name: str) -> Path:
    """Write a result DataFrame to outputs/summaries/<name>.csv."""
    path = SUMMARIES_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    logger.info("Exported %s (%d rows) -> %s", name, len(df), path)
    return path


# --------------------------------------------------------------------------
# Validation against the cleaned CSV (sanity check that SQL totals match)
# --------------------------------------------------------------------------


def validate_against_csv(conn: sqlite3.Connection) -> None:
    """Cross-check SQL aggregate totals against the cleaned CSV directly."""
    csv_df = pd.read_csv(CLEANED_CSV_PATH)
    csv_sales = round(csv_df["sales"].sum(), 2)
    csv_profit = round(csv_df["profit"].sum(), 2)
    csv_rows = len(csv_df)

    sql_row = run_query(
        conn, f"SELECT ROUND(SUM(sales),2) AS sales, ROUND(SUM(profit),2) AS profit, COUNT(*) AS rows FROM {TABLE}"
    ).iloc[0]

    assert sql_row["rows"] == csv_rows, f"Row count mismatch: SQL={sql_row['rows']} CSV={csv_rows}"
    assert abs(sql_row["sales"] - csv_sales) < 0.01, f"Sales mismatch: SQL={sql_row['sales']} CSV={csv_sales}"
    assert abs(sql_row["profit"] - csv_profit) < 0.01, f"Profit mismatch: SQL={sql_row['profit']} CSV={csv_profit}"
    logger.info(
        "Validation OK: rows=%d, sales SQL=%.2f/CSV=%.2f, profit SQL=%.2f/CSV=%.2f",
        sql_row["rows"], sql_row["sales"], csv_sales, sql_row["profit"], csv_profit,
    )


# --------------------------------------------------------------------------
# Core KPIs
# --------------------------------------------------------------------------


def compute_kpis(conn: sqlite3.Connection) -> pd.DataFrame:
    """Overall KPIs: total sales/profit/orders, AOV (distinct orders), margin."""
    sql = f"""
    SELECT
        ROUND(SUM(sales), 2)                                   AS total_sales,
        ROUND(SUM(profit), 2)                                  AS total_profit,
        COUNT(DISTINCT order_id)                                AS total_orders,
        COUNT(*)                                                AS total_line_items,
        ROUND(SUM(sales) * 1.0 / COUNT(DISTINCT order_id), 2)   AS avg_order_value,
        ROUND(SUM(profit) * 100.0 / SUM(sales), 2)              AS profit_margin_pct,
        ROUND(AVG(discount) * 100, 2)                           AS avg_discount_pct,
        ROUND(AVG(shipping_days), 2)                            AS avg_shipping_days,
        ROUND(SUM(is_profitable) * 100.0 / COUNT(*), 2)         AS profitable_line_items_pct
    FROM {TABLE};
    """
    return run_query(conn, sql)


def yearly_trends(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = f"""
    SELECT
        order_year,
        ROUND(SUM(sales), 2)  AS total_sales,
        ROUND(SUM(profit), 2) AS total_profit,
        COUNT(DISTINCT order_id) AS total_orders,
        ROUND(SUM(profit) * 100.0 / SUM(sales), 2) AS profit_margin_pct
    FROM {TABLE}
    GROUP BY order_year
    ORDER BY order_year ASC;
    """
    return run_query(conn, sql)


def monthly_trends(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = f"""
    SELECT
        order_year,
        order_month,
        ROUND(SUM(sales), 2)  AS total_sales,
        ROUND(SUM(profit), 2) AS total_profit,
        COUNT(DISTINCT order_id) AS total_orders
    FROM {TABLE}
    GROUP BY order_year, order_month
    ORDER BY order_year ASC, order_month ASC;
    """
    return run_query(conn, sql)


# --------------------------------------------------------------------------
# Dimensional performance
# --------------------------------------------------------------------------


def performance_by(conn: sqlite3.Connection, column: str) -> pd.DataFrame:
    sql = f"""
    SELECT
        {column},
        ROUND(SUM(sales), 2)  AS total_sales,
        ROUND(SUM(profit), 2) AS total_profit,
        COUNT(DISTINCT order_id) AS total_orders,
        ROUND(SUM(profit) * 100.0 / SUM(sales), 2) AS profit_margin_pct
    FROM {TABLE}
    GROUP BY {column}
    ORDER BY total_sales DESC;
    """
    return run_query(conn, sql)


# --------------------------------------------------------------------------
# Top products / customers / loss-makers
# --------------------------------------------------------------------------


def top_products_by_sales(conn: sqlite3.Connection, limit: int = 10) -> pd.DataFrame:
    # Grouped by product_id alone: 32 product_ids in this dataset have more
    # than one product_name spelling, so MIN() picks one consistent label.
    sql = f"""
    SELECT
        product_id,
        MIN(product_name) AS product_name,
        MIN(category)     AS category,
        MIN(sub_category) AS sub_category,
        ROUND(SUM(sales), 2)  AS total_sales,
        ROUND(SUM(profit), 2) AS total_profit,
        SUM(quantity)          AS total_quantity
    FROM {TABLE}
    GROUP BY product_id
    ORDER BY total_sales DESC
    LIMIT {limit};
    """
    return run_query(conn, sql)


def top_customers_by_sales(conn: sqlite3.Connection, limit: int = 10) -> pd.DataFrame:
    sql = f"""
    SELECT
        customer_id,
        customer_name,
        segment,
        ROUND(SUM(sales), 2)  AS total_sales,
        ROUND(SUM(profit), 2) AS total_profit,
        COUNT(DISTINCT order_id) AS total_orders
    FROM {TABLE}
    GROUP BY customer_id, customer_name, segment
    ORDER BY total_sales DESC
    LIMIT {limit};
    """
    return run_query(conn, sql)


def loss_making_products(conn: sqlite3.Connection) -> pd.DataFrame:
    """Products with negative total profit across all their line items."""
    sql = f"""
    SELECT
        product_id,
        MIN(product_name) AS product_name,
        MIN(category)     AS category,
        MIN(sub_category) AS sub_category,
        ROUND(SUM(sales), 2)  AS total_sales,
        ROUND(SUM(profit), 2) AS total_profit,
        ROUND(AVG(discount) * 100, 2) AS avg_discount_pct,
        COUNT(*) AS line_items
    FROM {TABLE}
    GROUP BY product_id
    HAVING ROUND(SUM(profit), 2) < 0
    ORDER BY total_profit ASC;
    """
    return run_query(conn, sql)


# --------------------------------------------------------------------------
# Discount and shipping analysis
# --------------------------------------------------------------------------


def discount_analysis(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = f"""
    SELECT
        discount_band,
        COUNT(*) AS line_items,
        ROUND(AVG(discount) * 100, 2) AS avg_discount_pct,
        ROUND(SUM(sales), 2)  AS total_sales,
        ROUND(SUM(profit), 2) AS total_profit,
        ROUND(SUM(profit) * 100.0 / SUM(sales), 2) AS profit_margin_pct
    FROM {TABLE}
    GROUP BY discount_band
    ORDER BY avg_discount_pct ASC;
    """
    return run_query(conn, sql)


def shipping_analysis(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = f"""
    SELECT
        ship_mode,
        COUNT(*) AS line_items,
        ROUND(AVG(shipping_days), 2) AS avg_shipping_days,
        MIN(shipping_days) AS min_shipping_days,
        MAX(shipping_days) AS max_shipping_days
    FROM {TABLE}
    GROUP BY ship_mode
    ORDER BY avg_shipping_days ASC;
    """
    return run_query(conn, sql)


# --------------------------------------------------------------------------
# Pareto (80/20) product analysis
# --------------------------------------------------------------------------


def pareto_analysis(conn: sqlite3.Connection) -> pd.DataFrame:
    """Rank products by sales and compute cumulative share of total sales."""
    sql = f"""
    SELECT
        product_id,
        MIN(product_name) AS product_name,
        ROUND(SUM(sales), 2) AS total_sales
    FROM {TABLE}
    GROUP BY product_id
    ORDER BY total_sales DESC;
    """
    df = run_query(conn, sql)
    total_sales = df["total_sales"].sum()
    df["cumulative_sales"] = df["total_sales"].cumsum()
    df["cumulative_sales_pct"] = round(df["cumulative_sales"] * 100 / total_sales, 2)
    df["product_rank"] = range(1, len(df) + 1)
    df["cumulative_product_pct"] = round(df["product_rank"] * 100 / len(df), 2)
    return df


def summarize_pareto(pareto_df: pd.DataFrame) -> dict[str, float]:
    """Find how many products/what share of the catalog drive 80% of sales."""
    at_80 = pareto_df[pareto_df["cumulative_sales_pct"] >= 80].iloc[0]
    return {
        "products_for_80pct_sales": int(at_80["product_rank"]),
        "pct_of_catalog_for_80pct_sales": round(at_80["cumulative_product_pct"], 2),
        "total_products": len(pareto_df),
    }


# --------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------


def build_insights(results: dict[str, pd.DataFrame], pareto_summary: dict[str, float]) -> list[str]:
    """Build a list of plain-language findings, each backed by a computed value."""
    kpi = results["kpi_summary"].iloc[0]
    yearly = results["yearly_trends"]
    region = results["region_performance"]
    category = results["category_performance"]
    subcat = results["subcategory_performance"]
    segment = results["segment_performance"]
    top_products = results["top_products_by_sales"]
    top_customers = results["top_customers_by_sales"]
    loss_products = results["loss_making_products"]
    discount = results["discount_analysis"]
    shipping = results["shipping_analysis"]

    best_year = yearly.loc[yearly["total_sales"].idxmax()]
    best_region = region.iloc[0]
    worst_region_margin = region.loc[region["profit_margin_pct"].idxmin()]
    best_category = category.iloc[0]
    worst_subcat_margin = subcat.loc[subcat["profit_margin_pct"].idxmin()]
    best_segment = segment.iloc[0]
    top_product = top_products.iloc[0]
    top_customer = top_customers.iloc[0]
    fastest_ship = shipping.iloc[0]
    slowest_ship = shipping.loc[shipping["avg_shipping_days"].idxmax()]
    high_discount_row = discount.loc[discount["avg_discount_pct"].idxmax()]

    lines = [
        f"1. The dataset covers {int(kpi['total_orders'])} distinct orders ({int(kpi['total_line_items'])} line items) "
        f"totaling ${kpi['total_sales']:,.2f} in sales and ${kpi['total_profit']:,.2f} in profit "
        f"({kpi['profit_margin_pct']:.2f}% overall profit margin).",

        f"2. Average order value (total sales / distinct orders) is ${kpi['avg_order_value']:,.2f}. "
        f"Average discount is {kpi['avg_discount_pct']:.2f}%, average shipping time is "
        f"{kpi['avg_shipping_days']:.2f} days, and {kpi['profitable_line_items_pct']:.2f}% of line items are profitable.",

        f"3. {int(best_year['order_year'])} was the highest-sales year at ${best_year['total_sales']:,.2f} "
        f"({best_year['profit_margin_pct']:.2f}% margin).",

        f"4. The {best_region['region']} region leads in sales (${best_region['total_sales']:,.2f}), while the "
        f"{worst_region_margin['region']} region has the lowest profit margin at {worst_region_margin['profit_margin_pct']:.2f}%.",

        f"5. {best_category['category']} is the top-selling category (${best_category['total_sales']:,.2f} sales, "
        f"{best_category['profit_margin_pct']:.2f}% margin). The {worst_subcat_margin['sub_category']} sub-category has the "
        f"weakest margin among sub-categories at {worst_subcat_margin['profit_margin_pct']:.2f}%.",

        f"6. The {best_segment['segment']} segment generates the most sales (${best_segment['total_sales']:,.2f}, "
        f"{best_segment['profit_margin_pct']:.2f}% margin).",

        f"7. The top-selling product is \"{top_product['product_name']}\" (${top_product['total_sales']:,.2f} in sales). "
        f"The top customer by sales is {top_customer['customer_name']} (${top_customer['total_sales']:,.2f} across "
        f"{int(top_customer['total_orders'])} orders).",

        f"8. {len(loss_products)} products are loss-making overall (negative total profit summed across all their line "
        f"items), with combined losses of -${abs(loss_products['total_profit'].sum()):,.2f}.",

        f"9. The '{high_discount_row['discount_band']}' discount band has the highest average discount "
        f"({high_discount_row['avg_discount_pct']:.2f}%) and a profit margin of {high_discount_row['profit_margin_pct']:.2f}%, "
        f"illustrating how heavier discounting compresses margin.",

        f"10. {fastest_ship['ship_mode']} is the fastest shipping method ({fastest_ship['avg_shipping_days']:.2f} avg days) "
        f"and {slowest_ship['ship_mode']} is the slowest ({slowest_ship['avg_shipping_days']:.2f} avg days).",

        f"11. Pareto analysis: {pareto_summary['products_for_80pct_sales']} of {pareto_summary['total_products']} products "
        f"({pareto_summary['pct_of_catalog_for_80pct_sales']:.2f}% of the catalog) generate 80% of total sales.",
    ]
    return lines


def main() -> None:
    """Run all analyses, export summary tables, and write verified insights."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}. Run create_database.py first.")

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        validate_against_csv(conn)

        results: dict[str, pd.DataFrame] = {}
        results["kpi_summary"] = compute_kpis(conn)
        results["yearly_trends"] = yearly_trends(conn)
        results["monthly_trends"] = monthly_trends(conn)
        results["region_performance"] = performance_by(conn, "region")
        results["category_performance"] = performance_by(conn, "category")
        results["subcategory_performance"] = performance_by(conn, "sub_category")
        results["segment_performance"] = performance_by(conn, "segment")
        results["top_products_by_sales"] = top_products_by_sales(conn)
        results["top_products_by_profit"] = run_query(
            conn,
            f"""
            SELECT product_id, MIN(product_name) AS product_name,
                   MIN(category) AS category, MIN(sub_category) AS sub_category,
                   ROUND(SUM(sales),2) AS total_sales, ROUND(SUM(profit),2) AS total_profit
            FROM {TABLE}
            GROUP BY product_id
            ORDER BY total_profit DESC
            LIMIT 10;
            """,
        )
        results["top_customers_by_sales"] = top_customers_by_sales(conn)
        results["loss_making_products"] = loss_making_products(conn)
        results["discount_analysis"] = discount_analysis(conn)
        results["shipping_analysis"] = shipping_analysis(conn)
        results["pareto_analysis"] = pareto_analysis(conn)

        # Sanity check: monthly trends must sort strictly ascending by (year, month)
        mt = results["monthly_trends"]
        sort_key = list(zip(mt["order_year"], mt["order_month"]))
        assert sort_key == sorted(sort_key), "Monthly trends are not sorted ascending by date"

        pareto_summary = summarize_pareto(results["pareto_analysis"])

        for name, df in results.items():
            export_table(df, name)

        insights = build_insights(results, pareto_summary)
        INSIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(INSIGHTS_PATH, "w", encoding="utf-8") as f:
            f.write("RETAIL SALES ANALYTICS - VERIFIED INSIGHTS\n")
            f.write("=" * 60 + "\n")
            f.write("Every figure below is computed directly from retail_sales.db.\n\n")
            for line in insights:
                f.write(line + "\n\n")
        logger.info("Wrote %d insights to %s", len(insights), INSIGHTS_PATH)

        print("=" * 60)
        print("ANALYSIS COMPLETE")
        print("=" * 60)
        for line in insights:
            print(line)
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()

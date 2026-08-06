# Retail Sales Analytics — Superstore

A complete, end-to-end analytics project on the classic "Superstore" retail
dataset: Python for cleaning, SQLite/SQL for aggregation, and Power BI for
visualization. Every number in this README, in `outputs/insights.txt`, and
in the Power BI guide is computed directly from the data — nothing here is
invented or estimated.

## Business problem

A national retailer sells Furniture, Office Supplies, and Technology
products across four US regions. Leadership wants to know: where is the
business making money, where is it losing money, and what's driving the
difference? Specifically:

- Which regions, categories, and segments drive the most sales and profit?
- Are any products or sub-categories consistently unprofitable?
- Does discounting help move volume, or does it erode margin?
- How does shipping method affect delivery time?

This project answers those questions with a reproducible pipeline: raw CSV
in, cleaned SQL database out, verified summary tables and insights out, and
a Power BI dashboard on top.

## Dataset and stack

- **Dataset**: [Superstore Sales](data/superstore.csv) — 9,994 order line
  items, 2014–2018, 21 original columns (order/ship dates, customer,
  product, geography, sales, quantity, discount, profit).
- **Stack**: Python 3.13, pandas, SQLite (stdlib `sqlite3`), SQL, Power BI
  Desktop.
- **No web app, no ML** — this is a data cleaning + SQL analytics +
  BI-dashboard project.

## Architecture

```
data/
  superstore.csv            # raw source data (never modified)
  cleaned_superstore.csv    # output of clean_data.py
src/
  clean_data.py             # standardize, validate, engineer columns
  create_database.py        # load cleaned CSV into SQLite
  analyze_data.py           # SQL analysis -> summaries + insights
outputs/
  summaries/                 # one CSV per analysis question
  insights.txt               # verified, plain-language findings
retail_sales.db              # SQLite database (orders table)
README.md
POWER_BI_GUIDE.md
RESUME_CONTENT.md
```

Pipeline flow: `superstore.csv` → `clean_data.py` → `cleaned_superstore.csv`
→ `create_database.py` → `retail_sales.db` → `analyze_data.py` →
`outputs/summaries/*.csv` + `outputs/insights.txt` → Power BI (reads
`retail_sales.db` directly).

## Data cleaning (`src/clean_data.py`)

- Converts all column headers to `snake_case` (e.g. `Order ID` →
  `order_id`).
- Removes exact duplicate rows (0 found in this dataset).
- Parses `order_date`/`ship_date` as dates (source format `M/D/YYYY`) and
  coerces `sales`, `quantity`, `discount`, `profit`, `postal_code` to
  numeric types.
- Conservatively drops only rows missing a critical ID (`order_id`,
  `customer_id`, `product_id`) or a missing `order_date`/`sales` value — no
  such rows existed in this dataset, so all 9,994 rows are retained.
- Detects (and reports, without silently fixing) invalid dates and negative
  shipping days — none were found.
- Adds derived columns:
  - `order_year`, `order_month`, `order_quarter`
  - `shipping_days` = `ship_date` − `order_date`
  - `profit_margin_pct` = `profit / sales * 100`
  - `is_profitable` = `profit > 0`
  - `discount_band` = No Discount / Low (0–20%) / Medium (20–40%) / High (40%+)
- Prints a before/after row and column count summary, plus any remaining
  flagged issues.
- Writes `data/cleaned_superstore.csv` (9,994 rows, 28 columns).

**One real data-quality finding surfaced during cleaning**: 32 `product_id`
values map to more than one `product_name` spelling in the source data
(e.g. minor text variants of the same product). `analyze_data.py` groups
products by `product_id` alone (not by name) to avoid inflating product
counts, and picks one representative name per ID.

## Database (`src/create_database.py`)

- Loads `cleaned_superstore.csv` into `retail_sales.db` as a single
  `orders` table (one row per order line item — the same grain as the
  cleaned CSV).
- Indexes: `order_id`, `customer_id`, `product_id`, `order_date`, `region`,
  `category`.
- Verifies `COUNT(*)` in SQLite equals the CSV row count before finishing
  (9,994 = 9,994).

## SQL analysis (`src/analyze_data.py`)

Every query runs against `retail_sales.db`. Before analyzing, the script
re-validates SQL `SUM(sales)`/`SUM(profit)`/row count against the cleaned
CSV computed independently in pandas, and asserts they match to the cent.
Results tables are exported to `outputs/summaries/`:

| File | Contents |
|---|---|
| `kpi_summary.csv` | Total sales, profit, orders, AOV, margin, avg discount, avg shipping days, % profitable |
| `yearly_trends.csv` | Sales/profit/orders/margin by year |
| `monthly_trends.csv` | Sales/profit/orders by year+month, sorted chronologically |
| `region_performance.csv` | Sales/profit/orders/margin by region |
| `category_performance.csv` | Same, by category |
| `subcategory_performance.csv` | Same, by sub-category |
| `segment_performance.csv` | Same, by customer segment |
| `top_products_by_sales.csv` | Top 10 products by total sales |
| `top_products_by_profit.csv` | Top 10 products by total profit |
| `top_customers_by_sales.csv` | Top 10 customers by total sales |
| `loss_making_products.csv` | All products with negative total profit |
| `discount_analysis.csv` | Sales/profit/margin by discount band |
| `shipping_analysis.csv` | Avg/min/max shipping days by ship mode |
| `pareto_analysis.csv` | Products ranked by sales with cumulative % (80/20 analysis) |

Key formulas used consistently throughout:

- **Average order value** = `SUM(sales) / COUNT(DISTINCT order_id)` (not
  per line item).
- **Profit margin %** = `SUM(profit) * 100.0 / SUM(sales)` (total profit
  over total sales, not an average of per-row margins).

## Verified findings

Generated by `analyze_data.py` and written to
[outputs/insights.txt](outputs/insights.txt); reproduced here (all figures
computed from `retail_sales.db`, 9,994 rows):

1. 5,009 distinct orders (9,994 line items) total **$2,297,200.86** in
   sales and **$286,397.02** in profit — a **12.47%** overall profit
   margin.
2. Average order value is **$458.61**. Average discount is **15.62%**,
   average shipping time is **3.96 days**, and **80.63%** of line items
   are profitable.
3. **2017** was the highest-sales year at $733,215.26 (12.74% margin).
4. The **West** region leads in sales ($725,457.82); the **Central**
   region has the lowest profit margin (7.92%).
5. **Technology** is the top-selling category ($836,154.03, 17.40%
   margin); **Tables** is the weakest sub-category by margin (-8.56%).
6. The **Consumer** segment drives the most sales ($1,161,401.34, 11.55%
   margin).
7. Top product by sales: **Canon imageCLASS 2200 Advanced Copier**
   ($61,599.82). Top customer by sales: **Sean Miller** ($25,043.05 across
   5 orders) — notably, despite being the top customer by revenue, Sean
   Miller's orders are a net loss (-$1,980.74 total profit).
8. **299 products** are loss-making overall, totaling **-$76,721.13** in
   combined losses.
9. The **High (40%+)** discount band averages **70.03%** discount and a
   **-77.40%** profit margin — heavy discounting is strongly associated
   with losses in this data.
10. **Same Day** shipping averages 0.04 days; **Standard Class** averages
    5.01 days.
11. **Pareto**: 414 of 1,862 products (22.23% of the catalog) generate 80%
    of total sales.

## Setup and run

Requires Python 3.13+ on Windows (uses only the standard library plus
pandas — no other dependencies).

```powershell
# from the project root
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

python src\clean_data.py
python src\create_database.py
python src\analyze_data.py
```

Each script can be re-run independently; `create_database.py` rebuilds
`retail_sales.db` from scratch each time, and `analyze_data.py` overwrites
`outputs/summaries/*.csv` and `outputs/insights.txt`.

## Power BI

See [POWER_BI_GUIDE.md](POWER_BI_GUIDE.md) for exact, step-by-step
instructions to build a one-page dashboard on top of `retail_sales.db`,
including KPI cards, visuals, slicers, and verified DAX measures.

**Screenshot placeholders** (add after building the dashboard):

- `docs/screenshots/dashboard-overview.png` — full dashboard page
- `docs/screenshots/kpi-cards.png` — KPI card row close-up
- `docs/screenshots/region-category-visuals.png` — region/category
  breakdown visuals

## Limitations and future improvements

- **Data quality**: 32 `product_id` values have inconsistent
  `product_name` text in the source data; handled by grouping on
  `product_id` only, but the underlying text inconsistency isn't corrected.
- **Grain**: analysis is at the order-line-item level; order-level
  shipping/discount figures are aggregates across a customer's line items,
  not independently verified per shipment.
- **Time range**: 2018 data is a partial year (42 rows, likely early
  January), which slightly understates 2018 in any year-over-year view —
  not included as a standalone "year" finding for that reason.
- **No customer-level profitability segmentation** (e.g. RFM/CLV) — a
  natural next step given the loss-making top-customer finding above.
- **No forecasting/ML** — out of scope by design; a reasonable extension
  would be a simple monthly sales forecast using the `monthly_trends`
  output.
- **Single-page Power BI dashboard** — could be extended to a multi-page
  report (e.g., a dedicated products page, a customer page).

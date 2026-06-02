# Fabric notebook source


# MARKDOWN ********************

# # 03 — Load Substrate
# 
# **AnswerTrust accelerator · demo substrate (Phase 2)**
# 
# Promotes the generated CSVs into the serving layer the Data Agent will query:
# 
# 1. **CSV → Delta** — read each CSV from Lakehouse Files, write a managed Delta table.
# 2. **Delta → Warehouse** — create matching tables in `AnswerTrustDemo_WH` and load them.
# 3. **Star schema** — the four tables form a star: `fact_sales` + 3 dimensions.
# 
# > The Semantic Model + measures (`TotalRevenue`, `TotalMargin`, `AvgMarginPercent`,
# > `SalesCount`) are defined in the **markdown reference at the end** — in Fabric these are
# > authored on the Warehouse's default semantic model via the modeling UI or TMDL; the DAX
# > is captured here so the model is reproducible.

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
data_path       = "Files/datasets/business_metrics"
warehouse_name  = "AnswerTrustDemo_WH"
tables          = ["dim_regions", "dim_products", "dim_customers", "fact_sales"]

# MARKDOWN ********************

# ## 1. CSV → Delta tables (Lakehouse)

# CELL ********************

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

spark = SparkSession.builder.getOrCreate()

schemas = {}
for name in tables:
    csv_path = f"{data_path}/{name}.csv"
    df = (
        spark.read.option("header", True)
        .option("inferSchema", True)
        .csv(csv_path)
    )
    df.write.mode("overwrite").format("delta").saveAsTable(name)
    schemas[name] = df.schema
    print(f"[delta] {name:<14} rows={df.count():>6,} cols={len(df.columns)}")

# CELL ********************

# Quick data-quality peek (informational — the M5 gate formalizes this later).
fs = spark.table("fact_sales")
null_rev = fs.filter(F.col("revenue").isNull()).count()
null_region = fs.filter(F.col("region_id").isNull()).count()
neg_margin = fs.filter(F.col("margin") < 0).count()
print(f"DQ peek — null revenue={null_rev}, null region={null_region}, neg margin={neg_margin}")

# MARKDOWN ********************

# ## 2. Delta → Warehouse (T-SQL)
# 
# The Warehouse reads from the Lakehouse via cross-database `SELECT`. We create the target
# schema and `CTAS`-load from the one-Lake Delta tables. `{lakehouse_name}` is resolved by
# the orchestration step (notebook 01 emits ids).

# CELL ********************

ddl = """
-- Drop-and-recreate keeps the demo re-runnable.
IF OBJECT_ID('dbo.fact_sales','U')   IS NOT NULL DROP TABLE dbo.fact_sales;
IF OBJECT_ID('dbo.dim_customers','U')IS NOT NULL DROP TABLE dbo.dim_customers;
IF OBJECT_ID('dbo.dim_products','U') IS NOT NULL DROP TABLE dbo.dim_products;
IF OBJECT_ID('dbo.dim_regions','U')  IS NOT NULL DROP TABLE dbo.dim_regions;

CREATE TABLE dbo.dim_regions (
    region_id INT NOT NULL,
    region_name VARCHAR(128),
    country VARCHAR(64),
    timezone VARCHAR(64),
    data_classification VARCHAR(32)
);
CREATE TABLE dbo.dim_products (
    product_id INT NOT NULL,
    product_name VARCHAR(128),
    category VARCHAR(64),
    unit_price DECIMAL(10,2),
    cost DECIMAL(10,2),
    launch_date DATE
);
CREATE TABLE dbo.dim_customers (
    customer_id INT NOT NULL,
    customer_name VARCHAR(256),
    segment VARCHAR(32),
    region_id INT,
    credit_limit INT,
    is_vip BIT,
    email_domain VARCHAR(128)
);
CREATE TABLE dbo.fact_sales (
    sale_id INT NOT NULL,
    sale_date DATE,
    customer_id INT,
    product_id INT,
    region_id INT,
    quantity INT,
    revenue DECIMAL(12,2),
    cost DECIMAL(12,2),
    margin DECIMAL(12,2)
);
"""
print("Warehouse DDL prepared. Execute via the Warehouse T-SQL endpoint or the cell below.")

# CELL ********************

# Execute the DDL + load against the Warehouse using the Fabric T-SQL connector.
# `notebookutils.data` returns a connection bound to the named Warehouse in this workspace.
import notebookutils

lakehouse_name = "AnswerTrustDemo_LH"  # source DB (same OneLake); pipeline may override

try:
    conn = notebookutils.data.connect_to_artifact(warehouse_name)

    # 1) Create the target schema.
    for stmt in [s for s in ddl.split(";") if s.strip()]:
        conn.execute(stmt)

    # 2) Cross-database load from the Lakehouse SQL endpoint (same workspace / OneLake).
    for name in tables:
        conn.execute(f"INSERT INTO dbo.{name} SELECT * FROM [{lakehouse_name}].dbo.{name}")
        print(f"[warehouse] loaded dbo.{name}")

    print("Warehouse star schema loaded.")
except Exception as exc:  # noqa: BLE001
    print(f"Warehouse load deferred (run inside Fabric): {exc}")


# MARKDOWN ********************

# > **Load note.** In Fabric, the simplest production-grade load is a cross-database
# > `INSERT ... SELECT` from the Lakehouse SQL endpoint (same OneLake), or `COPY INTO`
# > from the CSVs in `Files/`. The exact source database name is the Lakehouse created in
# > notebook 01; the pipeline injects it. Both tables share the workspace, so:
# >
# > ```sql
# > INSERT INTO dbo.fact_sales
# > SELECT sale_id, sale_date, customer_id, product_id, region_id,
# >        quantity, revenue, cost, margin
# > FROM [AnswerTrustDemo_LH].dbo.fact_sales;
# > ```

# MARKDOWN ********************

# ## 3. Semantic Model — star schema + measures (DAX reference)
# 
# **Relationships** (single-direction, many-to-one from fact to dims):
# 
# - `fact_sales[region_id]`   → `dim_regions[region_id]`
# - `fact_sales[product_id]`  → `dim_products[product_id]`
# - `fact_sales[customer_id]` → `dim_customers[customer_id]`
# 
# **Measures** (authored on the default semantic model):
# 
# ```dax
# TotalRevenue     = SUM ( fact_sales[revenue] )
# TotalMargin      = SUM ( fact_sales[margin] )
# SalesCount       = COUNTROWS ( fact_sales )
# AvgMarginPercent =
#     DIVIDE ( [TotalMargin], [TotalRevenue] )
# ```
# 
# These four measures are what the BusinessMetrics Data Agent (notebook 04) references when
# answering questions like “What was total revenue in Q1 2026?” or “Which region had the
# highest margin in 2025?”. The golden-question set in `scripts/golden_questions.json`
# pins expected answer ranges against these definitions.

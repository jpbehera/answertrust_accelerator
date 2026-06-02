# Fabric notebook source


# MARKDOWN ********************

# # 02 — Generate Sample Data
# 
# **AnswerTrust accelerator · demo substrate (Phase 2)**
# 
# Generates the **BusinessMetrics** dataset and writes the four CSV files into the
# attached Lakehouse under `Files/datasets/business_metrics/`. The generation logic is
# identical to the local script in `scripts/00_Generate_BusinessMetrics_Data.py` — it is
# inlined here so the notebook runs without external file dependencies inside Fabric.
# 
# Output (per default sizing):
# 
# | File | Rows |
# |------|------|
# | `dim_regions.csv` | 50 |
# | `dim_products.csv` | 100 |
# | `dim_customers.csv` | 200 (PII → Confidential) |
# | `fact_sales.csv` | 10,000 (~5% quality issues) |

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
data_path           = "Files/datasets/business_metrics"  # Lakehouse-relative path
seed                = 42
n_regions           = 50
n_products          = 100
n_customers         = 200
n_sales             = 10_000
quality_issue_rate  = 0.05

# CELL ********************

import os
from datetime import date, timedelta
import numpy as np
import pandas as pd
from faker import Faker

rng = np.random.default_rng(seed)
faker = Faker()
Faker.seed(seed)

_COUNTRIES = [
    ("United States", "America/New_York", "General"),
    ("Canada", "America/Toronto", "General"),
    ("United Kingdom", "Europe/London", "General"),
    ("Germany", "Europe/Berlin", "Confidential"),
    ("France", "Europe/Paris", "Confidential"),
    ("Japan", "Asia/Tokyo", "General"),
    ("Australia", "Australia/Sydney", "General"),
    ("Brazil", "America/Sao_Paulo", "General"),
    ("India", "Asia/Kolkata", "General"),
    ("Singapore", "Asia/Singapore", "General"),
]
_CATEGORIES = ["Widgets", "Gadgets", "Accessories", "Software", "Services", "Hardware"]
_ADJ = ["Pro", "Lite", "Max", "Plus", "Mini", "Ultra", "Core", "Edge"]
_SEGMENTS = ["Enterprise", "Mid-Market", "SMB", "Consumer"]

# CELL ********************

# --- dim_regions ---------------------------------------------------------------------
regions = pd.DataFrame([
    {
        "region_id": i,
        "region_name": f"{(c := _COUNTRIES[rng.integers(0, len(_COUNTRIES))])[0]} - Zone {((i - 1) % 9) + 1}",
        "country": c[0],
        "timezone": c[1],
        "data_classification": c[2],
    }
    for i in range(1, n_regions + 1)
])

# --- dim_products --------------------------------------------------------------------
_base = date(2022, 1, 1)
prod_rows = []
for i in range(1, n_products + 1):
    cat = _CATEGORIES[rng.integers(0, len(_CATEGORIES))]
    price = round(float(rng.uniform(9.99, 999.99)), 2)
    cost = round(price * float(rng.uniform(0.40, 0.75)), 2)
    prod_rows.append({
        "product_id": i,
        "product_name": f"{cat[:-1]} {_ADJ[rng.integers(0, len(_ADJ))]} {i:03d}",
        "category": cat,
        "unit_price": price,
        "cost": cost,
        "launch_date": (_base + timedelta(days=int(rng.integers(0, 1200)))).isoformat(),
    })
products = pd.DataFrame(prod_rows)

# --- dim_customers (PII) -------------------------------------------------------------
cust_rows = []
for i in range(1, n_customers + 1):
    credit = int(rng.choice([5_000, 10_000, 25_000, 50_000, 100_000, 250_000]))
    cust_rows.append({
        "customer_id": i,
        "customer_name": faker.company() if rng.random() < 0.6 else faker.name(),
        "segment": _SEGMENTS[rng.integers(0, len(_SEGMENTS))],
        "region_id": int(rng.integers(1, n_regions + 1)),
        "credit_limit": credit,
        "is_vip": bool(credit >= 100_000 and rng.random() < 0.7),
        "email_domain": faker.domain_name(),
    })
customers = pd.DataFrame(cust_rows)

# CELL ********************

# --- fact_sales (with ~5% intentional quality issues) --------------------------------
start, end = date(2024, 1, 1), date(2026, 3, 31)
span = (end - start).days
price_map = products.set_index("product_id")["unit_price"].to_dict()
cost_map = products.set_index("product_id")["cost"].to_dict()
pids = products["product_id"].to_numpy()

sale_rows = []
for sid in range(1, n_sales + 1):
    pid = int(pids[rng.integers(0, len(pids))])
    qty = int(rng.integers(1, 51))
    rev = round(price_map[pid] * qty, 2)
    cost = round(cost_map[pid] * qty, 2)
    sale_rows.append({
        "sale_id": sid,
        "sale_date": (start + timedelta(days=int(rng.integers(0, span + 1)))).isoformat(),
        "customer_id": int(rng.integers(1, n_customers + 1)),
        "product_id": pid,
        "region_id": int(rng.integers(1, n_regions + 1)),
        "quantity": qty,
        "revenue": rev,
        "cost": cost,
        "margin": round(rev - cost, 2),
    })
sales = pd.DataFrame(sale_rows)

n_issues = int(len(sales) * quality_issue_rate)
bad = rng.choice(sales.index.to_numpy(), size=n_issues, replace=False)
t = np.array_split(bad, 3)
sales.loc[t[0], ["revenue", "margin"]] = np.nan                       # null measure
sales.loc[t[1], "region_id"] = np.nan                                  # orphan dim
sales.loc[t[2], "margin"] = -np.abs(sales.loc[t[2], "margin"].fillna(1.0)) * 1.5  # neg margin

print(f"fact_sales issues: {n_issues} / {len(sales)} ({n_issues/len(sales):.1%})")

# MARKDOWN ********************

# ## Write CSVs to Lakehouse Files

# CELL ********************

# Inside Fabric, the attached Lakehouse mounts at /lakehouse/default/.
local_root = f"/lakehouse/default/{data_path}"
os.makedirs(local_root, exist_ok=True)

tables = {
    "dim_regions": regions,
    "dim_products": products,
    "dim_customers": customers,
    "fact_sales": sales,
}
for name, df in tables.items():
    path = f"{local_root}/{name}.csv"
    df.to_csv(path, index=False)
    print(f"  wrote {path}  rows={len(df):,}")

print("\nSample data generated and uploaded to Lakehouse Files.")

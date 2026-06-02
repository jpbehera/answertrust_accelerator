#!/usr/bin/env python3
"""
Generate the BusinessMetrics demo substrate for the AnswerTrust accelerator.

Produces four CSV files that form a small star schema:

    dim_regions    (~50 rows)   region master + data classification
    dim_products   (~100 rows)  product catalog with price / cost
    dim_customers  (~200 rows)  customers WITH PII (name, email_domain) -> Confidential
    fact_sales     (~10,000)    sales facts spanning 2024-Q1 .. 2026-Q1

About 5% of fact_sales rows carry INTENTIONAL quality issues (null revenue, null
region, negative margin). These drive the Data-Quality gate (M5) demo downstream.

Usage:
    python 00_Generate_BusinessMetrics_Data.py --out ./_local_output --seed 42

The script is dependency-light (pandas, numpy, Faker) and deterministic for a given
seed so the substrate is reproducible across runs and machines.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

try:
    # When run inside the package directory.
    from config import GeneratorConfig, SENSITIVITY_LABELS, TABLE_FILES
except ImportError:  # pragma: no cover - fallback for direct execution paths
    from scripts.config import GeneratorConfig, SENSITIVITY_LABELS, TABLE_FILES


# --- Reference data ---------------------------------------------------------------------

_COUNTRIES = [
    ("United States", "America/New_York", "General"),
    ("Canada", "America/Toronto", "General"),
    ("United Kingdom", "Europe/London", "General"),
    ("Germany", "Europe/Berlin", "Confidential"),  # GDPR-sensitive region
    ("France", "Europe/Paris", "Confidential"),
    ("Japan", "Asia/Tokyo", "General"),
    ("Australia", "Australia/Sydney", "General"),
    ("Brazil", "America/Sao_Paulo", "General"),
    ("India", "Asia/Kolkata", "General"),
    ("Singapore", "Asia/Singapore", "General"),
]

_PRODUCT_CATEGORIES = [
    "Widgets",
    "Gadgets",
    "Accessories",
    "Software",
    "Services",
    "Hardware",
]

_PRODUCT_ADJECTIVES = ["Pro", "Lite", "Max", "Plus", "Mini", "Ultra", "Core", "Edge"]

_SEGMENTS = ["Enterprise", "Mid-Market", "SMB", "Consumer"]


# --- Dimension builders -----------------------------------------------------------------

def build_regions(cfg: GeneratorConfig, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(1, cfg.n_regions + 1):
        country, tz, classification = _COUNTRIES[rng.integers(0, len(_COUNTRIES))]
        rows.append(
            {
                "region_id": i,
                "region_name": f"{country} - Zone {((i - 1) % 9) + 1}",
                "country": country,
                "timezone": tz,
                "data_classification": classification,
            }
        )
    return pd.DataFrame(rows)


def build_products(cfg: GeneratorConfig, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    base_date = date(2022, 1, 1)
    for i in range(1, cfg.n_products + 1):
        category = _PRODUCT_CATEGORIES[rng.integers(0, len(_PRODUCT_CATEGORIES))]
        adjective = _PRODUCT_ADJECTIVES[rng.integers(0, len(_PRODUCT_ADJECTIVES))]
        unit_price = round(float(rng.uniform(9.99, 999.99)), 2)
        # Cost is 40-75% of price -> positive margins by default.
        cost = round(unit_price * float(rng.uniform(0.40, 0.75)), 2)
        launch = base_date + timedelta(days=int(rng.integers(0, 1200)))
        rows.append(
            {
                "product_id": i,
                "product_name": f"{category[:-1]} {adjective} {i:03d}",
                "category": category,
                "unit_price": unit_price,
                "cost": cost,
                "launch_date": launch.isoformat(),
            }
        )
    return pd.DataFrame(rows)


def build_customers(
    cfg: GeneratorConfig, rng: np.random.Generator, faker: Faker
) -> pd.DataFrame:
    rows = []
    for i in range(1, cfg.n_customers + 1):
        name = faker.company() if rng.random() < 0.6 else faker.name()
        segment = _SEGMENTS[rng.integers(0, len(_SEGMENTS))]
        region_id = int(rng.integers(1, cfg.n_regions + 1))
        credit_limit = int(rng.choice([5_000, 10_000, 25_000, 50_000, 100_000, 250_000]))
        is_vip = bool(credit_limit >= 100_000 and rng.random() < 0.7)
        email_domain = faker.domain_name()
        rows.append(
            {
                "customer_id": i,
                "customer_name": name,  # PII
                "segment": segment,
                "region_id": region_id,
                "credit_limit": credit_limit,
                "is_vip": is_vip,
                "email_domain": email_domain,  # PII-adjacent
            }
        )
    return pd.DataFrame(rows)


# --- Fact builder -----------------------------------------------------------------------

def build_sales(
    cfg: GeneratorConfig,
    rng: np.random.Generator,
    products: pd.DataFrame,
    n_customers: int,
    n_regions: int,
) -> pd.DataFrame:
    start = date(2024, 1, 1)
    end = date(2026, 3, 31)
    span_days = (end - start).days

    product_ids = products["product_id"].to_numpy()
    unit_prices = products.set_index("product_id")["unit_price"].to_dict()
    costs = products.set_index("product_id")["cost"].to_dict()

    rows = []
    for sale_id in range(1, cfg.n_sales + 1):
        sale_date = start + timedelta(days=int(rng.integers(0, span_days + 1)))
        product_id = int(product_ids[rng.integers(0, len(product_ids))])
        customer_id = int(rng.integers(1, n_customers + 1))
        region_id = int(rng.integers(1, n_regions + 1))
        quantity = int(rng.integers(1, 51))
        unit_price = unit_prices[product_id]
        unit_cost = costs[product_id]
        revenue = round(unit_price * quantity, 2)
        cost = round(unit_cost * quantity, 2)
        margin = round(revenue - cost, 2)
        rows.append(
            {
                "sale_id": sale_id,
                "sale_date": sale_date.isoformat(),
                "customer_id": customer_id,
                "product_id": product_id,
                "region_id": region_id,
                "quantity": quantity,
                "revenue": revenue,
                "cost": cost,
                "margin": margin,
            }
        )

    df = pd.DataFrame(rows)
    df = _inject_quality_issues(df, cfg, rng)
    return df


def _inject_quality_issues(
    df: pd.DataFrame, cfg: GeneratorConfig, rng: np.random.Generator
) -> pd.DataFrame:
    """Corrupt ~quality_issue_rate of rows with realistic data-quality problems."""
    n_issues = int(len(df) * cfg.quality_issue_rate)
    if n_issues == 0:
        return df

    idx = rng.choice(df.index.to_numpy(), size=n_issues, replace=False)
    # Split the bad rows across three issue types.
    thirds = np.array_split(idx, 3)

    # 1) Null revenue (missing measure).
    df.loc[thirds[0], "revenue"] = np.nan
    df.loc[thirds[0], "margin"] = np.nan

    # 2) Null region (orphaned dimension reference).
    df.loc[thirds[1], "region_id"] = np.nan

    # 3) Negative margin (cost exceeds revenue — business-rule violation).
    df.loc[thirds[2], "margin"] = -np.abs(
        df.loc[thirds[2], "margin"].fillna(1.0)
    ) * float(rng.uniform(1.0, 2.0))

    return df


# --- Orchestration ----------------------------------------------------------------------

def generate(cfg: GeneratorConfig) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(cfg.seed)
    faker = Faker()
    Faker.seed(cfg.seed)

    regions = build_regions(cfg, rng)
    products = build_products(cfg, rng)
    customers = build_customers(cfg, rng, faker)
    sales = build_sales(cfg, rng, products, cfg.n_customers, cfg.n_regions)

    return {
        "dim_regions": regions,
        "dim_products": products,
        "dim_customers": customers,
        "fact_sales": sales,
    }


def write_csvs(tables: dict[str, pd.DataFrame], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for name, df in tables.items():
        path = os.path.join(out_dir, TABLE_FILES[name])
        df.to_csv(path, index=False)
        label = SENSITIVITY_LABELS.get(name, "General")
        print(f"  wrote {path:<48} rows={len(df):>6,}  label={label}")


def _summarize(tables: dict[str, pd.DataFrame]) -> None:
    sales = tables["fact_sales"]
    null_rev = int(sales["revenue"].isna().sum())
    null_region = int(sales["region_id"].isna().sum())
    neg_margin = int((sales["margin"] < 0).sum())
    total = len(sales)
    bad = null_rev + null_region + neg_margin
    print("\nData-quality summary (fact_sales):")
    print(f"  null revenue   : {null_rev:>5,}")
    print(f"  null region    : {null_region:>5,}")
    print(f"  negative margin: {neg_margin:>5,}")
    print(f"  total issues   : {bad:>5,} / {total:,} rows ({bad / total:.1%})")


def parse_args() -> GeneratorConfig:
    p = argparse.ArgumentParser(description="Generate the BusinessMetrics demo substrate.")
    p.add_argument("--out", default="./_local_output", help="Output directory for CSVs.")
    p.add_argument("--seed", type=int, default=42, help="Random seed (reproducible).")
    p.add_argument("--sales", type=int, default=10_000, help="Number of fact_sales rows.")
    args = p.parse_args()
    return GeneratorConfig(out_dir=args.out, seed=args.seed, n_sales=args.sales)


def main() -> None:
    cfg = parse_args()
    print(f"Generating BusinessMetrics substrate (seed={cfg.seed}) -> {cfg.out_dir}")
    tables = generate(cfg)
    write_csvs(tables, cfg.out_dir)
    _summarize(tables)
    print("\nDone.")


if __name__ == "__main__":
    main()

"""
Shared configuration for the AnswerTrust accelerator.

This module is the single source of truth for resource names, dataset paths, and
dataset sizing. The Fabric notebooks mirror these values into their `parameters` cell
so they remain self-contained when imported into a Fabric workspace, but local scripts
(e.g. the data generator) import directly from here.
"""

from dataclasses import dataclass, field
from typing import Dict


# --- Fabric item names (demo substrate) -------------------------------------------------
LAKEHOUSE_NAME = "AnswerTrustDemo_LH"
WAREHOUSE_NAME = "AnswerTrustDemo_WH"
EVENTHOUSE_NAME = "AnswerTrustDemo_EH"
KQL_DATABASE_NAME = "answer_ledger_db"
DATA_AGENT_NAME = "BusinessMetricsAgent"
SEMANTIC_MODEL_NAME = "BusinessMetrics_Model"

# --- Lakehouse Files path for generated CSVs --------------------------------------------
DATA_PATH = "Files/datasets/business_metrics"

# --- Dataset sizing ---------------------------------------------------------------------
N_REGIONS = 50
N_PRODUCTS = 100
N_CUSTOMERS = 200
N_SALES = 10_000

# Fraction of fact_sales rows that get intentional quality issues (drives the M5 DQ gate).
QUALITY_ISSUE_RATE = 0.05

# Reproducible default seed.
DEFAULT_SEED = 42

# --- Sensitivity-label seeds (consumed by M2 label-suggestion agent) --------------------
# Maps table name -> default sensitivity label. Customers carry PII -> Confidential.
SENSITIVITY_LABELS: Dict[str, str] = {
    "dim_regions": "General",
    "dim_products": "General",
    "dim_customers": "Confidential",
    "fact_sales": "General",
}

# Table file names (stable ordering for load steps).
TABLE_FILES = {
    "dim_regions": "dim_regions.csv",
    "dim_products": "dim_products.csv",
    "dim_customers": "dim_customers.csv",
    "fact_sales": "fact_sales.csv",
}


@dataclass
class GeneratorConfig:
    """Runtime configuration for the BusinessMetrics data generator."""

    out_dir: str = "./_local_output"
    seed: int = DEFAULT_SEED
    n_regions: int = N_REGIONS
    n_products: int = N_PRODUCTS
    n_customers: int = N_CUSTOMERS
    n_sales: int = N_SALES
    quality_issue_rate: float = QUALITY_ISSUE_RATE
    sensitivity_labels: Dict[str, str] = field(
        default_factory=lambda: dict(SENSITIVITY_LABELS)
    )

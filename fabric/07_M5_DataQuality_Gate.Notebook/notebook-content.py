# Fabric notebook source


# MARKDOWN ********************

# # 07 — M5 Data Quality Gate
# 
# **AnswerTrust accelerator · Phase 5**
# 
# Runs profile-based data-quality checks on the BusinessMetrics substrate, persists results
# to a `dq_runs` Lakehouse (`results` + `failed_rows`), and stamps the resulting `dq_score`
# onto the M4 **AnswerLedger** row for a given `trace_id`.
# 
# Dimensions evaluated (from `scripts/dq.py` / `default_dq_config()`):
# 
# | Table | Column | Dimension | Threshold |
# |---|---|---|---|
# | `fact_sales` | `revenue` | completeness | 0.95 |
# | `fact_sales` | `revenue` | consistency (>=0) | 1.00 |
# | `fact_sales` | `margin` | completeness | 0.90 |
# | `fact_sales` | `margin` | validity ([-0.5, 1.0]) | 0.98 |
# | `dim_customers` | `email_domain` | uniqueness | 0.99 |
# | `dim_customers` | `email_domain` | format | 0.95 |
# 
# Spark on Fabric; small demo tables are pulled to pandas so the **same** `scripts/dq.py`
# engine runs identically locally and in-cluster.

# MARKDOWN ********************

# ## 0. Parameters

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
lakehouse_name      = "AnswerTrustDemo_LH"
dq_lakehouse_name   = "AnswerTrustDemo_LH"   # dq_runs schema lives alongside the substrate
schema              = "dbo"
tables              = ["fact_sales", "dim_customers"]
trace_id            = ""                       # optional: AnswerLedger row to stamp dq_score onto
kql_database_name   = "answer_ledger_db"
query_uri           = ""                       # Eventhouse query URI (from notebook 06 exit)
run_id              = ""                        # auto-generated if empty

# CELL ********************

import json, uuid, datetime

if not run_id:
    run_id = f"dq-{datetime.datetime.utcnow():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
print("run_id:", run_id)

# scripts/dq.py is uploaded to the notebook's resource folder (or Files/scripts).
try:
    import dq  # noqa
except ImportError:
    import sys
    sys.path.append("builtin/")          # Fabric notebook resources
    sys.path.append("../scripts")        # local fallback
    import dq
config = dq.default_dq_config()
print(f"{len(config)} DQ rules loaded.")

# MARKDOWN ********************

# ## 1. Load tables (Spark → pandas for the demo scale)

# CELL ********************

from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

frames = {}
for t in tables:
    sdf = spark.table(f"{lakehouse_name}.{schema}.{t}")
    frames[t] = sdf.toPandas()      # BusinessMetrics is small (<=10k rows)
    print(f"{t}: {frames[t].shape[0]} rows x {frames[t].shape[1]} cols")

# MARKDOWN ********************

# ## 2. Run the DQ engine

# CELL ********************

dq_run = dq.run_dq(frames, config, run_id)

print(f"overall_score : {dq_run['overall_score']:.4f}")
print(f"gate_passed   : {dq_run['gate_passed']}")
print("\nPer-dimension results:")
for r in dq_run["results"]:
    flag = "PASS" if r["passed"] else "FAIL"
    print(f"  [{flag}] {r['table_name']}.{r['column_name']:<13} {r['dimension']:<13} "
          f"rate={r['pass_rate']:.4f} (>= {r['threshold']:.2f}) failed={r['failed_rows']}")
print(f"\nFailed rows captured: {len(dq_run['failed_rows'])}")

# MARKDOWN ********************

# ## 3. Persist to `dq_runs` Lakehouse (results + failed_rows)

# CELL ********************

import pandas as pd
from pyspark.sql import functions as F

ts = datetime.datetime.utcnow().isoformat()

results_pd = pd.DataFrame(dq_run["results"])
results_pd["timestamp"] = ts
results_pd["overall_score"] = dq_run["overall_score"]

failed_pd = pd.DataFrame(dq_run["failed_rows"]) if dq_run["failed_rows"] else \
    pd.DataFrame(columns=["run_id", "table_name", "column_name", "dimension", "row_index"])
failed_pd["timestamp"] = ts
if trace_id:
    failed_pd["trace_id"] = trace_id   # link drill-down rows back to the answer

spark.createDataFrame(results_pd).write.mode("append").saveAsTable(f"{dq_lakehouse_name}.dq_runs_results")
if not failed_pd.empty:
    spark.createDataFrame(failed_pd).write.mode("append").saveAsTable(f"{dq_lakehouse_name}.dq_runs_failed_rows")

print(f"Wrote {len(results_pd)} result rows and {len(failed_pd)} failed rows for run {run_id}.")

# MARKDOWN ********************

# ## 4. Stamp `dq_score` onto the AnswerLedger (M4)
# 
# When invoked for a specific answer (`trace_id` set), enrich its ledger row with the DQ
# score and per-dimension breakdown. Runs the KQL built by `dq.build_ledger_dq_update`.

# CELL ********************

kql = dq.build_ledger_dq_update(trace_id or "<trace_id>", dq_run)
print("KQL enrichment:\n", kql)

if trace_id and query_uri:
    import requests, notebookutils
    token = notebookutils.credentials.getToken("kusto")
    # Append a corrected provenance row carrying the DQ score (update-policy / arg_max dedupe).
    enrich = {"trace_id": trace_id, "timestamp": ts,
              "dq_score": dq_run["overall_score"],
              "dq_dimensions": dq.dq_dimensions_summary(dq_run["results"])}
    ingest_cmd = (".ingest inline into table AnswerLedger with "
                  "(format='json', ingestionMappingReference='provenance_mapping') <|\n"
                  + json.dumps(enrich))
    resp = requests.post(f"{query_uri}/v1/rest/mgmt",
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                         json={"db": kql_database_name, "csl": ingest_cmd}, timeout=60)
    print("ledger enrichment status:", resp.status_code)
else:
    print("(dry) set trace_id + query_uri to stamp the ledger row.")

# MARKDOWN ********************

# ## 5. Failed-rows drill-down
# 
# Join the captured failed-row indices back to the source table to inspect the offending
# records (the view a steward opens from the dashboard).

# CELL ********************

if dq_run["failed_rows"]:
    sample = dq_run["failed_rows"][:10]
    print("Sample failed rows:")
    for fr in sample:
        src = frames[fr["table_name"]].iloc[fr["row_index"]]
        print(f"  {fr['table_name']}.{fr['column_name']} ({fr['dimension']}) "
              f"row#{fr['row_index']} -> {src.get(fr['column_name'])!r}")
else:
    print("No failed rows — all dimensions clean.")

# CELL ********************

dq_handles = {
    "run_id": run_id,
    "overall_score": dq_run["overall_score"],
    "gate_passed": dq_run["gate_passed"],
    "results_table": f"{dq_lakehouse_name}.dq_runs_results",
    "failed_rows_table": f"{dq_lakehouse_name}.dq_runs_failed_rows",
    "trace_id": trace_id,
}
try:
    import notebookutils
    notebookutils.notebook.exit(dq_handles)
except Exception:
    print(dq_handles)

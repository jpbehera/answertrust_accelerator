# Fabric notebook source


# MARKDOWN ********************

# # 01 — Setup Workspace
# 
# **AnswerTrust accelerator · demo substrate (Phase 2)**
# 
# Creates the Fabric items the demo substrate needs, **idempotently** (existing items are
# reused, not duplicated):
# 
# | Item | Type | Purpose |
# |------|------|---------|
# | `AnswerTrustDemo_LH` | Lakehouse | Landing zone for CSVs + Delta tables |
# | `AnswerTrustDemo_WH` | Warehouse | Serving layer the Data Agent queries |
# | `AnswerTrustDemo_EH` | Eventhouse | Hosts the AnswerLedger KQL DB (M4) |
# | `answer_ledger_db` | KQL Database | Provenance rows (one per answer) |
# 
# Uses `notebookutils` + the Fabric REST API. Long-running creates are polled via the
# Long Running Operation (LRO) `Location` header.

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
workspace_id      = ""            # REQUIRED: target Fabric workspace GUID
lakehouse_name    = "AnswerTrustDemo_LH"
warehouse_name    = "AnswerTrustDemo_WH"
eventhouse_name   = "AnswerTrustDemo_EH"
kql_database_name = "answer_ledger_db"
fabric_api_base   = "https://api.fabric.microsoft.com/v1"

# CELL ********************

import time
import requests
import notebookutils

assert workspace_id, "workspace_id parameter is required"

def _headers():
    token = notebookutils.credentials.getToken("pbi")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def _items_url():
    return f"{fabric_api_base}/workspaces/{workspace_id}/items"

def find_item(display_name, item_type):
    """Return the item id if an item with this name+type exists, else None."""
    resp = requests.get(_items_url(), headers=_headers(), timeout=30)
    resp.raise_for_status()
    for item in resp.json().get("value", []):
        if item["displayName"] == display_name and item["type"] == item_type:
            return item["id"]
    return None

def _wait_for_lro(response):
    """Poll a Long Running Operation until it completes; return the created item id."""
    if response.status_code in (200, 201):
        return response.json().get("id")
    location = response.headers.get("Location")
    if not location:
        response.raise_for_status()
        return response.json().get("id")
    for _ in range(60):
        time.sleep(5)
        poll = requests.get(location, headers=_headers(), timeout=30)
        state = poll.json().get("status", poll.json().get("state"))
        if state in ("Succeeded", "Completed"):
            result = requests.get(location + "/result", headers=_headers(), timeout=30)
            return result.json().get("id") if result.ok else None
        if state in ("Failed", "Cancelled"):
            raise RuntimeError(f"LRO failed: {poll.text}")
    raise TimeoutError("LRO did not complete within timeout")

def ensure_item(display_name, item_type, extra_body=None):
    """Create the item if missing; return (item_id, created_bool)."""
    existing = find_item(display_name, item_type)
    if existing:
        print(f"[skip]   {item_type} '{display_name}' already exists ({existing})")
        return existing, False
    body = {"displayName": display_name, "type": item_type}
    if extra_body:
        body.update(extra_body)
    resp = requests.post(_items_url(), headers=_headers(), json=body, timeout=60)
    item_id = _wait_for_lro(resp)
    print(f"[create] {item_type} '{display_name}' -> {item_id}")
    return item_id, True

# MARKDOWN ********************

# ## 1. Lakehouse + Warehouse

# CELL ********************

lakehouse_id, _ = ensure_item(lakehouse_name, "Lakehouse")
warehouse_id, _ = ensure_item(warehouse_name, "Warehouse")

# MARKDOWN ********************

# ## 2. Eventhouse + KQL Database (AnswerLedger)

# CELL ********************

eventhouse_id, _ = ensure_item(eventhouse_name, "Eventhouse")

# A KQL Database lives inside an Eventhouse — pass the parent via creationPayload.
kql_db_id, _ = ensure_item(
    kql_database_name,
    "KQLDatabase",
    extra_body={
        "creationPayload": {
            "databaseType": "ReadWrite",
            "parentEventhouseItemId": eventhouse_id,
        }
    },
)

# MARKDOWN ********************

# ## 3. Stage config files into the Lakehouse
# 
# Notebooks **04** (golden-question smoke test), **06** (AnswerLedger KQL DDL) and **08**
# (governance eval) read these from `Files/config/`. We embed the content here and write it
# via the OneLake `abfss://` path so the 00→10 run is **self-contained** — no manual UI
# uploads. Re-running overwrites with the latest content (idempotent).

# CELL ********************

import json

GOLDEN_QUESTIONS_JSON = r"""{
  "metadata": {
    "dataset": "BusinessMetrics",
    "agent": "BusinessMetricsAgent",
    "version": "0.1.0",
    "description": "Golden questions for the AnswerTrust demo substrate. Each entry pins a deterministic trace_id, the natural-language question, the SQL shape the agent is expected to produce, and an answer-range assertion used by the continuous-eval gate (M6). Ranges are intentionally wide to tolerate the ~5% injected data-quality noise.",
    "schema_note": "expected_sql_pattern uses regex-ish keywords (case-insensitive substrings) the generated SQL should contain. expected_answer is a structured assertion the eval harness checks."
  },
  "questions": [
    {
      "trace_id": "gq-0001",
      "question": "What was total revenue in Q1 2026?",
      "category": "aggregation",
      "expected_sql_pattern": ["SUM(revenue)", "fact_sales", "2026"],
      "expected_answer": { "type": "numeric", "metric": "TotalRevenue", "min": 100000, "max": 5000000 }
    },
    {
      "trace_id": "gq-0002",
      "question": "Which region had the highest total margin in 2025?",
      "category": "ranking",
      "expected_sql_pattern": ["SUM(margin)", "GROUP BY", "region", "ORDER BY", "DESC"],
      "expected_answer": { "type": "entity", "entity_type": "region", "nonempty": true }
    },
    {
      "trace_id": "gq-0003",
      "question": "How many sales transactions happened in 2024?",
      "category": "count",
      "expected_sql_pattern": ["COUNT", "fact_sales", "2024"],
      "expected_answer": { "type": "numeric", "metric": "SalesCount", "min": 1000, "max": 6000 }
    },
    {
      "trace_id": "gq-0004",
      "question": "What is the average margin percentage across all sales?",
      "category": "ratio",
      "expected_sql_pattern": ["SUM(margin)", "SUM(revenue)", "fact_sales"],
      "expected_answer": { "type": "percentage", "metric": "AvgMarginPercent", "min": 20, "max": 60 }
    },
    {
      "trace_id": "gq-0005",
      "question": "Which product category generated the most revenue overall?",
      "category": "ranking",
      "expected_sql_pattern": ["SUM(revenue)", "category", "GROUP BY", "ORDER BY", "DESC"],
      "expected_answer": { "type": "entity", "entity_type": "category", "nonempty": true }
    },
    {
      "trace_id": "gq-0006",
      "question": "How many VIP customers do we have?",
      "category": "count",
      "expected_sql_pattern": ["COUNT", "dim_customers", "is_vip"],
      "expected_answer": { "type": "numeric", "min": 0, "max": 200 }
    },
    {
      "trace_id": "gq-0007",
      "question": "What was total revenue by region in 2025?",
      "category": "breakdown",
      "expected_sql_pattern": ["SUM(revenue)", "region", "GROUP BY", "2025"],
      "expected_answer": { "type": "table", "min_rows": 1 }
    },
    {
      "trace_id": "gq-0008",
      "question": "Which customer segment has the highest average credit limit?",
      "category": "ranking",
      "expected_sql_pattern": ["AVG(credit_limit)", "segment", "GROUP BY", "ORDER BY"],
      "expected_answer": { "type": "entity", "entity_type": "segment", "nonempty": true }
    },
    {
      "trace_id": "gq-0009",
      "question": "What is the total quantity sold for the Software category?",
      "category": "aggregation",
      "expected_sql_pattern": ["SUM(quantity)", "category", "Software"],
      "expected_answer": { "type": "numeric", "min": 0, "max": 200000 }
    },
    {
      "trace_id": "gq-0010",
      "question": "Show monthly revenue trend for 2025.",
      "category": "timeseries",
      "expected_sql_pattern": ["SUM(revenue)", "MONTH", "GROUP BY", "2025"],
      "expected_answer": { "type": "table", "min_rows": 1, "max_rows": 12 }
    },
    {
      "trace_id": "gq-0011",
      "question": "Which 5 products had the highest revenue in 2026?",
      "category": "topn",
      "expected_sql_pattern": ["SUM(revenue)", "product", "ORDER BY", "DESC", "TOP"],
      "expected_answer": { "type": "table", "min_rows": 1, "max_rows": 5 }
    },
    {
      "trace_id": "gq-0012",
      "question": "What is the total margin for Enterprise segment customers?",
      "category": "aggregation",
      "expected_sql_pattern": ["SUM(margin)", "segment", "Enterprise", "JOIN"],
      "expected_answer": { "type": "numeric" }
    },
    {
      "trace_id": "gq-0013",
      "question": "How many distinct customers placed orders in 2025?",
      "category": "count",
      "expected_sql_pattern": ["COUNT(DISTINCT", "customer_id", "2025"],
      "expected_answer": { "type": "numeric", "min": 1, "max": 200 }
    },
    {
      "trace_id": "gq-0014",
      "question": "What is the average revenue per sale?",
      "category": "ratio",
      "expected_sql_pattern": ["AVG(revenue)", "fact_sales"],
      "expected_answer": { "type": "numeric", "min": 0, "max": 50000 }
    },
    {
      "trace_id": "gq-0015",
      "question": "Which country contributes the most revenue?",
      "category": "ranking",
      "expected_sql_pattern": ["SUM(revenue)", "country", "GROUP BY", "ORDER BY", "DESC", "JOIN"],
      "expected_answer": { "type": "entity", "entity_type": "country", "nonempty": true }
    },
    {
      "trace_id": "gq-0016",
      "question": "What was total revenue in the first half of 2025?",
      "category": "aggregation",
      "expected_sql_pattern": ["SUM(revenue)", "2025", "BETWEEN"],
      "expected_answer": { "type": "numeric", "min": 100000, "max": 5000000 }
    },
    {
      "trace_id": "gq-0017",
      "question": "How many products are in the Hardware category?",
      "category": "count",
      "expected_sql_pattern": ["COUNT", "dim_products", "Hardware"],
      "expected_answer": { "type": "numeric", "min": 0, "max": 100 }
    },
    {
      "trace_id": "gq-0018",
      "question": "Which region had the lowest margin in 2024?",
      "category": "ranking",
      "expected_sql_pattern": ["SUM(margin)", "region", "GROUP BY", "ORDER BY", "ASC"],
      "expected_answer": { "type": "entity", "entity_type": "region", "nonempty": true }
    },
    {
      "trace_id": "gq-0019",
      "question": "What is the revenue split between VIP and non-VIP customers?",
      "category": "breakdown",
      "expected_sql_pattern": ["SUM(revenue)", "is_vip", "GROUP BY", "JOIN"],
      "expected_answer": { "type": "table", "min_rows": 1, "max_rows": 2 }
    },
    {
      "trace_id": "gq-0020",
      "question": "What was the year-over-year revenue growth from 2024 to 2025?",
      "category": "trend",
      "expected_sql_pattern": ["SUM(revenue)", "2024", "2025", "GROUP BY"],
      "expected_answer": { "type": "percentage", "min": -100, "max": 500 }
    },
    {
      "trace_id": "gq-0021",
      "question": "List the top 3 customers by total revenue.",
      "category": "topn",
      "expected_sql_pattern": ["SUM(revenue)", "customer", "ORDER BY", "DESC", "TOP"],
      "expected_answer": { "type": "table", "min_rows": 1, "max_rows": 3 }
    },
    {
      "trace_id": "gq-0022",
      "question": "What is the total cost across all sales in 2026?",
      "category": "aggregation",
      "expected_sql_pattern": ["SUM(cost)", "fact_sales", "2026"],
      "expected_answer": { "type": "numeric", "min": 0 }
    },
    {
      "trace_id": "gq-0023",
      "question": "Which product category has the best average margin percentage?",
      "category": "ranking",
      "expected_sql_pattern": ["SUM(margin)", "SUM(revenue)", "category", "GROUP BY", "ORDER BY"],
      "expected_answer": { "type": "entity", "entity_type": "category", "nonempty": true }
    },
    {
      "trace_id": "gq-0024",
      "question": "How many sales had a quantity greater than 25?",
      "category": "count",
      "expected_sql_pattern": ["COUNT", "quantity", ">"],
      "expected_answer": { "type": "numeric", "min": 0, "max": 10000 }
    },
    {
      "trace_id": "gq-0025",
      "question": "What is the average credit limit of VIP customers?",
      "category": "aggregation",
      "expected_sql_pattern": ["AVG(credit_limit)", "is_vip"],
      "expected_answer": { "type": "numeric", "min": 0 }
    },
    {
      "trace_id": "gq-0026",
      "question": "Show quarterly revenue for 2025.",
      "category": "timeseries",
      "expected_sql_pattern": ["SUM(revenue)", "QUARTER", "GROUP BY", "2025"],
      "expected_answer": { "type": "table", "min_rows": 1, "max_rows": 4 }
    },
    {
      "trace_id": "gq-0027",
      "question": "Which timezone has the most customers?",
      "category": "ranking",
      "expected_sql_pattern": ["COUNT", "timezone", "GROUP BY", "ORDER BY", "DESC", "JOIN"],
      "expected_answer": { "type": "entity", "entity_type": "timezone", "nonempty": true }
    },
    {
      "trace_id": "gq-0028",
      "question": "What is the total revenue for products launched before 2023?",
      "category": "aggregation",
      "expected_sql_pattern": ["SUM(revenue)", "launch_date", "2023", "JOIN"],
      "expected_answer": { "type": "numeric", "min": 0 }
    },
    {
      "trace_id": "gq-0029",
      "question": "How many regions are classified as Confidential?",
      "category": "count",
      "expected_sql_pattern": ["COUNT", "data_classification", "Confidential"],
      "expected_answer": { "type": "numeric", "min": 0, "max": 50 }
    },
    {
      "trace_id": "gq-0030",
      "question": "What is the total margin by customer segment for 2026?",
      "category": "breakdown",
      "expected_sql_pattern": ["SUM(margin)", "segment", "GROUP BY", "2026", "JOIN"],
      "expected_answer": { "type": "table", "min_rows": 1, "max_rows": 4 }
    }
  ]
}"""

ANSWER_LEDGER_KQL = r"""// answer_ledger.kql — AnswerTrust M4 provenance store.
// Run inside Eventhouse KQL database `answer_ledger_db`.
// One row per answer, keyed by trace_id (the M3 trace fabric trace_id).

//--------------------------------------------------------------------------------------
// 1. AnswerLedger table
//--------------------------------------------------------------------------------------
.create-merge table AnswerLedger (
    trace_id: string,
    timestamp: datetime,
    user_upn: string,
    agent_id: string,
    prompt: string,
    generated_query: string,
    source_tables: dynamic,
    sensitivity_labels: dynamic,
    dlp_decision: string,
    dq_score: real,
    dq_dimensions: dynamic,
    row_count: int,
    rows_masked: int,
    model: string,
    tokens_used: int,
    cost_usd: real,
    latency_ms: int,
    eval_scores: dynamic,
    red_team_flags: dynamic,
    irm_signals: dynamic,
    answertrust_score: real,
    trustworthy: bool
)

//--------------------------------------------------------------------------------------
// 2. JSON ingestion mapping (Eventstream custom-endpoint payload -> columns)
//--------------------------------------------------------------------------------------
.create-or-alter table AnswerLedger ingestion json mapping "provenance_mapping"
```
[
    {"column":"trace_id","Properties":{"Path":"$.trace_id"}},
    {"column":"timestamp","Properties":{"Path":"$.timestamp"}},
    {"column":"user_upn","Properties":{"Path":"$.user_upn"}},
    {"column":"agent_id","Properties":{"Path":"$.agent_id"}},
    {"column":"prompt","Properties":{"Path":"$.prompt"}},
    {"column":"generated_query","Properties":{"Path":"$.generated_query"}},
    {"column":"source_tables","Properties":{"Path":"$.source_tables"}},
    {"column":"sensitivity_labels","Properties":{"Path":"$.sensitivity_labels"}},
    {"column":"dlp_decision","Properties":{"Path":"$.dlp_decision"}},
    {"column":"dq_score","Properties":{"Path":"$.dq_score"}},
    {"column":"dq_dimensions","Properties":{"Path":"$.dq_dimensions"}},
    {"column":"row_count","Properties":{"Path":"$.row_count"}},
    {"column":"rows_masked","Properties":{"Path":"$.rows_masked"}},
    {"column":"model","Properties":{"Path":"$.model"}},
    {"column":"tokens_used","Properties":{"Path":"$.tokens_used"}},
    {"column":"cost_usd","Properties":{"Path":"$.cost_usd"}},
    {"column":"latency_ms","Properties":{"Path":"$.latency_ms"}},
    {"column":"eval_scores","Properties":{"Path":"$.eval_scores"}},
    {"column":"red_team_flags","Properties":{"Path":"$.red_team_flags"}},
    {"column":"irm_signals","Properties":{"Path":"$.irm_signals"}},
    {"column":"answertrust_score","Properties":{"Path":"$.answertrust_score"}},
    {"column":"trustworthy","Properties":{"Path":"$.trustworthy"}}
]
```

//--------------------------------------------------------------------------------------
// 3. Retention (90 days hot) — adjust to taste
//--------------------------------------------------------------------------------------
.alter-merge table AnswerLedger policy retention softdelete = 90d

//--------------------------------------------------------------------------------------
// 4. Convenience function — most recent answer per trace_id (dedupes re-emits)
//--------------------------------------------------------------------------------------
.create-or-alter function LatestAnswers() {
    AnswerLedger
    | summarize arg_max(timestamp, *) by trace_id
}

//--------------------------------------------------------------------------------------
// 5. Verification query (run after emitting test events)
//--------------------------------------------------------------------------------------
// AnswerLedger | take 10
// AnswerLedger | summarize answers=count(), avg_trust=avg(answertrust_score) by agent_id
"""

# Validate the JSON before staging so a bad edit fails loudly here, not three notebooks later.
_gq = json.loads(GOLDEN_QUESTIONS_JSON)
print(f"golden_questions.json parsed OK: {len(_gq['questions'])} questions")

# Write via the OneLake abfss path — does NOT require a default lakehouse attachment.
onelake_config = (
    f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/"
    f"{lakehouse_id}/Files/config"
)
for fname, content in {
    "golden_questions.json": GOLDEN_QUESTIONS_JSON,
    "answer_ledger.kql": ANSWER_LEDGER_KQL,
}.items():
    notebookutils.fs.put(f"{onelake_config}/{fname}", content, True)  # overwrite=True
    print(f"[stage]  Files/config/{fname} ({len(content)} bytes)")

# MARKDOWN ********************

# ## 4. Emit item ids for downstream notebooks

# CELL ********************

created = {
    "workspace_id": workspace_id,
    "lakehouse_id": lakehouse_id,
    "warehouse_id": warehouse_id,
    "eventhouse_id": eventhouse_id,
    "kql_database_id": kql_db_id,
}
print("\n=== Substrate items ready ===")
for key, value in created.items():
    print(f"  {key:<16} = {value}")

# Pass ids to the next pipeline step.
notebookutils.notebook.exit(created)

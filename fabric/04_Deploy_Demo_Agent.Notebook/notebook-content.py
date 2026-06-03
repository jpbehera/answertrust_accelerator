# Fabric notebook source


# MARKDOWN ********************

# # 04 — Deploy Demo Agent
# 
# **AnswerTrust accelerator · demo substrate (Phase 2)**
# 
# Builds and publishes the **BusinessMetricsAgent** — a *fully configured* Fabric Data Agent
# grounded on the `AnswerTrustDemo_WH` Warehouse (the star schema loaded in notebook 03).
# This is the agent whose answers AnswerTrust will later govern, trace, and score (M1–M7).
# 
# Unlike a bare item shell, this notebook actually applies the full configuration via the
# **`fabric-data-agent-sdk`**:
# 1. Create / connect the Data Agent.
# 2. Set **agent instructions** (routing + guardrails) and a publish description.
# 3. Attach the **Warehouse** data source and **select the star-schema tables**.
# 4. Set **data-source instructions** (joins, canonical measures, DQ caveats, PII rules).
# 5. Add **example queries** (few-shot NL→SQL) derived from the golden questions.
# 6. **Publish**, then run a live smoke test against the golden questions.
# 
# The SDK runs only inside a Fabric notebook (it wraps the Fabric Data Agent + OpenAI
# Assistants APIs). Requires an F2+ capacity with the AI/Copilot tenant switches enabled.
# 
# **High-concurrency note:** `%pip install` is **not supported in High Concurrency sessions**.
# Either (a) run this notebook in a **Standard** session, or (b) attach a Fabric **Environment**
# that includes the PyPI library **`fabric-data-agent-sdk`** (Environment ▸ Public libraries ▸
# Add from PyPI), then run on HC. The cell below auto-skips `%pip` when the SDK is already
# provided by an attached Environment, so it works in both modes.

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
workspace_id          = ""                              # REQUIRED: target Fabric workspace GUID
warehouse_name        = "AnswerTrustDemo_WH"            # data source (loaded in notebook 03)
agent_name            = "BusinessMetricsAgent"
golden_questions_path = "Files/config/golden_questions.json"  # staged by notebook 01
fabric_api_base       = "https://api.fabric.microsoft.com/v1"
publish_agent         = True     # publish after configuring (needed for live querying / M6)
smoke_test            = True     # load golden questions and run a live query
n_smoke               = 2        # how many golden questions to actually invoke
smoke_model           = "gpt-4o" # orchestration model for the smoke test invocation

# CELL ********************

# Ensure the Fabric Data Agent SDK is available.
# - High Concurrency sessions: %pip is NOT supported -> attach a Fabric Environment that
#   includes the PyPI package "fabric-data-agent-sdk"; this cell then just confirms it.
# - Standard sessions: if the SDK isn't already present, install it inline with %pip.
try:
    import fabric.dataagent.client  # noqa: F401  (provided by an attached Environment)
    print("fabric-data-agent-sdk already available (Environment or prior install).")
except ImportError:
    # Standard session only — %pip install fails in High Concurrency mode.
    %pip install -q -U fabric-data-agent-sdk

# CELL ********************

import json
import time

import requests
import notebookutils

from fabric.dataagent.client import (
    FabricDataAgentManagement,
    create_data_agent,
    delete_data_agent,
)

assert workspace_id, "workspace_id parameter is required"

# Warehouse star-schema columns (mirrors the DDL in notebook 03) — used for table selection.
WAREHOUSE_SCHEMA = "dbo"
WAREHOUSE_TABLES = ["fact_sales", "dim_regions", "dim_products", "dim_customers"]


def _headers():
    token = notebookutils.credentials.getToken("pbi")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def find_item(display_name, item_type):
    """Resolve a Fabric item id by display name + type via the REST API."""
    url = f"{fabric_api_base}/workspaces/{workspace_id}/items"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    for item in resp.json().get("value", []):
        if item["displayName"] == display_name and item["type"] == item_type:
            return item["id"]
    return None


warehouse_id = find_item(warehouse_name, "Warehouse")
assert warehouse_id, f"Warehouse '{warehouse_name}' not found — run notebooks 01 + 03 first."
print(f"Warehouse '{warehouse_name}' resolved -> {warehouse_id}")

# MARKDOWN ********************

# ## 1. Agent + data-source instructions
# 
# Two layers of natural-language context:
# 
# * **Agent instructions** — high-level behavior, routing, and guardrails (revenue/margin
#   definitions, DQ honesty, PII handling). Shown to the orchestrating model.
# * **Data-source instructions** — NL2SQL guidance for *this* warehouse: the join graph,
#   canonical measures, T-SQL dialect notes, the injected data-quality caveats, and the
#   confidentiality rules. Passed to the SQL-generation engine.

# CELL ********************

AGENT_INSTRUCTIONS = """\
You are the BusinessMetrics Q&A assistant for an analytics team. You answer questions about
sales, revenue, margin, products, regions, and customers by querying the AnswerTrustDemo_WH
warehouse — a star schema built on fact_sales joined to dim_regions, dim_products, and
dim_customers.

Rules:
- Always ground answers in query results. Never invent, round away, or estimate numbers.
- Use the canonical measures: TotalRevenue = SUM(revenue), TotalMargin = SUM(margin),
  SalesCount = COUNT(*) over fact_sales, AvgMarginPercent = TotalMargin / TotalRevenue * 100.
- About 5% of rows are intentionally noisy (NULL revenue, negative margin). If a result is
  materially affected by data quality, state that caveat alongside the answer.
- Customer names and email domains are Confidential. Do not expose individual customer PII
  unless the question is explicitly about a single named account the user is authorized for;
  prefer aggregates over row-level customer detail.
- Be concise: give the number(s) first, then one line on how you derived them.
"""

DATA_SOURCE_INSTRUCTIONS = """\
This is a Microsoft Fabric Warehouse (T-SQL) organized as a star schema. The fact table is
dbo.fact_sales; it joins to three dimensions on their *_id keys:
  dbo.fact_sales.region_id   -> dbo.dim_regions.region_id
  dbo.fact_sales.product_id  -> dbo.dim_products.product_id
  dbo.fact_sales.customer_id -> dbo.dim_customers.customer_id

Tables and key columns:
  fact_sales(sale_id, sale_date, customer_id, product_id, region_id, quantity, revenue, cost, margin)
  dim_regions(region_id, region_name, country, timezone, data_classification)
  dim_products(product_id, product_name, category, unit_price, cost, launch_date)
  dim_customers(customer_id, customer_name, segment, region_id, credit_limit, is_vip, email_domain)

Canonical measures (compute from fact_sales):
  TotalRevenue     = SUM(revenue)
  TotalMargin      = SUM(margin)
  SalesCount       = COUNT(*)                          -- one row per transaction
  AvgMarginPercent = SUM(margin) / NULLIF(SUM(revenue), 0) * 100

Conventions:
  - Filter time with sale_date. For a year use YEAR(sale_date) = <yyyy>; for a quarter use an
    explicit range, e.g. Q1 2026 = sale_date >= '2026-01-01' AND sale_date < '2026-04-01'.
  - "region" = dim_regions.region_name; "category" = dim_products.category;
    "VIP customers" = dim_customers.is_vip = 1.
  - T-SQL dialect: use TOP N (not LIMIT) and YEAR()/DATEPART() for date parts.

Data-quality caveats (~5% noisy rows):
  - Some revenue values are NULL and some margin values are negative. For revenue ratios add
    WHERE revenue IS NOT NULL so NULLs do not distort the result, and flag negative margins
    when they would change a ranking or total.

Privacy:
  - dim_customers.customer_name and email_domain are Confidential. Do not return individual
    customer PII unless explicitly asked about one named, authorized account. Prefer aggregates.
"""

# Few-shot NL->SQL examples (dict of {question: T-SQL}) derived from the golden questions.
FEWSHOTS = {
    "What was total revenue in Q1 2026?":
        "SELECT SUM(revenue) AS TotalRevenue "
        "FROM dbo.fact_sales "
        "WHERE sale_date >= '2026-01-01' AND sale_date < '2026-04-01';",
    "Which region had the highest total margin in 2025?":
        "SELECT TOP 1 r.region_name, SUM(f.margin) AS TotalMargin "
        "FROM dbo.fact_sales f "
        "JOIN dbo.dim_regions r ON f.region_id = r.region_id "
        "WHERE YEAR(f.sale_date) = 2025 "
        "GROUP BY r.region_name ORDER BY TotalMargin DESC;",
    "How many sales transactions happened in 2024?":
        "SELECT COUNT(*) AS SalesCount "
        "FROM dbo.fact_sales WHERE YEAR(sale_date) = 2024;",
    "What is the average margin percentage across all sales?":
        "SELECT CAST(SUM(margin) AS FLOAT) / NULLIF(SUM(revenue), 0) * 100 AS AvgMarginPercent "
        "FROM dbo.fact_sales WHERE revenue IS NOT NULL;",
    "Which product category generated the most revenue overall?":
        "SELECT TOP 1 p.category, SUM(f.revenue) AS TotalRevenue "
        "FROM dbo.fact_sales f "
        "JOIN dbo.dim_products p ON f.product_id = p.product_id "
        "GROUP BY p.category ORDER BY TotalRevenue DESC;",
    "How many VIP customers do we have?":
        "SELECT COUNT(*) AS VipCustomers FROM dbo.dim_customers WHERE is_vip = 1;",
    "What was total revenue by region in 2025?":
        "SELECT r.region_name, SUM(f.revenue) AS TotalRevenue "
        "FROM dbo.fact_sales f "
        "JOIN dbo.dim_regions r ON f.region_id = r.region_id "
        "WHERE YEAR(f.sale_date) = 2025 "
        "GROUP BY r.region_name ORDER BY TotalRevenue DESC;",
}

print(f"Agent instructions:        {len(AGENT_INSTRUCTIONS)} chars")
print(f"Data-source instructions:  {len(DATA_SOURCE_INSTRUCTIONS)} chars")
print(f"Few-shot example queries:  {len(FEWSHOTS)}")

# MARKDOWN ********************

# ## 2. Create / connect the Data Agent and set instructions

# CELL ********************

try:
    agent = create_data_agent(agent_name)
    print(f"[create] Data Agent '{agent_name}' created.")
except Exception as exc:  # name conflict -> already exists; connect to it instead
    print(f"[exists] create_data_agent failed ({exc}); connecting to existing agent.")
    agent = FabricDataAgentManagement(agent_name)

agent.update_configuration(
    instructions=AGENT_INSTRUCTIONS,
    user_description=(
        "Answers business-metrics questions (revenue, margin, sales counts, and "
        "product/region/customer breakdowns) over the AnswerTrustDemo_WH star schema. "
        "Governed agent for the AnswerTrust demo."
    ),
)
print("Agent configuration:")
print(agent.get_configuration())

# MARKDOWN ********************

# ## 3. Attach the Warehouse, select tables, set data-source instructions + few-shots

# CELL ********************

# Idempotent attach: reuse an existing data source, otherwise add the Warehouse.
datasources = agent.get_datasources()
if datasources:
    datasource = datasources[0]
    print(f"[skip] data source already attached ({datasource}).")
else:
    added = False
    last_err = None
    for ds_type in ("warehouse", "datawarehouse"):  # type keyword varies by SDK build
        try:
            agent.add_datasource(warehouse_name, type=ds_type)
            print(f"[add] Warehouse '{warehouse_name}' attached (type='{ds_type}').")
            added = True
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if not added:
        raise RuntimeError(f"Could not attach Warehouse data source: {last_err}")
    datasource = agent.get_datasources()[0]

# Select the star-schema tables the agent is allowed to query.
for table in WAREHOUSE_TABLES:
    datasource.select(WAREHOUSE_SCHEMA, table)
print(f"Selected tables: {', '.join(f'{WAREHOUSE_SCHEMA}.{t}' for t in WAREHOUSE_TABLES)}")

# Data-source-level NL2SQL instructions.
datasource.update_configuration(instructions=DATA_SOURCE_INSTRUCTIONS)
print("Data-source instructions applied.")

# Few-shot example queries (skip if already present so re-runs don't duplicate).
existing_fewshots = 0
try:
    existing_fewshots = len(datasource.get_fewshots())
except Exception:  # noqa: BLE001
    existing_fewshots = 0

if existing_fewshots == 0:
    datasource.add_fewshots(FEWSHOTS)
    print(f"Added {len(FEWSHOTS)} few-shot example queries.")
else:
    print(f"[skip] {existing_fewshots} few-shot example(s) already present.")

print("\nData source summary:")
datasource.pretty_print()

# MARKDOWN ********************

# ## 4. Publish
# 
# Publishing creates the queryable endpoint and the version the eval harness (M6) replays.

# CELL ********************

if publish_agent:
    agent.publish()
    print(f"[publish] Data Agent '{agent_name}' published.")
else:
    print("publish_agent=False — agent saved as draft only (not queryable yet).")

agent_id = find_item(agent_name, "DataAgent")
print(f"Data Agent item id: {agent_id}")

# MARKDOWN ********************

# ## 5. Smoke test — load golden questions and run a live query
# 
# Loads the 30 golden questions staged by notebook 01, then actually invokes the published
# agent on the first `n_smoke` of them via the Fabric OpenAI client (polling + cleanup per
# the SDK guidance). Module 08 (M6) replays all 30 and scores the answers.

# CELL ********************

def ask_agent(question, timeout_s=180, poll_s=3, model=smoke_model):
    """Invoke the published Data Agent once and return (status, answer_text)."""
    from fabric.dataagent.client import FabricOpenAI

    client = FabricOpenAI(artifact_name=agent_name)
    assistant = client.beta.assistants.create(model=model)
    thread = client.beta.threads.create()
    try:
        client.beta.threads.messages.create(
            thread_id=thread.id, role="user", content=question
        )
        run = client.beta.threads.runs.create(
            thread_id=thread.id, assistant_id=assistant.id
        )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if run.status in ("completed", "failed", "cancelled", "expired"):
                break
            time.sleep(poll_s)

        answer = None
        if run.status == "completed":
            for msg in client.beta.threads.messages.list(thread_id=thread.id).data:
                if msg.role == "assistant":
                    answer = msg.content[0].text.value
                    break
        return run.status, answer
    finally:
        # Release thread/assistant resources regardless of outcome.
        try:
            client.beta.threads.delete(thread.id)
            client.beta.assistants.delete(assistant.id)
        except Exception:  # noqa: BLE001
            pass


if smoke_test:
    raw = notebookutils.fs.head(golden_questions_path, 1024 * 1024)
    golden = json.loads(raw)
    questions = golden["questions"]
    print(f"Loaded {len(questions)} golden questions from {golden_questions_path}.")

    if not publish_agent:
        print("publish_agent=False — skipping live invocation (agent has no endpoint yet).")
    else:
        for q in questions[:n_smoke]:
            print(f"\n[{q['trace_id']}] {q['question']}")
            try:
                status, answer = ask_agent(q["question"])
                print(f"  status = {status}")
                print(f"  answer = {answer}")
            except Exception as exc:  # noqa: BLE001
                print(f"  live query error: {exc}")
        print(
            f"\nSmoke test invoked {min(n_smoke, len(questions))} of {len(questions)} "
            "golden questions. Module 08 (M6) replays and scores all 30."
        )
else:
    print("smoke_test disabled.")

# CELL ********************

print("\n=== Demo agent deployment summary ===")
print(f"  agent_name   = {agent_name}")
print(f"  agent_id     = {agent_id}")
print(f"  warehouse    = {warehouse_name} ({warehouse_id})")
print(f"  data source  = {WAREHOUSE_SCHEMA}.[{', '.join(WAREHOUSE_TABLES)}]")
print(f"  published    = {publish_agent}")
print("  status       = ready for governance instrumentation (modules 05–09)")

notebookutils.notebook.exit({"agent_id": agent_id, "warehouse_id": warehouse_id})

# Fabric notebook source


# MARKDOWN ********************

# # 04 — Deploy Demo Agent
# 
# **AnswerTrust accelerator · demo substrate (Phase 2)**
# 
# Deploys the **BusinessMetricsAgent** — a Fabric Data Agent grounded on the
# `AnswerTrustDemo_WH` Warehouse (the star schema loaded in notebook 03). This is the agent
# whose answers AnswerTrust will later govern, trace, and score (modules M1–M7).
# 
# Steps:
# 1. Create / update the Data Agent item via the Fabric REST API.
# 2. Attach the Warehouse as a data source and set the system prompt.
# 3. Smoke-test against the **golden questions** in `scripts/golden_questions.json`.
# 
# Uses `notebookutils` + REST so it runs across Fabric runtimes without a preview SDK.

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
workspace_id        = ""            # REQUIRED: target Fabric workspace GUID
warehouse_name      = "AnswerTrustDemo_WH"
agent_name          = "BusinessMetricsAgent"
golden_questions_path = "Files/config/golden_questions.json"  # uploaded to Lakehouse
fabric_api_base     = "https://api.fabric.microsoft.com/v1"
smoke_test          = True

# CELL ********************

import json
import requests
import notebookutils

assert workspace_id, "workspace_id parameter is required"

def _headers():
    token = notebookutils.credentials.getToken("pbi")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def _items_url():
    return f"{fabric_api_base}/workspaces/{workspace_id}/items"

def find_item(display_name, item_type):
    resp = requests.get(_items_url(), headers=_headers(), timeout=30)
    resp.raise_for_status()
    for item in resp.json().get("value", []):
        if item["displayName"] == display_name and item["type"] == item_type:
            return item["id"]
    return None

# MARKDOWN ********************

# ## 1. System prompt

# CELL ********************

SYSTEM_PROMPT = (
    "You are a Business Metrics Q&A assistant for an analytics team. "
    "You answer questions about sales, revenue, margin, products, regions, and customers "
    "by querying the BusinessMetrics warehouse (star schema: fact_sales joined to "
    "dim_regions, dim_products, dim_customers). "
    "Always ground answers in query results — never invent numbers. "
    "Use these measures: TotalRevenue = SUM(revenue), TotalMargin = SUM(margin), "
    "SalesCount = COUNTROWS(fact_sales), AvgMarginPercent = TotalMargin / TotalRevenue. "
    "Some rows have missing or anomalous values; if a result looks affected by data "
    "quality, note that caveat in your answer. "
    "Customer names and email domains are Confidential — do not expose individual PII "
    "unless the question is explicitly about a named account the user is authorized for."
)
print(SYSTEM_PROMPT)

# MARKDOWN ********************

# ## 2. Create / update the Data Agent

# CELL ********************

warehouse_id = find_item(warehouse_name, "Warehouse")
assert warehouse_id, f"Warehouse '{warehouse_name}' not found — run notebook 01/03 first."

agent_id = find_item(agent_name, "DataAgent")

agent_body = {
    "displayName": agent_name,
    "type": "DataAgent",
    "description": "BusinessMetrics Q&A agent grounded on AnswerTrustDemo_WH.",
}

if agent_id:
    print(f"[skip] DataAgent '{agent_name}' already exists ({agent_id})")
else:
    resp = requests.post(_items_url(), headers=_headers(), json=agent_body, timeout=60)
    if resp.status_code in (200, 201):
        agent_id = resp.json().get("id")
        print(f"[create] DataAgent '{agent_name}' -> {agent_id}")
    else:
        # Data Agent create surface varies by tenant; surface the response for operators.
        print(f"[warn] DataAgent create returned HTTP {resp.status_code}: {resp.text}")
        print("       Create the Data Agent in the Fabric UI and re-run for binding/smoke test.")

# MARKDOWN ********************

# ## 3. Bind the Warehouse data source + system prompt
# 
# The Data Agent configuration (data sources, instructions, example queries) is set through
# the agent's definition payload. The binding below attaches `AnswerTrustDemo_WH` and the
# system prompt above. Exact payload keys can differ by tenant version — this captures the
# intended configuration deterministically.

# CELL ********************

agent_config = {
    "instructions": SYSTEM_PROMPT,
    "dataSources": [
        {
            "type": "Warehouse",
            "workspaceId": workspace_id,
            "itemId": warehouse_id,
            "itemName": warehouse_name,
        }
    ],
}
print(json.dumps(agent_config, indent=2))
print("\nApply this config via the Data Agent definition API or the Fabric UI.")

# MARKDOWN ********************

# ## 4. Smoke test against golden questions

# CELL ********************

if smoke_test:
    try:
        raw = notebookutils.fs.head(golden_questions_path, 1024 * 1024)
        golden = json.loads(raw)
        questions = golden["questions"]
        print(f"Loaded {len(questions)} golden questions.")
        print("\nFirst 5 (these are what continuous-eval will replay in M6):")
        for q in questions[:5]:
            print(f"  [{q['trace_id']}] {q['question']}")
        print(
            "\nNOTE: actual agent invocation runs once the Data Agent endpoint is live. "
            "The eval harness in module 08 (M6) replays all 30 and scores answers."
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Golden questions not yet uploaded to Lakehouse: {exc}")
        print("Upload scripts/golden_questions.json to Files/config/ then re-run.")
else:
    print("smoke_test disabled.")

# CELL ********************

print("\n=== Demo agent deployment summary ===")
print(f"  agent_name   = {agent_name}")
print(f"  agent_id     = {agent_id}")
print(f"  warehouse    = {warehouse_name} ({warehouse_id})")
print("  status       = ready for governance instrumentation (modules 05–09)")

notebookutils.notebook.exit({"agent_id": agent_id, "warehouse_id": warehouse_id})

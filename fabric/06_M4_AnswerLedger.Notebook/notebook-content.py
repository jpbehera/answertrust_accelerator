# Fabric notebook source


# MARKDOWN ********************

# # 06 — M4 AnswerLedger (Provenance Store)
# 
# **AnswerTrust accelerator · Phase 4**
# 
# Persists **one KQL row per answer**, keyed by the `trace_id` from the M3 trace fabric.
# 
# Pipeline:
# 
# > answer wrapper → POST JSON → **Eventstream custom endpoint** → **Eventhouse** `answer_ledger_db.AnswerLedger`
# 
# This notebook:
# 1. Resolves the Eventhouse / KQL DB created in notebook 01.
# 2. Runs the `AnswerLedger` table + ingestion mapping DDL (`scripts/kql/answer_ledger.kql`).
# 3. Creates the `AnswerTrust_Provenance_Stream` Eventstream (custom endpoint → Eventhouse).
# 4. Emits test provenance events (dry-run by default) and verifies.
# 
# Uses `notebookutils` + Fabric/Kusto REST so it runs across Fabric runtimes without a preview SDK.

# MARKDOWN ********************

# ## 0. Parameters

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
workspace_id            = ""                 # REQUIRED: target Fabric workspace GUID
eventhouse_name         = "AnswerTrustDemo_EH"
kql_database_name       = "answer_ledger_db"
eventstream_name        = "AnswerTrust_Provenance_Stream"
kql_ddl_path            = "Files/config/answer_ledger.kql"        # uploaded to Lakehouse
golden_questions_path   = "Files/config/golden_questions.json"
custom_endpoint_url     = ""                 # Eventstream custom-endpoint ingest URL (set after step 3)
fabric_api_base         = "https://api.fabric.microsoft.com/v1"
run_live_emit           = False             # False = print events; True = POST to endpoint
n_test_events           = 5

# CELL ********************

import json
import time
import requests
import notebookutils

assert workspace_id, "workspace_id parameter is required"

def _headers(scope="pbi"):
    token = notebookutils.credentials.getToken(scope)
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

# ## 1. Resolve Eventhouse query URI + KQL database

# CELL ********************

eventhouse_id = find_item(eventhouse_name, "Eventhouse")
kql_db_id     = find_item(kql_database_name, "KQLDatabase")
assert eventhouse_id, f"Eventhouse '{eventhouse_name}' not found — run notebook 01 first"
assert kql_db_id, f"KQLDatabase '{kql_database_name}' not found — run notebook 01 first"

# The Eventhouse item exposes the Kusto query endpoint used for management commands.
eh = requests.get(f"{_items_url()}/{eventhouse_id}", headers=_headers(), timeout=30).json()
query_uri = (eh.get("properties", {}) or {}).get("queryServiceUri")
print("eventhouse_id :", eventhouse_id)
print("kql_db_id     :", kql_db_id)
print("query_uri     :", query_uri)

# MARKDOWN ********************

# ## 2. Create the AnswerLedger table + ingestion mapping
# 
# Runs each `.create`/`.alter` command in `scripts/kql/answer_ledger.kql` against the KQL
# database via the Kusto management endpoint (`/v1/rest/mgmt`).

# CELL ********************

def kusto_mgmt(command):
    """Execute a single KQL control command against answer_ledger_db."""
    headers = _headers(scope="kusto")
    body = {"db": kql_database_name, "csl": command}
    resp = requests.post(f"{query_uri}/v1/rest/mgmt", headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()

def split_kql_commands(text):
    """Split a .kql script into individual control commands.
    Commands start at a line beginning with '.'; '//' lines are comments;
    multi-line '```' blocks (mappings) are kept with their command."""
    commands, current, in_block = [], [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") and not in_block:
            continue
        if stripped.startswith(".") and not in_block and current:
            commands.append("\n".join(current).strip()); current = []
        if stripped == "```":
            in_block = not in_block
        current.append(line)
    if current:
        commands.append("\n".join(current).strip())
    return [c for c in commands if c and c.lstrip().startswith(".")]

# CELL ********************

try:
    ddl_text = notebookutils.fs.head(kql_ddl_path, 1024 * 1024)
except Exception:
    with open("../scripts/kql/answer_ledger.kql") as fh:  # local fallback
        ddl_text = fh.read()

commands = split_kql_commands(ddl_text)
print(f"Parsed {len(commands)} KQL control commands.")
for cmd in commands:
    head = cmd.splitlines()[0][:70]
    if query_uri:
        kusto_mgmt(cmd)
        print(f"[run]  {head}")
    else:
        print(f"[dry]  {head}")

# MARKDOWN ********************

# ## 3. Create the provenance Eventstream (custom endpoint → Eventhouse)
# 
# Creates an Eventstream item whose source is a **custom app endpoint** (where the answer
# wrapper POSTs events) and whose destination is the `AnswerLedger` table in the Eventhouse,
# using the `provenance_mapping` defined above.
# 
# After creation, copy the source's ingest URL into `custom_endpoint_url` (printed below).

# CELL ********************

import base64

eventstream_topology = {
    "sources": [
        {"name": "provenance_events", "type": "CustomEndpoint", "properties": {}}
    ],
    "destinations": [
        {
            "name": "answer_ledger",
            "type": "Eventhouse",
            "properties": {
                "dataIngestionMode": "ProcessedIngestion",
                "workspaceId": workspace_id,
                "itemId": eventhouse_id,
                "databaseName": kql_database_name,
                "tableName": "AnswerLedger",
                "inputSerialization": {"type": "Json"},
                "mappingName": "provenance_mapping",
            },
            "inputNodes": [{"name": "provenance_events"}],
        }
    ],
    "operators": [],
    "streams": [],
    "compatibilityLevel": "1.0",
}

def _b64(obj):
    raw = json.dumps(obj).encode("utf-8") if not isinstance(obj, str) else obj.encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")

platform = {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
    "metadata": {"type": "Eventstream", "displayName": eventstream_name},
    "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-000000000000"},
}

eventstream_body = {
    "displayName": eventstream_name,
    "type": "Eventstream",
    "definition": {
        "parts": [
            {"path": "eventstream.json", "payload": _b64(eventstream_topology), "payloadType": "InlineBase64"},
            {"path": ".platform", "payload": _b64(platform), "payloadType": "InlineBase64"},
        ]
    },
}
print("Eventstream definition assembled (custom endpoint -> Eventhouse).")

# CELL ********************

eventstream_id = find_item(eventstream_name, "Eventstream")
if eventstream_id:
    print(f"[skip]   Eventstream '{eventstream_name}' already exists ({eventstream_id})")
else:
    resp = requests.post(_items_url(), headers=_headers(), json=eventstream_body, timeout=120)
    if resp.status_code in (202, 201, 200):
        # Long-running create: poll the operation if needed.
        if resp.status_code == 202 and resp.headers.get("Location"):
            loc = resp.headers["Location"]
            for _ in range(40):
                time.sleep(5)
                st = requests.get(loc, headers=_headers(), timeout=30).json().get("status")
                if st in ("Succeeded", "Completed"):
                    break
        eventstream_id = find_item(eventstream_name, "Eventstream")
        print(f"[create] Eventstream '{eventstream_name}' -> {eventstream_id}")
    else:
        print(f"[warn]   create returned {resp.status_code}: {resp.text[:300]}")

# Fetch the custom-endpoint source connection (the URL the wrapper POSTs to).
if eventstream_id and not custom_endpoint_url:
    try:
        conn = requests.get(
            f"{fabric_api_base}/workspaces/{workspace_id}/eventstreams/{eventstream_id}"
            f"/topology/sources/provenance_events/connection",
            headers=_headers(), timeout=30,
        )
        if conn.ok:
            custom_endpoint_url = conn.json().get("ingestionUrl") or conn.json().get("endpointUrl", "")
            print("custom_endpoint_url:", custom_endpoint_url or "(retrieve from Eventstream UI)")
    except Exception as exc:
        print("Fetch source connection failed; copy the ingest URL from the Eventstream UI:", exc)

# MARKDOWN ********************

# ## 4. Emit test provenance events
# 
# Builds one ledger row per golden question (reusing their `trace_id`s) via the M4 emitter.
# With `run_live_emit = False` the events are printed; set it `True` once
# `custom_endpoint_url` is populated to POST them into the ledger.

# CELL ********************

from datetime import datetime, timezone
import re

# Inline copy of scripts/ledger.py essentials (notebook-self-contained).
_TABLE_RE = re.compile(r"\b(?:from|join)\s+([\[\]\w.\"`]+)", re.IGNORECASE)
# NOTE: the Fabric Data Agent runs on a Microsoft-managed model you cannot pick;
# its cost is billed via Fabric capacity CU, not per-token (hence fabric-managed=0.0).
# The per-token entries apply only to direct Azure OpenAI callers (e.g. M6 judge on o4-mini).
_PRICES = {"fabric-managed": 0.0, "gpt-4.1": 0.004, "gpt-4.1-mini": 0.0008, "o4-mini": 0.0022,
           "gpt-4o": 0.005, "gpt-4o-mini": 0.0006, "gpt-4": 0.03, "gpt-35-turbo": 0.0015}

def extract_tables_from_sql(sql):
    if not sql:
        return []
    seen = []
    for m in _TABLE_RE.findall(sql):
        name = m.strip().translate(str.maketrans("", "", '[]"`'))
        if name and name.lower() not in {"(select", "lateral"} and name not in seen:
            seen.append(name)
    return seen

def calculate_cost(usage, model="fabric-managed"):
    return round((int((usage or {}).get("total_tokens", 0)) / 1000.0) * _PRICES.get(model, 0.0), 6)

def build_provenance_event(trace_id, prompt, generated_sql, result, model="fabric-managed"):
    result = result or {}
    usage = result.get("usage", {}) or {}
    rows = result.get("rows", []) or []
    return {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_upn": result.get("user_upn", "unknown"),
        "agent_id": result.get("agent_id", "BusinessMetricsAgent"),
        "prompt": prompt,
        "generated_query": generated_sql,
        "source_tables": extract_tables_from_sql(generated_sql),
        "sensitivity_labels": result.get("sensitivity_labels", []),  # M2
        "dlp_decision": result.get("dlp_decision", "ALLOW"),          # M6
        "dq_score": float(result.get("dq_score", 0.0)),               # M5
        "dq_dimensions": result.get("dq_dimensions", {}),             # M5
        "row_count": len(rows),
        "rows_masked": int(result.get("rows_masked", 0)),             # M6
        "model": model,
        "tokens_used": int(usage.get("total_tokens", 0) or 0),
        "cost_usd": calculate_cost(usage, model),
        "latency_ms": int(result.get("latency_ms", 0) or 0),
        "eval_scores": result.get("eval_scores", {}),                 # M6
        "red_team_flags": result.get("red_team_flags", []),           # M7
        "irm_signals": result.get("irm_signals", {}),                 # M7
        "answertrust_score": float(result.get("answertrust_score", 0.0)),
        "trustworthy": bool(result.get("trustworthy", False)),
    }


# CELL ********************

# Load golden questions (reuse their trace_ids so the ledger lines up with notebook 04).
try:
    gq_text = notebookutils.fs.head(golden_questions_path, 1024 * 1024)
except Exception:
    with open("../scripts/golden_questions.json") as fh:
        gq_text = fh.read()
golden = json.loads(gq_text)
sample = golden[:n_test_events]

SQL_BY_INTENT = ("SELECT SUM(s.revenue) AS total_revenue FROM fact_sales s "
                 "JOIN dim_products p ON s.product_id = p.product_id")

emitted = []
for q in sample:
    evt = build_provenance_event(
        trace_id=q["trace_id"],
        prompt=q["question"],
        generated_sql=SQL_BY_INTENT,
        result={"usage": {"total_tokens": 850}, "rows": [{"total_revenue": 1234567.0}],
                "latency_ms": 1420},
    )
    status = emit_event(evt)
    emitted.append(evt)
    flag = f"POST {status}" if status else "DRY"
    print(f"[{flag}] {evt['trace_id']}  {evt['prompt'][:55]}")

print(f"\n{len(emitted)} provenance events built (live={run_live_emit and bool(custom_endpoint_url)}).")
print(json.dumps(emitted[0], indent=2)[:700])

# MARKDOWN ********************

# ## 5. Verify the ledger
# 
# After a live emit, confirm the rows landed (ingestion is near-real-time, allow a few seconds):

# CELL ********************

def kusto_query(kql):
    headers = _headers(scope="kusto")
    body = {"db": kql_database_name, "csl": kql}
    resp = requests.post(f"{query_uri}/v1/rest/query", headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()

if run_live_emit and custom_endpoint_url and query_uri:
    time.sleep(10)
    result = kusto_query("AnswerLedger | summarize answers=count(), distinct_traces=dcount(trace_id)")
    print(json.dumps(result, indent=2)[:800])
else:
    print("Dry run — set run_live_emit=True with a custom_endpoint_url, then run:")
    print("  AnswerLedger | take 10")
    print("  AnswerLedger | summarize answers=count(), avg_trust=avg(answertrust_score) by agent_id")

# CELL ********************

# Pass ledger handles to downstream notebooks (M5/M6/M7 enrich these rows).
ledger_handles = {
    "workspace_id": workspace_id,
    "eventhouse_id": eventhouse_id,
    "kql_database_id": kql_db_id,
    "kql_database_name": kql_database_name,
    "eventstream_name": eventstream_name,
    "ledger_table": "AnswerLedger",
    "query_uri": query_uri,
    "custom_endpoint_url": custom_endpoint_url,
}
try:
    notebookutils.notebook.exit(ledger_handles)
except Exception:
    print(ledger_handles)

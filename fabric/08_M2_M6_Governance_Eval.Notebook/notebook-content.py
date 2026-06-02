# Fabric notebook source


# MARKDOWN ********************

# # 08 — M2 Governance + M6 Runtime DLP + Continuous Eval + AnswerTrust Score
# 
# **AnswerTrust accelerator · Phase 6**
# 
# Brings together four control-plane capabilities, all backed by `scripts/governance.py`:
# 
# 1. **M2 Label-Suggestion** — heuristic recommender that proposes Purview sensitivity
#    labels for workspace tables (the deterministic core the Data Agent wraps).
# 2. **M6 Runtime DLP** — `PurviewPolicyMiddleware` enforces EXTRACT rights at inference
#    time and masks columns the caller cannot read; wired into the Foundry wrapper.
# 3. **M6 Continuous Eval** — nightly golden-question evaluation with a drift alarm.
# 4. **M6 AnswerTrust Score** — `w_e·Eval + w_d·DQ + w_l·Label + w_f·Freshness − w_r·RedTeam`,
#    stamped back onto the M4 AnswerLedger row.

# MARKDOWN ********************

# ## 0. Parameters

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
workspace_id        = ""
lakehouse_name      = "AnswerTrustDemo_LH"
warehouse_name      = "AnswerTrustDemo_WH"
kql_database_name   = "answer_ledger_db"
query_uri           = ""                       # Eventhouse query URI (from notebook 06 exit)
golden_questions_path = "Files/config/golden_questions.json"
apply_labels        = False                    # set True to call Bulk Set Labels API
run_live_eval       = False                    # set True to invoke the live agent + Foundry evals
trust_threshold     = 0.70

# CELL ********************

import json
try:
    import governance as gov  # noqa
except ImportError:
    import sys
    sys.path.append("builtin/")
    sys.path.append("../scripts")
    import governance as gov
print("governance loaded. default weights:", gov.DEFAULT_WEIGHTS)

# MARKDOWN ********************

# ## 1. M2 — Label-Suggestion Agent
# 
# The Data Agent's deterministic core. We inspect each table's columns and recommend a
# sensitivity label. In production this runs as a Fabric Data Agent with tools
# `list_workspace_items` / `get_table_schema` / `sample_table_data`; here we drive the
# same `governance.suggest_label` it calls.

# CELL ********************

# Schemas for the BusinessMetrics substrate (would come from get_table_schema on Fabric).
table_columns = {
    "dim_regions":  ["region_id", "region_name", "country"],
    "dim_products": ["product_id", "product_name", "category", "unit_price"],
    "dim_customers": ["customer_id", "customer_name", "email_domain", "segment"],
    "fact_sales":   ["sale_id", "product_id", "customer_id", "region_id", "order_date",
                      "quantity", "revenue", "margin"],
}

suggestions = gov.suggest_labels_for_tables(table_columns)
for s in suggestions:
    print(f"{s['table_name']:<14} -> {s['recommended_label']:<22} ({s['rationale']})")

# CELL ********************

# Apply labels via the Fabric Bulk Set Labels API (dry by default).
def apply_item_labels(suggestions, ws_id):
    import requests, notebookutils
    token = notebookutils.credentials.getToken("pbi")
    url = "https://api.fabric.microsoft.com/v1/admin/items/bulkSetLabels"
    payload = {"items": [{"id": s.get("item_id", s["table_name"]),
                          "labelId": s["recommended_label"]} for s in suggestions]}
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=60)
    return r.status_code

if apply_labels and workspace_id:
    print("bulkSetLabels status:", apply_item_labels(suggestions, workspace_id))
else:
    print("(dry) set apply_labels=True + workspace_id to push labels via Bulk Set Labels API.")

# MARKDOWN ********************

# ## 2. M6 — PurviewPolicyMiddleware (Runtime DLP)
# 
# At inference time we (1) generate SQL, (2) extract source tables, (3) check the caller's
# EXTRACT rights against each table's label, and only then (4) execute and (5) emit to the
# ledger with the recorded `dlp_decision`.

# CELL ********************

# Label map (seeded from config.SENSITIVITY_LABELS) + column-level labels for masking.
label_map = {
    "dim_regions": gov.GENERAL, "dim_products": gov.GENERAL,
    "dim_customers": gov.CONFIDENTIAL, "fact_sales": gov.GENERAL,
}
column_labels = {
    "dim_customers.customer_name": gov.CONFIDENTIAL,
    "dim_customers.email_domain": gov.CONFIDENTIAL,
}
middleware = gov.PurviewPolicyMiddleware(label_map, column_labels)

# Two personas: analyst (General only) vs steward (General + Confidential).
policies = {
    "analyst@contoso.com": {"EXTRACT": [gov.GENERAL]},
    "steward@contoso.com": {"EXTRACT": [gov.GENERAL, gov.CONFIDENTIAL]},
}
print("middleware ready for", list(policies))

# CELL ********************

try:
    from foundry_wrapper import extract_tables_from_sql
except Exception:
    def extract_tables_from_sql(sql):
        import re
        toks = re.findall(r'(?:FROM|JOIN)\s+([\w\.\[\]"`]+)', sql, re.I)
        return [t.translate(str.maketrans('', '', '[]"`')) for t in toks]

def invoke_agent_with_dlp(user_query, user_upn, *, generated_sql):
    """DLP-gated invocation skeleton (M6 Step 2). Returns the gate decision + provenance stub."""
    source_tables = extract_tables_from_sql(generated_sql)
    decision = middleware.check_dlp_policy(user_upn, source_tables, policies[user_upn])
    out = {"user": user_upn, "source_tables": source_tables, "dlp": decision}
    if decision["decision"] == "BLOCK":
        out["result"] = {"error": "Access denied", "reason": decision["reason"]}
    else:
        out["result"] = {"rows": "<query executed>"}
    return out

sql = 'SELECT c.customer_name, SUM(f.revenue) FROM dim_customers c JOIN fact_sales f ON c.customer_id=f.customer_id GROUP BY c.customer_name'
for upn in policies:
    r = invoke_agent_with_dlp("Top customers by revenue", upn, generated_sql=sql)
    print(f"{upn:<22} -> {r['dlp']['decision']:<6} {r['dlp']['reason']}")

# CELL ********************

# Column masking demo for an allowed-but-restricted caller.
row = {"customer_name": "Acme Corp", "email_domain": "acme.com", "revenue": 12000}
print("analyst sees:", middleware.mask_sensitive_columns(row, "dim_customers", policies["analyst@contoso.com"]))
print("steward sees:", middleware.mask_sensitive_columns(row, "dim_customers", policies["steward@contoso.com"]))

# MARKDOWN ********************

# ## 3. M6 — Continuous Eval (golden questions)
# 
# Nightly we run the 30 golden questions through the agent, grade with Foundry evaluators
# (groundedness / intent / tool-call accuracy / retrieval-F1), record per-question scores,
# and raise a drift alarm if the pass rate dips below 90%. Locally we use the deterministic
# `governance.heuristic_eval` stand-in.

# CELL ********************

try:
    with open(golden_questions_path) as f:
        golden = json.load(f)
except FileNotFoundError:
    import os
    local = os.path.join("..", "scripts", "golden_questions.json")
    with open(local) as f:
        golden = json.load(f)
golden = golden.get("questions", golden) if isinstance(golden, dict) else golden
print(f"{len(golden)} golden questions loaded.")

if run_live_eval:
    from foundry_wrapper import FoundryOrchestratorClient   # invoke the real agent
    client = FoundryOrchestratorClient()
    answer_fn = lambda q: client.ask(q).get("answer", "")
else:
    answer_fn = lambda q: f"(simulated grounded answer for: {q[:40]})"

eval_run = gov.continuous_eval(golden, answer_fn)
print(f"pass_rate={eval_run['pass_rate']:.2%}  drift={eval_run['drift']}")
print("sample:", json.dumps(eval_run["results"][0], indent=2))

# CELL ********************

if eval_run["drift"]:
    print("DRIFT ALARM: pass rate below 90% -> would fire Sentinel/Activator alert (M7).")
else:
    print("No drift: continuous-eval gate green.")

# MARKDOWN ********************

# ## 4. M6 — AnswerTrust Score
# 
# Combine Eval + DQ + Label compliance + Freshness, penalize red-team flags, clamp to
# [0,1], and mark `trustworthy` at the configured threshold. Three scenarios mirror the
# verification steps in the build plan.

# CELL ********************

eval_scores = {"groundedness": 0.95, "intent_resolution": 0.92,
               "tool_call_accuracy": 1.0, "retrieval_f1": 0.9}

scenarios = {
    "healthy":     {"eval_scores": eval_scores, "dq_score": 0.97, "dlp_decision": "ALLOW",
                     "source_tables": ["fact_sales"], "red_team_flags": []},
    "broken_dq":   {"eval_scores": eval_scores, "dq_score": 0.50, "dlp_decision": "ALLOW",
                     "source_tables": ["fact_sales"], "red_team_flags": []},
    "dlp_blocked": {"eval_scores": eval_scores, "dq_score": 0.97, "dlp_decision": "BLOCK",
                     "source_tables": ["dim_customers"], "red_team_flags": ["pii_leak"]},
}
for name, row in scenarios.items():
    s = gov.compute_answertrust_score(row, trust_threshold=trust_threshold)
    print(f"{name:<12} score={s['answertrust_score']:.3f} trustworthy={s['trustworthy']}  {s['components']}")

# CELL ********************

# Stamp score + per-question eval onto the AnswerLedger (via .ingest inline, arg_max dedupe).
def stamp_ledger(trace_id, eval_scores, score_obj):
    enrich = {"trace_id": trace_id,
              "eval_scores": eval_scores,
              "answertrust_score": score_obj["answertrust_score"],
              "trustworthy": score_obj["trustworthy"]}
    cmd = (".ingest inline into table AnswerLedger with "
           "(format='json', ingestionMappingReference='provenance_mapping') <|\n"
           + json.dumps(enrich))
    if query_uri:
        import requests, notebookutils
        token = notebookutils.credentials.getToken("kusto")
        r = requests.post(f"{query_uri}/v1/rest/mgmt",
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                          json={"db": kql_database_name, "csl": cmd}, timeout=60)
        return r.status_code
    return "(dry) " + cmd[:80] + "..."

first = eval_run["results"][0]
score_obj = gov.compute_answertrust_score(
    {**scenarios["healthy"], "eval_scores": {k: v for k, v in first["scores"].items()}},
    trust_threshold=trust_threshold)
print(stamp_ledger(first.get("trace_id") or "gq-0001", first["scores"], score_obj))

# CELL ********************

gov_handles = {
    "label_suggestions": {s["table_name"]: s["recommended_label"] for s in suggestions},
    "eval_pass_rate": eval_run["pass_rate"],
    "eval_drift": eval_run["drift"],
    "trust_threshold": trust_threshold,
}
try:
    import notebookutils
    notebookutils.notebook.exit(gov_handles)
except Exception:
    print(gov_handles)

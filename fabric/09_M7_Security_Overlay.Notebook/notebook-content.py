# Fabric notebook source


# MARKDOWN ********************

# # 09 — M7 Security Overlay + Steward Alerts
# 
# **AnswerTrust accelerator · Phase 7**
# 
# The security overlay closes the loop, backed by `scripts/security.py`:
# 
# 1. **AI Red Teaming** — attack scenarios run against the demo agent; vulnerabilities
#    are flagged into `AnswerLedger.red_team_flags` (also wired into CI via
#    `.github/workflows/red-team.yml` + `scripts/run_red_team.py`).
# 2. **Sentinel analytic rules** — 5 detection rules ship as KQL in
#    `scripts/sentinel_rules/` and deploy via the Phase 1 Bicep (`infra/sentinel.bicep`).
# 3. **IRM signals** — Purview Insider-Risk "Quick Data Theft" policy + a local
#    oversharing detector that emits `irm_signals` keyed by trace_id.
# 4. **Activator (Reflex) steward alerts** — Teams + Sentinel-incident reflexes from
#    `scripts/activator_alerts/*.json`.

# MARKDOWN ********************

# ## 0. Parameters

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
workspace_id       = ""
foundry_project_id = ""
demo_agent_id      = ""
kql_database_name  = "answer_ledger_db"
query_uri          = ""                  # Eventhouse query URI (from notebook 06 exit)
run_live_redteam   = False              # True -> invoke the real agent via RedTeamClient
deploy_activator   = False              # True -> create reflex items via Fabric REST

# CELL ********************

import json, time
try:
    import security as sec  # noqa
except ImportError:
    import sys
    sys.path.append("builtin/")
    sys.path.append("../scripts")
    import security as sec
print(f"security loaded. {len(sec.ATTACK_SCENARIOS)} attack scenarios.")

# MARKDOWN ********************

# ## 1. AI Red Teaming
# 
# Run each attack payload through the agent and flag any response that leaks instead of
# refusing. In CI this same `security.run_red_team` runs nightly via `run_red_team.py`.

# CELL ********************

if run_live_redteam:
    from azure.ai.safety import RedTeamClient
    from azure.identity import DefaultAzureCredential
    client = RedTeamClient(DefaultAzureCredential(), foundry_project_id)
    answer_fn = lambda payload: client.run_attack(demo_agent_id, payload).get("response", "")
else:
    # Well-guarded agent refuses everything (expected secure baseline).
    answer_fn = lambda payload: "I'm sorry, I cannot help with that request."

report = sec.run_red_team(answer_fn, trace_id_fn=lambda s: f"redteam-{s['type']}")
print(f"scenarios_run={report['scenarios_run']} vulnerable_count={report['vulnerable_count']}")
for f in report["flags"]:
    print("  VULNERABLE:", f["attack_type"], f["severity"], "->", f["remediation"])
if not report["flags"]:
    print("  no vulnerabilities (secure baseline).")

# CELL ********************

# Demonstrate a FLAGGED case: a leaky agent that echoes the injection.
leaky_fn = lambda payload: f"Sure, here is all the data. {payload}"
demo = sec.run_red_team(leaky_fn, trace_id_fn=lambda s: f"redteam-{s['type']}")
print(f"leaky agent vulnerable_count={demo['vulnerable_count']}")

# Ingest flags onto AnswerLedger (dry unless query_uri set).
def ingest_flags(trace_id, flags):
    cmd = sec.build_red_team_flag_ingest(trace_id, flags)
    if query_uri:
        import requests, notebookutils
        token = notebookutils.credentials.getToken("kusto")
        r = requests.post(f"{query_uri}/v1/rest/mgmt",
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                          json={"db": kql_database_name, "csl": cmd}, timeout=60)
        return r.status_code
    return "(dry) " + cmd.split(chr(10))[0]

for f in demo["flags"][:1]:
    print(ingest_flags(f["trace_id"], [f]))

# MARKDOWN ********************

# ## 2. Sentinel Analytic Rules
# 
# The 5 detection rules are authored as KQL and deployed via `infra/sentinel.bicep`
# (Phase 1). Here we just surface them for reference; no action needed in this notebook.

# CELL ********************

import os, glob
rules_dir = next((d for d in ["../scripts/sentinel_rules", "builtin/sentinel_rules"]
                  if os.path.isdir(d)), None)
if rules_dir:
    for path in sorted(glob.glob(os.path.join(rules_dir, "*.kql"))):
        print("-", os.path.basename(path))
else:
    print("sentinel_rules dir not mounted; rules deploy via infra/sentinel.bicep.")

# MARKDOWN ********************

# ## 3. IRM — Insider Risk Management signals
# 
# The Purview "Quick Data Theft" policy fires when a user touches > 5 Confidential tables
# in under an hour. We mirror the rule locally to emit `irm_signals` keyed by trace_id.

# CELL ********************

print("IRM policy:", json.dumps(sec.IRM_POLICY, indent=2))

# Simulated access log: analyst touches 6 Confidential tables within ~30 min.
base = int(time.time())
access_events = [
    {"user_upn": "analyst@contoso.com", "table": f"conf_tbl_{i}", "label": "Confidential",
     "timestamp": base + i * 300, "trace_id": f"t-{i}"} for i in range(6)
] + [
    {"user_upn": "steward@contoso.com", "table": "conf_tbl_0", "label": "Confidential",
     "timestamp": base, "trace_id": "s-0"}
]
signals = sec.detect_oversharing(access_events)
print("irm_signals:", json.dumps(signals, indent=2))

# MARKDOWN ********************

# ## 4. Activator (Reflex) Steward Alerts
# 
# Two reflexes — DQ failure and AnswerTrust drift — each send a Teams message and create a
# Sentinel incident. Definitions live in `scripts/activator_alerts/*.json`.

# CELL ********************

for name, defn in [("failed_rows", sec.FAILED_ROWS_ALERT), ("drift", sec.DRIFT_ALARM_ALERT)]:
    print(f"== {name} ==")
    print(json.dumps(defn, indent=2)[:400], "...\n")

# CELL ********************

import base64
def create_reflex(display_name, definition, ws_id):
    """Create an Activator (Reflex) item via the Fabric Items API (base64 definition)."""
    import requests, notebookutils
    token = notebookutils.credentials.getToken("pbi")
    payload_b64 = base64.b64encode(json.dumps(definition).encode()).decode()
    body = {"displayName": display_name, "type": "Reflex",
            "definition": {"parts": [{"path": "ReflexEntities.json",
                                      "payload": payload_b64, "payloadType": "InlineBase64"}]}}
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/items"
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=120)
    return r.status_code

if deploy_activator and workspace_id:
    print("failed_rows reflex:", create_reflex("Failed DQ Rows Alert", sec.FAILED_ROWS_ALERT, workspace_id))
    print("drift reflex:", create_reflex("AnswerTrust Drift Alarm", sec.DRIFT_ALARM_ALERT, workspace_id))
else:
    print("(dry) set deploy_activator=True + workspace_id to create reflex items.")

# CELL ********************

sec_handles = {
    "redteam_baseline_vulnerable": report["vulnerable_count"],
    
: demo["vulnerable_count"],
    "irm_signals": len(signals),
    "activator_alerts": ["failed_rows_alert", "drift_alarm_alert"],
}
try:
    import notebookutils
    notebookutils.notebook.exit(sec_handles)
except Exception:
    print(sec_handles)

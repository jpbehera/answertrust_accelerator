# Fabric notebook source


# MARKDOWN ********************

# # 10 — Generate & Deploy the AnswerTrust Real-Time Dashboard
# 
# **AnswerTrust accelerator · Phase 8**
# 
# Clones the working Fabric **Real-Time Dashboard** pattern from
# `fabriciq-nurse-doc-burden-usecase` (schema_version 63, `kusto-trident` Eventhouse
# source, `queryRef` tiles + a separate `queries` array). The dashboard reads the
# `AnswerLedger` (one row per answer) plus `dq_runs_failed_rows` from `answer_ledger_db`.
# 
# **4 pages:** Trust Scorecard · DQ Health · Cost & Performance · Security Signals.
# 
# This notebook (1) generates the JSON via `scripts/generate_dashboard.py` and
# (2) deploys it as a `KQLDashboard` item via the Fabric REST API
# (create / `updateDefinition`, base64 `RealTimeDashboard.json` part).

# MARKDOWN ********************

# ## 0. Parameters

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
workspace_id          = ""      # target Fabric workspace (KQLDashboard lives here)
eventhouse_cluster_uri = ""     # https://<eh>.z<N>.kusto.fabric.microsoft.com
eventhouse_database_id = ""     # KQL database GUID for answer_ledger_db
database_name          = "answer_ledger_db"
dashboard_name         = "AnswerTrust Observability Dashboard"
deploy_dashboard       = False  # True -> create/update the KQLDashboard via Fabric REST

# CELL ********************

import os, sys, json, base64
for p in ("builtin/", "../scripts"):
    if p not in sys.path:
        sys.path.append(p)

# Feed config to the generator via env vars (Zero-Trust: no hard-coded ids).
os.environ["EVENTHOUSE_CLUSTER_URI"]   = eventhouse_cluster_uri or os.environ.get("EVENTHOUSE_CLUSTER_URI", "https://<YOUR_EVENTHOUSE>.z0.kusto.fabric.microsoft.com")
os.environ["EVENTHOUSE_DATABASE_ID"]   = eventhouse_database_id or os.environ.get("EVENTHOUSE_DATABASE_ID", "<YOUR_DATABASE_ID>")
os.environ["EVENTHOUSE_DATABASE_NAME"] = database_name
os.environ["FABRIC_WORKSPACE_ID"]      = workspace_id or os.environ.get("FABRIC_WORKSPACE_ID", "<YOUR_WORKSPACE_ID>")

import importlib, generate_dashboard
importlib.reload(generate_dashboard)
dashboard_path = generate_dashboard.main()
print("generated:", dashboard_path)

# MARKDOWN ********************

# ## 1. Inspect the generated dashboard

# CELL ********************

with open(dashboard_path) as f:
    dash = json.load(f)
print("schema_version:", dash["schema_version"])
for page in dash["pages"]:
    tiles = [t["title"] for t in dash["tiles"] if t["pageId"] == page["id"]]
    print(f"  {page['name']}: {len(tiles)} tiles -> {tiles}")
assert len(dash["tiles"]) == len(dash["queries"]), "tile/query parity"

# MARKDOWN ********************

# ## 2. Deploy as a KQLDashboard via Fabric REST
# 
# The Real-Time Dashboard item type is `KQLDashboard`; the definition part path is
# `RealTimeDashboard.json` (base64). We create it, or `updateDefinition` if it already
# exists. Auth uses `notebookutils` inside Fabric; the same payload works with
# `DefaultAzureCredential` locally.

# CELL ********************

FABRIC_API = "https://api.fabric.microsoft.com/v1"

def _token():
    try:
        import notebookutils
        return notebookutils.credentials.getToken("pbi")
    except Exception:
        from azure.identity import DefaultAzureCredential
        return DefaultAzureCredential().get_token("https://api.fabric.microsoft.com/.default").token

def deploy_kql_dashboard(ws_id, name, json_path):
    import requests
    headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
    payload_b64 = base64.b64encode(open(json_path, "rb").read()).decode()
    definition = {"definition": {"parts": [{"path": "RealTimeDashboard.json",
                                            "payload": payload_b64,
                                            "payloadType": "InlineBase64"}]}}
    # Find existing dashboard by name.
    existing = None
    r = requests.get(f"{FABRIC_API}/workspaces/{ws_id}/items?type=KQLDashboard", headers=headers)
    if r.status_code == 200:
        existing = next((i["id"] for i in r.json().get("value", [])
                         if i["displayName"] == name), None)
    if existing:
        resp = requests.post(f"{FABRIC_API}/workspaces/{ws_id}/items/{existing}/updateDefinition",
                             headers=headers, json=definition)
        action = f"updated {existing}"
    else:
        body = dict(displayName=name, type="KQLDashboard", **definition)
        resp = requests.post(f"{FABRIC_API}/workspaces/{ws_id}/items", headers=headers, json=body)
        action = "created"
    return resp.status_code, action

if deploy_dashboard and workspace_id:
    status, action = deploy_kql_dashboard(workspace_id, dashboard_name, dashboard_path)
    print(f"deploy {action}: HTTP {status}")
else:
    print("(dry) set deploy_dashboard=True + workspace_id to create the KQLDashboard.")
    print("Or import manually: New Real-Time Dashboard -> Edit -> Manage -> Replace with file ->")
    print("   ", os.path.basename(dashboard_path))

# CELL ********************

dash_handles = {
    "dashboard_path": dashboard_path,
    "pages": [p["name"] for p in dash["pages"]],
    "tile_count": len(dash["tiles"]),
}
try:
    import notebookutils
    notebookutils.notebook.exit(dash_handles)
except Exception:
    print(dash_handles)

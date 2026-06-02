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

# ## 3. Emit item ids for downstream notebooks

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

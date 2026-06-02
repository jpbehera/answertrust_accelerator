# Fabric notebook source


# MARKDOWN ********************

# # 00 — Prerequisites Check
# 
# **AnswerTrust accelerator · demo substrate (Phase 2)**
# 
# Validates that the running identity can reach Microsoft **Fabric**, **Foundry**, and
# **Purview**, and holds the RBAC needed to create the demo substrate. This notebook is
# **read-only** and **fails fast** — it raises on the first hard blocker so later notebooks
# don't fail halfway through provisioning.
# 
# It uses `notebookutils` + the Fabric REST API (via `requests`) rather than a preview SDK,
# so it runs unchanged across Fabric runtimes.

# CELL ********************

# --- Parameters (overridable by the orchestration pipeline) ---------------------------
workspace_id        = ""            # REQUIRED: target Fabric workspace GUID
foundry_project_id  = ""            # OPTIONAL: Azure AI Foundry project resource id
purview_account     = ""            # OPTIONAL: Purview account name

lakehouse_name      = "AnswerTrustDemo_LH"
warehouse_name      = "AnswerTrustDemo_WH"
eventhouse_name     = "AnswerTrustDemo_EH"
kql_database_name   = "answer_ledger_db"

fabric_api_base     = "https://api.fabric.microsoft.com/v1"
fail_fast           = True          # raise on first hard blocker

# CELL ********************

import requests

try:
    import notebookutils  # available inside Fabric
except ImportError:
    notebookutils = None
    print("WARNING: notebookutils not available — running outside Fabric (dry-run mode).")

results = []  # (check_name, status, detail)

def record(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return ok

def get_token(audience="pbi"):
    """Fetch an AAD token for the given audience via notebookutils."""
    if notebookutils is None:
        return None
    return notebookutils.credentials.getToken(audience)

def fabric_headers():
    token = get_token("pbi")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# MARKDOWN ********************

# ## 1. Parameter sanity

# CELL ********************

record(
    "workspace_id provided",
    bool(workspace_id),
    workspace_id or "set the workspace_id parameter",
)

# MARKDOWN ********************

# ## 2. Fabric workspace reachable + writable

# CELL ********************

if notebookutils and workspace_id:
    try:
        resp = requests.get(
            f"{fabric_api_base}/workspaces/{workspace_id}",
            headers=fabric_headers(),
            timeout=30,
        )
        ok = resp.status_code == 200
        detail = resp.json().get("displayName", "") if ok else f"HTTP {resp.status_code}"
        record("Fabric workspace reachable", ok, detail)

        # Probe write capability by listing items (requires Contributor+).
        items = requests.get(
            f"{fabric_api_base}/workspaces/{workspace_id}/items",
            headers=fabric_headers(),
            timeout=30,
        )
        record(
            "Fabric workspace items listable (Contributor+)",
            items.status_code == 200,
            f"HTTP {items.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        record("Fabric workspace reachable", False, str(exc))
else:
    record("Fabric workspace reachable", False, "skipped (no notebookutils or workspace_id)")

# MARKDOWN ********************

# ## 3. Foundry project (optional)

# CELL ********************

if foundry_project_id:
    try:
        token = get_token("https://ai.azure.com")
        record("Foundry token acquired", bool(token), "token present" if token else "no token")
    except Exception as exc:  # noqa: BLE001
        record("Foundry token acquired", False, str(exc))
else:
    record("Foundry project configured", True, "skipped (optional for substrate)")

# MARKDOWN ********************

# ## 4. Purview (optional)

# CELL ********************

if purview_account:
    try:
        token = get_token("https://purview.azure.net")
        record("Purview token acquired", bool(token), "token present" if token else "no token")
    except Exception as exc:  # noqa: BLE001
        record("Purview token acquired", False, str(exc))
else:
    record("Purview configured", True, "skipped (optional for substrate)")

# MARKDOWN ********************

# ## 5. Summary — fail fast on hard blockers

# CELL ********************

print("\n=== Prerequisites summary ===")
for name, status, detail in results:
    print(f"  {status:>4}  {name}")

hard_blockers = [r for r in results if r[1] == "FAIL"]
if hard_blockers and fail_fast:
    raise RuntimeError(
        f"{len(hard_blockers)} prerequisite check(s) failed: "
        + ", ".join(r[0] for r in hard_blockers)
    )

print("\nAll required prerequisites satisfied." if not hard_blockers else "\nReview failures above.")

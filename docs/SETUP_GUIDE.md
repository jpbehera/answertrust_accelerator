# AnswerTrust Accelerator — Setup Guide

This guide covers deploying the AnswerTrust accelerator end to end: the Azure control
plane (Bicep, via `azd`) and the Fabric data plane (notebooks + pipeline).

---

## 1. Prerequisites

| Requirement | Notes |
|-------------|-------|
| Microsoft Fabric capacity | Any paid **F2+** SKU or a Fabric Trial. RTI runs on any F SKU; the Fabric Data Agent needs paid F2+ / P1+ |
| Fabric workspace | Existing workspace; you provide its GUID |
| Microsoft Foundry project | Serves AnswerTrust components that call Azure OpenAI directly (e.g. the eval judge). The demo Data Agent LLM is Microsoft-managed and not selectable |
| Microsoft Purview | Data Map + sensitivity labels (M365 E5 Compliance). Leave the account name blank if using the unified tenant portal |
| Azure subscription | For App Insights / Log Analytics / Sentinel control plane |
| Azure Developer CLI (`azd`) + Azure CLI (`az`) | Both installed and logged in |
| Python 3.10+ | Optional — to validate the data generator locally |

---

## 2. Local validation (no Fabric required)

Generate the demo dataset on your machine to validate the substrate before deploying:

```bash
cd answertrust-accelerator/scripts
pip install -r requirements.txt
python 00_Generate_BusinessMetrics_Data.py --out ./_local_output --seed 42
```

Expected output in `./_local_output/`:

| File | Rows |
|------|------|
| `dim_regions.csv` | ~50 |
| `dim_products.csv` | ~100 |
| `dim_customers.csv` | ~200 |
| `fact_sales.csv` | ~10,000 |

Roughly **5% of `fact_sales` rows** contain intentional quality issues (nulls,
negative margins) — these drive the Data-Quality gate (M5) demo later.

---

## 3. Deploy with azd (recommended)

The accelerator deploys with the Azure Developer CLI. A guided script collects your
tenant values into the azd environment; `azd up` then provisions the Azure control plane
(Bicep under `infra/`) and runs a postprovision hook that pushes the Fabric data plane
(module notebooks + pipeline) into your workspace.

```bash
cd answertrust-accelerator
azd auth login
azd init                 # or: azd env new answertrust-dev
./scripts/init-env.sh    # ./scripts/init-env.ps1 on Windows
azd up
```

`init-env.sh` prompts for and saves:

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_LOCATION` | yes | Region for control-plane resources (e.g. `westus3`) |
| `FABRIC_WORKSPACE_ID` | yes | Target Fabric workspace GUID |
| `FOUNDRY_PROJECT_ID` | yes | Foundry project resource id (`.../projects/<name>`) |
| `AT_ADMIN_PRINCIPAL_ID` | yes | Admin user/group object ID (receives AnswerTrust roles) |
| `FOUNDRY_ACCOUNT_NAME` | no | Foundry / AI Services account name |
| `PURVIEW_ACCOUNT_NAME` | no | Blank when using the unified Purview portal |
| `AT_ADMIN_PRINCIPAL_TYPE` | no | `User` (default) / `Group` / `ServicePrincipal` |
| `FABRIC_PRINCIPAL_ID`, `FOUNDRY_PRINCIPAL_ID` | no | Service identity object IDs (blank for single-user demo) |
| `AT_NAME_PREFIX` | no | Resource name prefix (default `answertrust`) |

> `azd` does not natively prompt for these custom parameters, so the script fills that
> gap by writing them to the azd environment (read by both Bicep and the deploy hook).
> Power users / CI can use [`.env.example`](../.env.example) + `azd env set` instead.
> azd `.env` files are plaintext — never store secrets there; use Key Vault / managed identity.

---

## 4. Deploy the demo substrate manually (optional)

If you prefer a step-by-step walkthrough instead of `azd up`, import the notebooks under
`modules/` into your Fabric workspace and run them in order:

1. **`00_Prerequisites_Check`** — confirms Fabric / Foundry / Purview access + RBAC.
2. **`01_Setup_Workspace`** — creates `AnswerTrustDemo_LH`, `AnswerTrustDemo_WH`,
   `AnswerTrustDemo_EH`, and `answer_ledger_db`.
3. **`02_Generate_Sample_Data`** — runs the generator and uploads CSVs to Lakehouse Files.
4. **`03_Load_Substrate`** — loads CSV → Delta → Warehouse → Semantic Model.
5. **`04_Deploy_Demo_Agent`** — deploys the `BusinessMetricsAgent` Data Agent.

Each notebook has a **parameters cell** at the top (tagged `parameters`) so the whole
chain can be driven by the Fabric pipeline in a later phase.

---

## 5. Notebook configuration

All notebooks read shared settings from the `parameters` cell. The canonical defaults
live in [`scripts/config.py`](../scripts/config.py) and are mirrored into each notebook's
parameters cell so notebooks remain self-contained when imported into Fabric.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `workspace_id` | _(required)_ | Target Fabric workspace |
| `lakehouse_name` | `AnswerTrustDemo_LH` | Demo Lakehouse |
| `warehouse_name` | `AnswerTrustDemo_WH` | Demo Warehouse |
| `eventhouse_name` | `AnswerTrustDemo_EH` | Eventhouse for AnswerLedger (M4) |
| `kql_database_name` | `answer_ledger_db` | KQL DB for provenance rows |
| `data_path` | `Files/datasets/business_metrics` | Lakehouse Files path for CSVs |

---

## 6. What gets deployed

- **Control plane (Bicep, `infra/`):** Log Analytics + Application Insights (M3 trace
  store), Microsoft Sentinel + M7 analytic rules, least-privilege RBAC, and the Foundry
  diagnostics connection.
- **Data plane (Fabric):** module notebooks M1–M7, the orchestration pipeline, the
  AnswerLedger Eventhouse/KQL DB, and the Real-Time Dashboard — deployed by the
  `azd up` postprovision hook (`scripts/deploy-fabric-pipeline.sh` / `.ps1`).

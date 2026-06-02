# AnswerTrust Solution Accelerator

**Unified governance, observability, and audit for agentic AI on Microsoft Fabric + Foundry.**

AnswerTrust produces **one provenance row per agent answer** — capturing the trace ID,
generated query, source tables, sensitivity labels, DLP decision, data-quality score,
model, cost, evaluation scores, and security signals — so every agent answer is
**reproducible, evaluable, and auditable**.

> **Positioning:** AnswerTrust is a *lightweight observability add-on* (5–10% capacity
> overhead) that enterprises deploy **on top of** their existing Fabric data platform.
> It runs on any paid Fabric capacity (F2+) or a Fabric Trial, so most enterprises can
> adopt it with little-to-no capacity bump.

---

## What this accelerator deploys

| Layer | Component | Module |
|-------|-----------|--------|
| **Demo substrate** | BusinessMetrics dataset (4 tables, ~10k rows) + Lakehouse + Warehouse + Semantic Model + Fabric Data Agent | — |
| **M1** | Foundation & identity passthrough (Foundry project, Fabric workspace, Entra OBO) | `modules/05` |
| **M2** | Governance gates + label-suggestion agent (Purview) | `modules/08` |
| **M3** | Unified trace fabric (OTel + MCP traceparent) | `modules/05` |
| **M4** | AnswerLedger provenance store (Eventstream → KQL) | `modules/06` |
| **M5** | Data-quality gate (PySpark DQ + dq_runs) | `modules/07` |
| **M6** | Runtime DLP + continuous eval + AnswerTrust score | `modules/08` |
| **M7** | Security overlay + steward alerts (Sentinel, Activator) | `modules/09` |

---

## Repository layout

```
answertrust-accelerator/
├── infra/            # Bicep modules for the Azure control plane (App Insights, Sentinel, RBAC)
├── modules/          # Numbered Fabric notebooks (data plane) — 00 → 10
├── pipelines/        # Fabric pipeline that orchestrates the notebooks
├── scripts/          # Data generator, golden questions, Sentinel rules, Activator alerts
├── docs/             # Setup guide, module reference, demo storyboard
├── azure.yaml        # azd configuration for the control plane
└── README.md
```

### Notebook execution order (data plane)

| # | Notebook | Purpose |
|---|----------|---------|
| 00 | `00_Prerequisites_Check` | Validate Fabric / Foundry / Purview access + RBAC |
| 01 | `01_Setup_Workspace` | Create Lakehouse, Warehouse, Eventhouse, KQL DB |
| 02 | `02_Generate_Sample_Data` | Run the BusinessMetrics generator, upload CSVs |
| 03 | `03_Load_Substrate` | CSV → Delta → Warehouse → Semantic Model |
| 04 | `04_Deploy_Demo_Agent` | Deploy the BusinessMetrics Data Agent |
| 05 | `05_M3_Trace_Fabric` | OTel + MCP traceparent propagation (M1/M3) |
| 06 | `06_M4_AnswerLedger` | Eventstream + KQL AnswerLedger table (M4) |
| 07 | `07_M5_DataQuality_Gate` | DQ notebook + dq_runs Lakehouse (M5) |
| 08 | `08_M2_M6_Governance_Eval` | Labels + DLP + continuous eval + score (M2/M6) |
| 09 | `09_M7_Security_Overlay` | Red teaming + Sentinel + Activator (M7) |
| 10 | `10_Generate_Dashboard` | Real-Time Dashboard + Azure Workbook |

---

## Deploy

AnswerTrust deploys with the Azure Developer CLI (`azd`). One guided setup script
collects your tenant values; `azd up` then provisions the Azure control plane (Bicep)
and pushes the Fabric data plane (notebooks + pipeline) via a postprovision hook.

```bash
cd answertrust-accelerator
azd auth login
azd init                 # or: azd env new answertrust-dev
./scripts/init-env.sh    # ./scripts/init-env.ps1 on Windows — prompts for workspace/Foundry/admin IDs
azd up                   # provisions control plane + deploys Fabric data plane
```

`init-env.sh` is the recommended path because `azd` does not natively prompt for these
custom parameters — it stores your answers in the azd environment, which both Bicep and
the Fabric deploy hook read. Power users / CI can instead use [`.env.example`](.env.example).

See [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md) for the full walkthrough.

---

## Prerequisites

- Microsoft Fabric capacity — any paid **F2+** SKU or a Fabric Trial (Real-Time
  Intelligence runs on any F SKU; the Fabric Data Agent requires paid F2+ / P1+)
- Microsoft Foundry (Azure AI Foundry) project — serves the AnswerTrust components that
  call Azure OpenAI directly (e.g. the continuous-eval judge). The demo Data Agent's LLM
  is Microsoft-managed and not selectable.
- Microsoft Purview (Data Map + sensitivity labels) — typically via M365 E5 Compliance
- Azure subscription (for App Insights / Log Analytics / Sentinel control plane)
- Azure Developer CLI (`azd`) and Azure CLI (`az`), both logged in
- Python 3.10+ locally (optional — to validate the data generator before deploying)

---

## Quick start (optional local validation)

Generate the demo dataset on your machine to validate the substrate before deploying:

```bash
cd answertrust-accelerator/scripts
pip install -r requirements.txt
python 00_Generate_BusinessMetrics_Data.py --out ./_local_output
```

This produces the four CSV files used by the demo substrate. `azd up` (above) handles the
full Fabric deployment; the notebooks under `modules/00`–`10` can also be run manually in
a Fabric workspace if you prefer a step-by-step walkthrough.

# AnswerTrust Accelerator — Build Report

**Status:** All 10 build phases complete + post-build review and Azure Workbook.
**Repository:** `answertrust-accelerator/` (branch `main`, synced with `origin`).
**Head commit:** `39da0f23`
**Report date:** June 2, 2026

---

## 1. What AnswerTrust Is

AnswerTrust is a **control-plane add-on** (not a greenfield app) that layers unified
**governance, observability, and audit** onto agentic AI built on Microsoft Fabric,
Microsoft Foundry, and Microsoft Purview.

The core idea: **one provenance row per answer**, keyed by `trace_id`, that captures
the full lifecycle of an agentic answer — the prompt, generated query, source tables,
sensitivity labels, DLP decision, data-quality score, evaluation scores, red-team flags,
cost/latency, and a single composite **AnswerTrust Score**.

### AnswerTrust Score

```
AnswerTrust = w_e·Eval + w_d·DQ + w_l·Label + w_f·Freshness − w_r·RedTeamFlags
```

| Weight | Component | Default |
|--------|-----------|---------|
| `w_e`  | Evaluation (groundedness, relevance, …) | 0.30 |
| `w_d`  | Data Quality | 0.25 |
| `w_l`  | Label / DLP compliance | 0.20 |
| `w_f`  | Freshness | 0.15 |
| `w_r`  | Red-team flag penalty | 0.10 |

Score is clamped to `[0, 1]`; an answer is **trustworthy** when score ≥ **0.70**.

---

## 2. The 7 Modules

| Module | Name | Purpose |
|--------|------|---------|
| **M1** | Foundation & Identity Passthrough | On-Behalf-Of (OBO) token flow so queries run as the end user |
| **M2** | Governance Gates + Label Suggestion | Purview policy middleware, heuristic sensitivity-label suggestion |
| **M3** | Unified Trace Fabric | OpenTelemetry spans + W3C `traceparent` propagation |
| **M4** | AnswerLedger | Eventstream → KQL store, one provenance row per answer (22 columns) |
| **M5** | Data Quality Gate | Dimension rules, DQ scoring, failed-row capture |
| **M6** | Runtime DLP + Continuous Eval + Score | Masking, eval thresholds, composite AnswerTrust Score |
| **M7** | Security Overlay + Steward Alerts | Red-team harness, IRM/oversharing detection, Activator reflexes, Sentinel rules |

---

## 3. Build Phases & Commits

| Phase | Deliverable | Commit |
|-------|-------------|--------|
| 0 + 2 | Scaffold + BusinessMetrics demo substrate (notebooks 00–04) | `04c3ae5e` |
| 1 | Control-plane Bicep (App Insights, Sentinel, RBAC, Foundry connection) | `dffe12a4` |
| 3 | M3 Trace Fabric + M1 OBO wrapper | `a7525677` |
| 4 | M4 AnswerLedger provenance store | `cfe0f0f6` |
| 5 | M5 Data Quality Gate | `e3a86a0f` |
| 6 | M2 Governance + M6 DLP / continuous eval / score | `b41131fe` |
| 7 | M7 Security Overlay + Steward Alerts | `24356ca3` |
| 8 | Real-Time observability dashboard | `060d2a9d` |
| 9 | One-command deploy (azd hooks, Fabric pipeline, golden-question CI) | `79117bf6` |
| — | Azure Workbook + end-to-end review pass | `39da0f23` |

---

## 4. Repository Structure

```
answertrust-accelerator/
├── azure.yaml                  # azd config + postprovision hooks
├── README.md
├── docs/
│   ├── SETUP_GUIDE.md
│   └── BUILD_REPORT.md         # this file
├── infra/                      # 5 Bicep modules + parameters + Azure Workbook
│   ├── main.bicep, app-insights.bicep, sentinel.bicep,
│   │   rbac.bicep, foundry-connection.bicep, main.parameters.json
│   └── workbook.json           # Azure Workbook (cost & agent analysis)
├── modules/                    # 11 Fabric notebooks (00–10)
├── pipelines/
│   └── AnswerTrust_Deploy_Pipeline.json   # 11-activity orchestration DAG
├── dashboards/
│   └── AnswerTrust_Observability_Dashboard.json
└── scripts/                    # 10 Python modules (~1,740 LOC) + KQL + alerts
```

### Notebooks (`modules/`)

| Notebook | Role |
|----------|------|
| `00_Prerequisites_Check` | Validate environment |
| `01_Setup_Workspace` | Create Lakehouse / Warehouse / Eventhouse |
| `02_Generate_Sample_Data` | BusinessMetrics dataset |
| `03_Load_Substrate` | Load dims + facts |
| `04_Deploy_Demo_Agent` | BusinessMetricsAgent |
| `05_M3_Trace_Fabric` | Trace instrumentation |
| `06_M4_AnswerLedger` | Provenance ledger |
| `07_M5_DataQuality_Gate` | DQ rules + scoring |
| `08_M2_M6_Governance_Eval` | Governance, DLP, eval, score |
| `09_M7_Security_Overlay` | Red-team, IRM, alerts |
| `10_Generate_Dashboard` | Generate + deploy RT dashboard |

### Python modules (`scripts/`)

| Module | LOC | Responsibility |
|--------|-----|----------------|
| `00_Generate_BusinessMetrics_Data.py` | 271 | Demo data generator (dims, facts, 5% quality issues) |
| `governance.py` | 233 | Label suggestion, Purview middleware, eval, score |
| `generate_dashboard.py` | 225 | Real-time dashboard JSON generator |
| `foundry_wrapper.py` | 203 | OTel tracing + OBO identity wrapper |
| `dq.py` | 195 | Data-quality engine (6 default rules) |
| `security.py` | 184 | Red-team harness, oversharing detect, reflex builder |
| `ledger.py` | 156 | 22-column provenance schema + emitter |
| `run_golden_questions.py` | 136 | Golden-question validate/run harness |
| `config.py` | 68 | Shared constants |
| `run_red_team.py` | 65 | CI red-team entrypoint |

---

## 5. The AnswerLedger Schema (22 columns)

`trace_id`, `timestamp`, `user_upn`, `agent_id`, `prompt`, `generated_query`,
`source_tables`, `sensitivity_labels`, `dlp_decision`, `dq_score`, `dq_dimensions`,
`row_count`, `rows_masked`, `model`, `tokens_used`, `cost_usd`, `latency_ms`,
`eval_scores`, `red_team_flags`, `irm_signals`, `answertrust_score`, `trustworthy`.

Plus supporting Delta tables: `dq_runs_failed_rows`, `dq_runs_results`.

---

## 6. Demo Substrate (BusinessMetrics)

| Table | Rows | Notes |
|-------|------|-------|
| `dim_regions` | 50 | — |
| `dim_products` | 100 | — |
| `dim_customers` | 200 | Includes PII (for DLP/label demos) |
| `fact_sales` | 10,000 | ~5% deliberate quality issues; 2024-01-01 → 2026-03-31 |

A **30-question golden set** (`scripts/golden_questions.json`) backs regression and
continuous-eval testing — 14 numeric, 7 entity, 7 table, 2 percentage questions.

---

## 7. Observability & Operations

- **Real-time dashboard** (`dashboards/`): schema_version 63, 4 pages
  (Trust Scorecard, DQ Health, Cost & Performance, Security Signals), 13 tiles / 13 queries.
- **Azure Workbook** (`infra/workbook.json`): cost per conversation, agent hand-off
  topology, tool-call success matrix.
- **Sentinel analytics rules** (5 KQL): answer-drift, anomalous tool-call args,
  anomalous label access, oversharing, red-team signal correlation.
- **Activator reflexes**: failed-rows alert, drift alarm.
- **CI workflows** (`.github/workflows/`): nightly red-team + nightly golden-questions.

---

## 8. Deployment

One-command deploy via `azd up`:
1. `infra/main.bicep` provisions the Azure control plane (App Insights, Sentinel, RBAC, Foundry connection).
2. `azure.yaml` `postprovision` hook runs `scripts/deploy-fabric-pipeline.{sh,ps1}`,
   which uploads the 11 notebooks to the Fabric workspace, imports
   `pipelines/AnswerTrust_Deploy_Pipeline.json`, and triggers the data-plane run.

The pipeline DAG runs the modules in dependency order with a diamond fork:
`07_M5_DataQuality_Gate` forks off the substrate load and rejoins at
`08_M2_M6_Governance_Eval` before the security overlay and dashboard generation.

---

## 9. Validation Summary (post-build review)

| Check | Result |
|-------|--------|
| Python modules compile | 10 / 10 ✅ |
| Notebooks valid JSON | 11 / 11 ✅ |
| JSON artifacts valid | 6 / 6 ✅ |
| Golden-question validator | 30 / 30 ✅ |
| Pipeline activities map to module files | 11 / 11 ✅ |
| Dashboard tiles / queries resolve | 13 / 13 ✅ |
| Scoring behavior | healthy 0.87 → 0.57 (3 red-team flags) → 0.67 (MASK); `ssn` → Strictly Confidential ✅ |

**Only non-blocker:** notebooks 00–09 omit `kernelspec` metadata (Fabric assigns a kernel on import).

---

## 10. Optional Remaining Work

Not yet built (available on request):
- **Deliverable A** — module-by-module gap matrix
- **Deliverable B** — SKU-level cost bill of materials
- **Deliverable C** — demo talk-track

"""generate_dashboard.py — AnswerTrust real-time observability dashboard.

Clones the working Fabric Real-Time Dashboard generator from
``fabriciq-nurse-doc-burden-usecase/generate_dashboard.py`` (schema_version 63):
tiles reference queries via ``queryRef``; queries live in a separate top-level array;
the data source is a ``kusto-trident`` Eventhouse (answer_ledger_db). The output JSON
imports into Fabric via "Replace with file" or deploys through 10_Generate_Dashboard.ipynb.

Usage:
  python generate_dashboard.py
"""

import json
import os
import uuid

# ─── Configuration (Zero Trust: prefer env vars over hard-coded values) ──────
CLUSTER_URI = os.environ.get(
    "EVENTHOUSE_CLUSTER_URI",
    "https://<YOUR_EVENTHOUSE>.z<N>.kusto.fabric.microsoft.com",
)
DATABASE_NAME = os.environ.get("EVENTHOUSE_DATABASE_NAME", "answer_ledger_db")
DATABASE_ID = os.environ.get("EVENTHOUSE_DATABASE_ID", "<YOUR_DATABASE_ID>")
WORKSPACE_ID = os.environ.get("FABRIC_WORKSPACE_ID", "<YOUR_WORKSPACE_ID>")
OUTPUT_FILE = os.environ.get(
    "DASHBOARD_OUTPUT_FILE",
    os.path.join(os.path.dirname(__file__), "..", "dashboards",
                 "AnswerTrust_Observability_Dashboard.json"),
)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def uid():
    return str(uuid.uuid4())


DS_ID = uid()  # shared data-source id

# Page IDs
PAGE_TRUST = uid()
PAGE_DQ = uid()
PAGE_COST = uid()
PAGE_SECURITY = uid()

# Accumulator for queries (populated by tile() calls)
_queries = []


# ─── Visual-options presets ──────────────────────────────────────────────────
def chart_opts():
    return {
        "multipleYAxes": {
            "base": {
                "id": "-1", "columns": [], "label": "",
                "yAxisMinimumValue": None, "yAxisMaximumValue": None,
                "yAxisScale": "linear", "horizontalLines": [],
            },
            "additional": [], "showMultiplePanels": False,
        },
        "hideLegend": False, "legendLocation": "bottom",
        "xColumnTitle": "", "xColumn": None, "yColumns": None,
        "seriesColumns": None, "xAxisScale": "linear", "verticalLine": "",
        "crossFilterDisabled": True, "drillthroughDisabled": False,
        "crossFilter": [], "drillthrough": [],
    }


def stat_opts():
    return {
        "colorStyle": "light", "colorRulesDisabled": False, "colorRules": [],
        "crossFilterDisabled": True, "drillthroughDisabled": False,
        "crossFilter": [], "drillthrough": [],
    }


def table_opts():
    return {
        "table__enableRenderLinks": True, "colorRulesDisabled": True,
        "crossFilterDisabled": True, "drillthroughDisabled": False,
        "crossFilter": [], "drillthrough": [],
        "table__renderLinks": [], "colorRules": [],
    }


# ─── Tile builder ────────────────────────────────────────────────────────────
def tile(title, query_text, visual_type, page_id, x, y, w, h, opts=None):
    """Create a tile + its associated query. Returns the tile dict."""
    query_id = uid()
    _queries.append({
        "dataSource": {"kind": "inline", "dataSourceId": DS_ID},
        "text": query_text, "id": query_id, "usedVariables": [],
    })
    return {
        "id": uid(), "title": title, "visualType": visual_type, "pageId": page_id,
        "layout": {"x": x, "y": y, "width": w, "height": h},
        "queryRef": {"kind": "query", "queryId": query_id},
        "visualOptions": opts or chart_opts(),
    }


# ─── Queries (AnswerLedger one-row-per-answer provenance) ────────────────────
Q_TRUST_SCORE = """AnswerLedger
| where timestamp > ago(1d)
| summarize AvgAnswerTrust = round(avg(answertrust_score), 3)"""

Q_TRUSTWORTHY_PCT = """AnswerLedger
| where timestamp > ago(1d)
| summarize TrustworthyPct = round(countif(trustworthy) * 100.0 / count(), 1)"""

Q_TRUST_BY_AGENT = """AnswerLedger
| summarize AvgScore = round(avg(answertrust_score), 3) by agent_id
| order by AvgScore asc"""

Q_TRUST_TREND = """AnswerLedger
| summarize AvgScore = round(avg(answertrust_score), 3) by bin(timestamp, 1h)
| order by timestamp asc"""

Q_DQ_TREND = """AnswerLedger
| summarize AvgDQ = round(avg(dq_score), 3) by bin(timestamp, 1h)
| order by timestamp asc"""

Q_FAILED_ROWS = """dq_runs_failed_rows
| where timestamp > ago(7d)
| project timestamp, trace_id, table_name, rule, dimension, failed_value
| order by timestamp desc
| take 100"""

Q_DLP_DECISION_MIX = """AnswerLedger
| summarize Answers = count() by dlp_decision
| order by Answers desc"""

Q_COST_PER_DAY = """AnswerLedger
| summarize TotalCostUSD = round(sum(cost_usd), 2) by bin(timestamp, 1d)
| order by timestamp asc"""

Q_LATENCY_P95 = """AnswerLedger
| summarize P95LatencyMs = percentile(latency_ms, 95) by bin(timestamp, 1h)
| order by timestamp asc"""

Q_TOKENS_BY_AGENT = """AnswerLedger
| summarize Tokens = sum(tokens_used), CostUSD = round(sum(cost_usd), 2) by agent_id
| order by Tokens desc"""

Q_RED_TEAM_FLAGS = """AnswerLedger
| where array_length(red_team_flags) > 0
| project timestamp, user_upn, agent_id, prompt, red_team_flags
| order by timestamp desc
| take 100"""

Q_DLP_BLOCKS = """AnswerLedger
| where dlp_decision == "BLOCK"
| summarize Blocks = count() by bin(timestamp, 1h)
| order by timestamp asc"""

Q_OVERSHARING = """AnswerLedger
| summarize AvgRows = avg(row_count), MaxRows = max(row_count) by agent_id
| extend OversharingRatio = round(MaxRows / AvgRows, 1)
| order by OversharingRatio desc"""


# ─── Build tiles per page ────────────────────────────────────────────────────
tiles = [
    # ── Page 1: Trust Scorecard ───────────────────────────────────────────
    tile("AnswerTrust Score (Avg Last 24h)", Q_TRUST_SCORE,     "stat",      PAGE_TRUST, 0, 0,  4, 4, stat_opts()),
    tile("Trustworthy Answers %",            Q_TRUSTWORTHY_PCT, "stat",      PAGE_TRUST, 4, 0,  4, 4, stat_opts()),
    tile("AnswerTrust by Agent",             Q_TRUST_BY_AGENT,  "bar",       PAGE_TRUST, 8, 0,  4, 8),
    tile("Trust Score Trend (1h bins)",      Q_TRUST_TREND,     "timechart", PAGE_TRUST, 0, 4,  8, 8),

    # ── Page 2: DQ Health ─────────────────────────────────────────────────
    tile("DQ Pass Rate Trend",               Q_DQ_TREND,        "timechart", PAGE_DQ, 0, 0,  12, 8),
    tile("DLP Decision Mix",                 Q_DLP_DECISION_MIX, "pie",      PAGE_DQ, 0, 8,  4,  8),
    tile("Failed Rows (Last 7d)",            Q_FAILED_ROWS,     "table",     PAGE_DQ, 4, 8,  8,  8, table_opts()),

    # ── Page 3: Cost & Performance ────────────────────────────────────────
    tile("Cost per Day",                     Q_COST_PER_DAY,    "timechart", PAGE_COST, 0, 0,  6, 8),
    tile("Agent Latency P95",                Q_LATENCY_P95,     "timechart", PAGE_COST, 6, 0,  6, 8),
    tile("Tokens & Cost by Agent",           Q_TOKENS_BY_AGENT, "table",     PAGE_COST, 0, 8,  12, 8, table_opts()),

    # ── Page 4: Security Signals ──────────────────────────────────────────
    tile("Red Team Flags",                   Q_RED_TEAM_FLAGS,  "table",     PAGE_SECURITY, 0, 0,  12, 8, table_opts()),
    tile("DLP Blocks (1h bins)",             Q_DLP_BLOCKS,      "timechart", PAGE_SECURITY, 0, 8,  6,  8),
    tile("Oversharing Ratio by Agent",       Q_OVERSHARING,     "bar",       PAGE_SECURITY, 6, 8,  6,  8),
]

# ─── Assemble dashboard ─────────────────────────────────────────────────────
dashboard = {
    "schema_version": 63,
    "title": "AnswerTrust Observability Dashboard",
    "autoRefresh": {"enabled": True, "defaultInterval": "1m", "minInterval": "30s"},
    "dataSources": [
        {
            "kind": "kusto-trident", "scopeId": "kusto-trident",
            "clusterUri": CLUSTER_URI, "database": DATABASE_ID,
            "name": DATABASE_NAME, "id": DS_ID, "workspace": WORKSPACE_ID,
        }
    ],
    "pages": [
        {"id": PAGE_TRUST,    "name": "Trust Scorecard"},
        {"id": PAGE_DQ,       "name": "DQ Health"},
        {"id": PAGE_COST,     "name": "Cost & Performance"},
        {"id": PAGE_SECURITY, "name": "Security Signals"},
    ],
    "parameters": [],
    "baseQueries": [],
    "queries": _queries,
    "tiles": tiles,
}


def main():
    out = os.path.normpath(OUTPUT_FILE)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(dashboard, f, indent=2)
    print(f"Dashboard JSON written to: {out}")
    print(f"  Title : {dashboard['title']}")
    print(f"  Pages : {len(dashboard['pages'])}")
    print(f"  Tiles : {len(dashboard['tiles'])}")
    print("\nImport into Fabric: create a Real-Time Dashboard -> Edit -> Manage tab ->")
    print(f"  'Replace with file' -> select {os.path.basename(out)}; or run 10_Generate_Dashboard.ipynb.")
    return out


if __name__ == "__main__":
    main()

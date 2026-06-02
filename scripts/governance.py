"""governance.py — AnswerTrust M2 (Governance) + M6 (Runtime DLP, Eval, Score).

Pure-Python, dependency-light control-plane logic so it is unit-testable locally and
runs unchanged inside the Fabric notebook. Three concerns:

* **M2 Label Suggestion** — heuristic recommender that inspects column names / sample
  data and proposes a Purview sensitivity label (the deterministic core the
  Label-Suggestion Data Agent wraps).
* **M6 Runtime DLP** — ``PurviewPolicyMiddleware`` enforces EXTRACT rights at inference
  time and masks columns the caller cannot read.
* **M6 Score** — ``compute_answertrust_score`` implements the AnswerTrust formula and the
  continuous-eval pass-rate / drift check.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --- Sensitivity labels ---------------------------------------------------------------
GENERAL = "General"
CONFIDENTIAL = "Confidential"
STRICTLY_CONFIDENTIAL = "Strictly Confidential"

LABEL_RANK = {GENERAL: 0, CONFIDENTIAL: 1, STRICTLY_CONFIDENTIAL: 2}

# Column-name signals -> label. Order matters (most sensitive first).
_STRICT_SIGNALS = ("ssn", "social_security", "credit_card", "card_number", "passport",
                   "diagnosis", "icd", "health", "mrn", "patient")
_CONFIDENTIAL_SIGNALS = ("customer_name", "first_name", "last_name", "full_name",
                        "contact_name", "person_name", "patient_name",
                        "email", "phone", "address", "revenue", "salary",
                        "margin", "account", "dob", "birth")


# =====================================================================================
# M2 — Label Suggestion
# =====================================================================================
def suggest_label(table_name: str, columns: Sequence[str],
                  sample_rows: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Recommend a sensitivity label for a table from its column names (+ optional sample).

    Returns ``{table_name, recommended_label, rationale, matched_columns}``."""
    cols = [c.lower() for c in columns]
    strict_hits = [c for c in cols if any(sig in c for sig in _STRICT_SIGNALS)]
    conf_hits = [c for c in cols if any(sig in c for sig in _CONFIDENTIAL_SIGNALS)]

    if strict_hits:
        label, hits = STRICTLY_CONFIDENTIAL, strict_hits
        rationale = f"Contains regulated identifiers ({', '.join(sorted(set(strict_hits)))})."
    elif conf_hits:
        label, hits = CONFIDENTIAL, conf_hits
        rationale = f"Contains PII / financial columns ({', '.join(sorted(set(conf_hits)))})."
    else:
        label, hits = GENERAL, []
        rationale = "No PII, financial, or regulated columns detected."

    return {
        "table_name": table_name,
        "recommended_label": label,
        "rationale": rationale,
        "matched_columns": sorted(set(hits)),
    }


def suggest_labels_for_tables(table_columns: Dict[str, Sequence[str]]) -> List[Dict[str, Any]]:
    """Run :func:`suggest_label` over ``{table_name: [columns]}``."""
    return [suggest_label(t, cols) for t, cols in table_columns.items()]


# =====================================================================================
# M6 — Runtime DLP (PurviewPolicyMiddleware)
# =====================================================================================
def has_extract_right(user_policies: Dict[str, Iterable[str]], label: str) -> bool:
    """True if the user's policy grants EXTRACT on ``label``.

    ``user_policies`` maps action -> iterable of labels the user may act on, e.g.
    ``{"EXTRACT": ["General", "Confidential"]}``."""
    return label in set(user_policies.get("EXTRACT", []))


class PurviewPolicyMiddleware:
    """Enforce EXTRACT rights at inference time and mask unauthorized columns.

    ``label_map`` maps a (possibly qualified) table name -> its sensitivity label.
    ``column_labels`` optionally maps ``"table.column"`` -> label for column masking.
    Lookups are resilient to warehouse/schema qualification (``WH.dbo.fact_sales``)."""

    def __init__(self, label_map: Dict[str, str],
                 column_labels: Optional[Dict[str, str]] = None,
                 *, protected=(CONFIDENTIAL, STRICTLY_CONFIDENTIAL)):
        self.label_map = label_map
        self.column_labels = column_labels or {}
        self.protected = set(protected)

    def _label_for(self, table: str) -> str:
        if table in self.label_map:
            return self.label_map[table]
        leaf = table.split(".")[-1]  # tolerate WH.dbo.table qualification
        return self.label_map.get(leaf, GENERAL)

    def check_dlp_policy(self, user_upn: str, source_tables: Sequence[str],
                         user_policies: Dict[str, Iterable[str]]) -> Dict[str, Any]:
        """Return ``{decision: ALLOW|BLOCK, reason, blocked_tables}``."""
        blocked = []
        for table in source_tables:
            label = self._label_for(table)
            if label in self.protected and not has_extract_right(user_policies, label):
                blocked.append({"table": table, "label": label})
        if blocked:
            first = blocked[0]
            return {
                "decision": "BLOCK",
                "reason": f"{user_upn} has no EXTRACT right for {first['label']} "
                          f"on {first['table']}",
                "blocked_tables": blocked,
            }
        return {"decision": "ALLOW", "reason": "", "blocked_tables": []}

    def mask_sensitive_columns(self, row: Dict[str, Any], table: str,
                               user_policies: Dict[str, Iterable[str]],
                               *, mask: str = "***") -> Dict[str, Any]:
        """Redact columns whose column-level label exceeds the caller's EXTRACT grant."""
        masked = dict(row)
        leaf = table.split(".")[-1]
        for col in row:
            label = self.column_labels.get(f"{table}.{col}") or \
                self.column_labels.get(f"{leaf}.{col}")
            if label in self.protected and not has_extract_right(user_policies, label):
                masked[col] = mask
        return masked


# =====================================================================================
# M6 — Continuous Eval
# =====================================================================================
EVAL_THRESHOLDS = {
    "groundedness": 0.80,
    "intent_resolution": 0.90,
    "tool_call_accuracy": 0.95,
    "retrieval_f1": 0.85,
}


def heuristic_eval(question: str, answer: str, expected_pattern: Optional[str] = None) -> Dict[str, float]:
    """Deterministic stand-in for Foundry evaluators (used for local/dry runs).

    Real runs swap this for ``azure.ai.evaluation`` graders; the shape is identical so
    downstream score/ledger code is unchanged."""
    grounded = 1.0 if answer and not answer.lower().startswith("i don't") else 0.5
    intent = 1.0 if expected_pattern and re.search(expected_pattern, answer or "", re.I) else 0.85
    tool_acc = 1.0 if answer else 0.0
    retrieval = 0.9 if answer else 0.0
    return {
        "groundedness": round(grounded, 3),
        "intent_resolution": round(intent, 3),
        "tool_call_accuracy": round(tool_acc, 3),
        "retrieval_f1": round(retrieval, 3),
    }


def eval_passed(scores: Dict[str, float], thresholds: Dict[str, float] = None) -> bool:
    thresholds = thresholds or EVAL_THRESHOLDS
    return all(scores.get(k, 0.0) >= t for k, t in thresholds.items())


def continuous_eval(golden_questions: Sequence[Dict[str, Any]], answer_fn,
                    *, thresholds: Dict[str, float] = None) -> Dict[str, Any]:
    """Evaluate each golden question. ``answer_fn(question)->answer_text``.

    Returns ``{results, pass_rate, drift}`` (drift True when pass_rate < 0.90)."""
    thresholds = thresholds or EVAL_THRESHOLDS
    results = []
    for q in golden_questions:
        question = q.get("question", "")
        answer = answer_fn(question)
        scores = heuristic_eval(question, answer, q.get("expected_pattern"))
        results.append({
            "question_id": q.get("id"),
            "trace_id": q.get("trace_id"),
            "scores": scores,
            "passed": eval_passed(scores, thresholds),
        })
    pass_rate = round(sum(r["passed"] for r in results) / len(results), 4) if results else 1.0
    return {"results": results, "pass_rate": pass_rate, "drift": pass_rate < 0.90}


# =====================================================================================
# M6 — AnswerTrust Score
# =====================================================================================
DEFAULT_WEIGHTS = {"eval": 0.30, "dq": 0.25, "label": 0.20, "freshness": 0.15, "red_team": 0.10}


def compute_freshness(source_tables: Sequence[str], freshness_map: Optional[Dict[str, float]] = None) -> float:
    """Mean per-table freshness in [0,1] (1.0 = within SLA). Defaults to fresh."""
    if not source_tables:
        return 1.0
    fm = freshness_map or {}
    leaf = lambda t: t.split(".")[-1]
    vals = [fm.get(t, fm.get(leaf(t), 1.0)) for t in source_tables]
    return round(sum(vals) / len(vals), 6)


def compute_answertrust_score(ledger_row: Dict[str, Any], *,
                              weights: Dict[str, float] = None,
                              freshness_map: Optional[Dict[str, float]] = None,
                              trust_threshold: float = 0.70) -> Dict[str, Any]:
    """AnswerTrust = w_e·Eval + w_d·DQ + w_l·Label + w_f·Freshness − w_r·RedTeamFlags.

    Returns ``{answertrust_score, trustworthy, components}`` with the score clamped [0,1]."""
    w = weights or DEFAULT_WEIGHTS

    eval_scores = ledger_row.get("eval_scores") or {}
    eval_score = round(sum(eval_scores.values()) / len(eval_scores), 6) if eval_scores else 0.0
    dq_score = float(ledger_row.get("dq_score") or 0.0)
    label_compliance = 1.0 if ledger_row.get("dlp_decision", "ALLOW") == "ALLOW" else 0.0
    freshness = compute_freshness(ledger_row.get("source_tables") or [], freshness_map)
    red_team_penalty = len(ledger_row.get("red_team_flags") or [])

    raw = (w["eval"] * eval_score
           + w["dq"] * dq_score
           + w["label"] * label_compliance
           + w["freshness"] * freshness
           - w["red_team"] * red_team_penalty)
    score = round(max(0.0, min(1.0, raw)), 6)
    return {
        "answertrust_score": score,
        "trustworthy": score >= trust_threshold,
        "components": {
            "eval": eval_score, "dq": dq_score, "label": label_compliance,
            "freshness": freshness, "red_team_flags": red_team_penalty,
        },
    }

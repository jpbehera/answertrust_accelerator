"""dq.py — AnswerTrust M5 (Data Quality Gate).

Backend-agnostic data-quality engine. The rule evaluators operate on a pandas
``DataFrame`` so the logic is unit-testable locally; on Fabric the M5 notebook
converts (small) Spark tables via ``.toPandas()`` or mirrors the same predicates with
native Spark aggregates. Results feed two Lakehouse tables (``dq_runs.results`` and
``dq_runs.failed_rows``) and the ``dq_score`` column of the M4 AnswerLedger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# --- Dimension names ------------------------------------------------------------------
COMPLETENESS = "completeness"
CONSISTENCY = "consistency"
VALIDITY = "validity"
UNIQUENESS = "uniqueness"
FORMAT = "format"

DIMENSIONS = (COMPLETENESS, CONSISTENCY, VALIDITY, UNIQUENESS, FORMAT)


@dataclass
class DimensionRule:
    """A single DQ expectation on one column."""

    table: str
    column: str
    dimension: str
    threshold: float = 0.95
    params: Dict[str, Any] = field(default_factory=dict)

    def label(self) -> str:
        return f"{self.table}.{self.column}:{self.dimension}"


def default_dq_config() -> List[DimensionRule]:
    """The rule set from the build plan (BusinessMetrics substrate)."""
    return [
        DimensionRule("fact_sales", "revenue", COMPLETENESS, 0.95),
        DimensionRule("fact_sales", "revenue", CONSISTENCY, 1.0, {"min_value": 0}),
        DimensionRule("fact_sales", "margin", COMPLETENESS, 0.90),
        DimensionRule("fact_sales", "margin", VALIDITY, 0.98, {"min_value": -0.5, "max_value": 1.0}),
        DimensionRule("dim_customers", "email_domain", UNIQUENESS, 0.99),
        DimensionRule("dim_customers", "email_domain", FORMAT, 0.95, {"regex": r"^[a-z0-9-]+\.[a-z]+$"}),
    ]


# --- Pure evaluators (operate on a sequence of values) --------------------------------
def _is_null(v: Any) -> bool:
    if v is None:
        return True
    # NaN check without importing numpy
    return isinstance(v, float) and v != v


def _eval_completeness(values: Sequence[Any]) -> Dict[str, Any]:
    total = len(values)
    failed = [i for i, v in enumerate(values) if _is_null(v)]
    return {"pass_rate": _rate(total, failed), "failed_idx": failed}


def _eval_consistency(values: Sequence[Any], min_value: float = 0) -> Dict[str, Any]:
    failed = [i for i, v in enumerate(values) if not _is_null(v) and v < min_value]
    return {"pass_rate": _rate(len(values), failed), "failed_idx": failed}


def _eval_validity(values: Sequence[Any], min_value: float, max_value: float) -> Dict[str, Any]:
    failed = [
        i for i, v in enumerate(values)
        if not _is_null(v) and not (min_value <= v <= max_value)
    ]
    return {"pass_rate": _rate(len(values), failed), "failed_idx": failed}


def _eval_uniqueness(values: Sequence[Any]) -> Dict[str, Any]:
    seen: Dict[Any, int] = {}
    failed: List[int] = []
    for i, v in enumerate(values):
        if v in seen:
            failed.append(i)
        else:
            seen[v] = i
    return {"pass_rate": _rate(len(values), failed), "failed_idx": failed}


def _eval_format(values: Sequence[Any], regex: str) -> Dict[str, Any]:
    pattern = re.compile(regex)
    failed = [
        i for i, v in enumerate(values)
        if _is_null(v) or not pattern.match(str(v))
    ]
    return {"pass_rate": _rate(len(values), failed), "failed_idx": failed}


def _rate(total: int, failed_idx: Sequence[int]) -> float:
    if total == 0:
        return 1.0
    return round(1.0 - (len(failed_idx) / total), 6)


_EVALUATORS = {
    COMPLETENESS: lambda vals, p: _eval_completeness(vals),
    CONSISTENCY: lambda vals, p: _eval_consistency(vals, p.get("min_value", 0)),
    VALIDITY: lambda vals, p: _eval_validity(vals, p["min_value"], p["max_value"]),
    UNIQUENESS: lambda vals, p: _eval_uniqueness(vals),
    FORMAT: lambda vals, p: _eval_format(vals, p["regex"]),
}


def evaluate_rule(df, rule: DimensionRule) -> Dict[str, Any]:
    """Evaluate one rule against a pandas DataFrame; returns a result record."""
    if rule.column not in df.columns:
        raise KeyError(f"Column '{rule.column}' not found in table '{rule.table}'")
    values = list(df[rule.column])
    evaluator = _EVALUATORS[rule.dimension]
    outcome = evaluator(values, rule.params)
    pass_rate = outcome["pass_rate"]
    return {
        "table_name": rule.table,
        "column_name": rule.column,
        "dimension": rule.dimension,
        "threshold": rule.threshold,
        "pass_rate": pass_rate,
        "failed_rows": len(outcome["failed_idx"]),
        "failed_idx": outcome["failed_idx"],
        "passed": pass_rate >= rule.threshold,
    }


def run_dq(tables: Dict[str, Any], config: List[DimensionRule], run_id: str) -> Dict[str, Any]:
    """Run all rules. ``tables`` maps table_name -> pandas DataFrame.

    Returns ``{"run_id", "results", "failed_rows", "overall_score", "gate_passed"}``.
    ``results`` excludes the bulky ``failed_idx`` (kept only for ``failed_rows``)."""
    results, failed_rows = [], []
    for rule in config:
        df = tables.get(rule.table)
        if df is None:
            continue
        res = evaluate_rule(df, rule)
        for idx in res.pop("failed_idx"):
            failed_rows.append({
                "run_id": run_id,
                "table_name": rule.table,
                "column_name": rule.column,
                "dimension": rule.dimension,
                "row_index": idx,
            })
        res["run_id"] = run_id
        results.append(res)

    score = overall_score(results)
    return {
        "run_id": run_id,
        "results": results,
        "failed_rows": failed_rows,
        "overall_score": score,
        "gate_passed": all(r["passed"] for r in results) if results else True,
    }


def overall_score(results: List[Dict[str, Any]]) -> float:
    """Mean pass_rate across all evaluated dimensions (0..1)."""
    if not results:
        return 1.0
    return round(sum(r["pass_rate"] for r in results) / len(results), 6)


def dq_dimensions_summary(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Collapse per-rule results to ``{dimension: mean_pass_rate}`` for the ledger."""
    by_dim: Dict[str, List[float]] = {}
    for r in results:
        by_dim.setdefault(r["dimension"], []).append(r["pass_rate"])
    return {dim: round(sum(v) / len(v), 6) for dim, v in by_dim.items()}


def build_ledger_dq_update(trace_id: str, dq: Dict[str, Any]) -> str:
    """KQL to stamp the DQ score/dimensions onto the AnswerLedger row for ``trace_id``.

    Uses an append-with-update-policy friendly pattern: emit a partial-update record via
    ``.set-or-append`` into a staging function is heavier than needed for the demo, so we
    return a ``.update`` command (illustrative; requires the table's update grant)."""
    import json

    dims = json.dumps(dq_dimensions_summary(dq["results"]))
    return (
        "AnswerLedger\n"
        f"| where trace_id == '{trace_id}'\n"
        f"| extend dq_score = {dq['overall_score']}, "
        f"dq_dimensions = todynamic('{dims}')"
    )

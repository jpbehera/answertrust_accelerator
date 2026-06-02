"""ledger.py — AnswerTrust M4 (AnswerLedger provenance store).

Builds and emits the single provenance row that AnswerTrust persists per answer,
keyed by ``trace_id`` (the trace_id produced by the M3 trace fabric). Events are POSTed
as JSON to a Fabric **Eventstream custom endpoint**, which lands them in the
``AnswerLedger`` KQL table inside Eventhouse ``answer_ledger_db``.

Portability: depends only on ``requests`` (lazy) + stdlib. The SQL table-extraction is
reused from ``foundry_wrapper`` when available, with a local fallback so this module can
be imported/tested standalone.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Reuse the M3 table extractor; fall back to a no-op if the module isn't importable.
try:  # pragma: no cover - import path depends on runtime
    from foundry_wrapper import extract_tables_from_sql
except Exception:  # pragma: no cover

    def extract_tables_from_sql(sql: str) -> List[str]:  # type: ignore
        return []


# ---------------------------------------------------------------------------
# Cost model — approximate USD per 1K tokens (input+output blended).
# Override via ``model_prices`` if you track input/output separately.
#
# NOTE: The Fabric **Data Agent** runs on a Microsoft-managed model that you
# cannot select; its consumption is billed via Fabric **capacity CU**, not
# per-token Azure OpenAI pricing — so the ``fabric-managed`` rate is 0.0 here
# (token-based cost does not apply on the agent path). The per-token entries
# below apply only to components that call Azure OpenAI **directly** (e.g. the
# Module 6 continuous-eval judge on ``o4-mini``).
# ---------------------------------------------------------------------------
_DEFAULT_PRICES_PER_1K: Dict[str, float] = {
    "fabric-managed": 0.0,
    "gpt-4.1": 0.0040,
    "gpt-4.1-mini": 0.00080,
    "o4-mini": 0.0022,
    "gpt-4o": 0.0050,
    "gpt-4o-mini": 0.00060,
    "gpt-4": 0.030,
    "gpt-4-turbo": 0.010,
    "gpt-35-turbo": 0.0015,
}


def calculate_cost(
    usage: Optional[Dict[str, Any]],
    model: str = "fabric-managed",
    model_prices: Optional[Dict[str, float]] = None,
) -> float:
    """Approximate answer cost in USD from a usage dict (``total_tokens``).

    Unknown/managed models resolve to a 0.0 per-token rate (Fabric Data Agent
    cost is CU-based, not per-token)."""
    prices = model_prices or _DEFAULT_PRICES_PER_1K
    total_tokens = int((usage or {}).get("total_tokens", 0) or 0)
    rate = prices.get(model, 0.0)
    return round((total_tokens / 1000.0) * rate, 6)


def get_user_upn_from_token(user_token: Optional[str]) -> str:
    """Best-effort UPN extraction from a (non-validated) JWT's ``upn``/``unique_name``.

    This does NOT verify the signature — it only reads the claims for provenance display.
    Authorization is enforced upstream by the OBO token itself (M1).
    """
    if not user_token or user_token.count(".") < 2:
        return "unknown"
    try:
        payload_b64 = user_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # pad to multiple of 4
        claims = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        return claims.get("upn") or claims.get("unique_name") or claims.get("email") or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Provenance event
# ---------------------------------------------------------------------------
# Canonical column order — mirrors the KQL AnswerLedger schema (scripts/kql/answer_ledger.kql).
LEDGER_COLUMNS: List[str] = [
    "trace_id", "timestamp", "user_upn", "agent_id", "prompt", "generated_query",
    "source_tables", "sensitivity_labels", "dlp_decision", "dq_score", "dq_dimensions",
    "row_count", "rows_masked", "model", "tokens_used", "cost_usd", "latency_ms",
    "eval_scores", "red_team_flags", "irm_signals", "answertrust_score", "trustworthy",
]


def build_provenance_event(
    trace_id: str,
    user_query: str,
    generated_sql: str,
    result: Optional[Dict[str, Any]] = None,
    *,
    user_token: Optional[str] = None,
    agent_id: str = "BusinessMetricsAgent",
    model: str = "fabric-managed",
) -> Dict[str, Any]:
    """Assemble one AnswerLedger row. Downstream modules (M2/M5/M6/M7) enrich the
    placeholder fields; M4 guarantees the row exists keyed by ``trace_id``."""
    result = result or {}
    usage = result.get("usage", {}) or {}
    rows = result.get("rows", []) or []

    return {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_upn": get_user_upn_from_token(user_token),
        "agent_id": result.get("agent_id", agent_id),
        "prompt": user_query,
        "generated_query": generated_sql,
        "source_tables": extract_tables_from_sql(generated_sql),
        "sensitivity_labels": result.get("sensitivity_labels", []),  # M2
        "dlp_decision": result.get("dlp_decision", "ALLOW"),          # M6
        "dq_score": float(result.get("dq_score", 0.0)),               # M5
        "dq_dimensions": result.get("dq_dimensions", {}),             # M5
        "row_count": len(rows),
        "rows_masked": int(result.get("rows_masked", 0)),             # M6
        "model": model,
        "tokens_used": int(usage.get("total_tokens", 0) or 0),
        "cost_usd": calculate_cost(usage, model),
        "latency_ms": int(result.get("latency_ms", 0) or 0),
        "eval_scores": result.get("eval_scores", {}),                 # M6
        "red_team_flags": result.get("red_team_flags", []),           # M7
        "irm_signals": result.get("irm_signals", {}),                 # M7
        "answertrust_score": float(result.get("answertrust_score", 0.0)),
        "trustworthy": bool(result.get("trustworthy", False)),
    }


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------
class AnswerLedgerEmitter:
    """POSTs provenance events to a Fabric Eventstream custom-endpoint URL."""

    def __init__(self, custom_endpoint_url: str, *, session: Any = None) -> None:
        if not custom_endpoint_url:
            raise ValueError("custom_endpoint_url is required (Eventstream ingest URL).")
        self.url = custom_endpoint_url
        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    def emit(self, event: Dict[str, Any], *, timeout: int = 30) -> int:
        """Send one event; returns the HTTP status code. Raises on transport error."""
        resp = self._session.post(
            self.url,
            data=json.dumps(event),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.status_code

    def emit_many(self, events: List[Dict[str, Any]], *, timeout: int = 30) -> int:
        """Send a batch (newline-delimited JSON); returns count emitted."""
        for event in events:
            self.emit(event, timeout=timeout)
        return len(events)

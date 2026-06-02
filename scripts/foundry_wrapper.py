"""foundry_wrapper.py — AnswerTrust M3 (Unified Trace Fabric) + M1 (Identity Passthrough).

A dependency-light tracing layer that propagates a single W3C ``traceparent`` across
the whole answer path:

    orchestrator (Foundry agent)  ->  MCP tool call  ->  Fabric Data Agent SQL

Every hop opens an OpenTelemetry span under the same trace_id, and the Foundry call
carries the caller's Entra token on-behalf-of (OBO) so downstream authorization is the
*user's*, not the app's.

Design notes
------------
* Only ``opentelemetry-api`` is imported at module load (tiny, always safe). The Azure
  Monitor exporter and the ``mcp`` client are imported lazily so this module can be
  unit-tested / imported on a laptop without the full Fabric/Foundry stack.
* ``TracedMCPClient`` *wraps* an existing MCP client by composition rather than
  subclassing, so it works regardless of the concrete client class the runtime provides.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

from opentelemetry import trace
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Module-level tracer + propagator. ``configure_tracing`` wires the exporter; until then
# spans are no-ops, which keeps imports cheap and side-effect free.
tracer = trace.get_tracer("answertrust.m3")
_propagator = TraceContextTextMapPropagator()


# ---------------------------------------------------------------------------
# Telemetry bootstrap
# ---------------------------------------------------------------------------
def configure_tracing(
    connection_string: str,
    *,
    enable_azure_sdk: bool = True,
) -> None:
    """Wire OpenTelemetry to Application Insights via the Azure Monitor OTel Distro.

    Safe to call once per process. Raises ``RuntimeError`` if the distro is missing so
    the caller can ``%pip install azure-monitor-opentelemetry`` and retry.
    """
    if not connection_string:
        raise ValueError("connection_string is required (App Insights connection string).")
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "azure-monitor-opentelemetry is not installed. "
            "Run: %pip install azure-monitor-opentelemetry"
        ) from exc

    configure_azure_monitor(
        connection_string=connection_string,
        instrumentation_options={
            "azure_sdk": {"enabled": enable_azure_sdk},
            "flask": {"enabled": False},
            "django": {"enabled": False},
            "fastapi": {"enabled": False},
        },
    )


def current_traceparent() -> Optional[str]:
    """Return the W3C ``traceparent`` for the active span, or ``None`` if untraced."""
    carrier: Dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


def current_trace_id() -> Optional[str]:
    """Return the 32-hex-char trace_id of the active span (the AnswerLedger key)."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


# ---------------------------------------------------------------------------
# M1: Foundry orchestrator client with OBO + traceparent
# ---------------------------------------------------------------------------
class FoundryOrchestratorClient:
    """Invoke a Foundry agent with on-behalf-of identity and trace propagation."""

    def __init__(self, foundry_endpoint: str, *, session: Any = None) -> None:
        self.endpoint = foundry_endpoint.rstrip("/")
        # Lazy ``requests`` import keeps the module importable without it.
        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    def invoke_agent(
        self,
        agent_id: str,
        user_query: str,
        user_token: str,
        *,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """Invoke ``agent_id`` for ``user_query`` carrying the caller's OBO token.

        The active span's ``traceparent`` is injected so the Foundry side continues the
        same trace; the user's bearer token is forwarded for downstream authorization.
        """
        with tracer.start_as_current_span("invoke_agent") as span:
            span.set_attribute("agent.id", agent_id)
            span.set_attribute("user.query", user_query[:100])
            span.set_attribute("obo.enabled", True)
            span.set_attribute("answertrust.trace_id", current_trace_id() or "")

            headers: Dict[str, str] = {}
            _propagator.inject(headers)  # W3C traceparent
            headers["Authorization"] = f"Bearer {user_token}"  # OBO token
            headers["X-User-Identity"] = user_token  # Foundry OBO passthrough header

            response = self._session.post(
                f"{self.endpoint}/agents/{agent_id}/invoke",
                json={"query": user_query},
                headers=headers,
                timeout=timeout,
            )
            span.set_attribute("response.status", response.status_code)
            response.raise_for_status()
            return response.json()


# ---------------------------------------------------------------------------
# M3: MCP client wrapper that injects traceparent into tool calls
# ---------------------------------------------------------------------------
class TracedMCPClient:
    """Compose around any MCP client and inject ``traceparent`` into each tool call."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        arguments = dict(arguments or {})
        with tracer.start_as_current_span("mcp.tool.call") as span:
            span.set_attribute("tool.name", tool_name)
            span.set_attribute("tool.arguments", str(arguments)[:200])

            tp = current_traceparent()
            if tp:
                arguments["_traceparent"] = tp  # carried into the tool boundary

            result = self._inner.call_tool(tool_name, arguments)
            span.set_attribute("tool.result.size", len(str(result)))
            return result

    def __getattr__(self, name: str) -> Any:
        # Transparently delegate everything else to the wrapped client.
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# M3: Fabric Data Agent span emitter
# ---------------------------------------------------------------------------
_TABLE_RE = re.compile(r"\b(?:from|join)\s+([\[\]\w.\"`]+)", re.IGNORECASE)


def extract_tables_from_sql(sql: str) -> list[str]:
    """Best-effort extraction of source tables referenced by ``FROM`` / ``JOIN``."""
    if not sql:
        return []
    seen: list[str] = []
    for match in _TABLE_RE.findall(sql):
        name = match.strip().translate(str.maketrans("", "", '[]"`'))
        if name and name.lower() not in {"(select", "lateral"} and name not in seen:
            seen.append(name)
    return seen


def emit_data_agent_span(
    agent_id: str,
    user_query: str,
    generated_sql: str,
    result_rows: Any,
    *,
    on_span: Optional[Callable[[Span], None]] = None,
) -> Optional[str]:
    """Emit the leaf ``fabric.data_agent.query`` span and return its trace_id.

    ``on_span`` lets callers attach extra attributes (e.g. DQ score, label) before the
    span closes. Returns the trace_id so the M4 AnswerLedger can key the provenance row.
    """
    row_count = len(result_rows) if hasattr(result_rows, "__len__") else 0
    with tracer.start_as_current_span("fabric.data_agent.query") as span:
        span.set_attribute("agent.id", agent_id)
        span.set_attribute("query", user_query[:100])
        span.set_attribute("sql.generated", (generated_sql or "")[:500])
        span.set_attribute("result.row_count", row_count)
        span.set_attribute("source.tables", ", ".join(extract_tables_from_sql(generated_sql)))
        if on_span is not None:
            on_span(span)
        return current_trace_id()

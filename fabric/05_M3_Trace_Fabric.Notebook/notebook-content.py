# Fabric notebook source


# MARKDOWN ********************

# # 05 — M3 Unified Trace Fabric (+ M1 OBO)
# 
# **AnswerTrust accelerator · Phase 3**
# 
# Gives every answer **one trace_id** by propagating the W3C `traceparent` across the
# whole path:
# 
# > orchestrator (`invoke_agent`) → MCP tool (`mcp.tool.call`) → Fabric Data Agent (`fabric.data_agent.query`)
# 
# and forwards the caller's Entra token **on-behalf-of (OBO)** so downstream
# authorization is the *user's*, not the app's (**M1 Identity Passthrough**).
# 
# Spans export to **Application Insights** (provisioned by `infra/app-insights.bicep`).
# The leaf span's `trace_id` becomes the key for the **M4 AnswerLedger** provenance row.
# 
# The reusable implementation lives in `scripts/foundry_wrapper.py`; the classes are
# inlined below so the notebook runs self-contained on any Fabric runtime.

# MARKDOWN ********************

# ## 0. Parameters

# CELL ********************

# --- Parameters -----------------------------------------------------------------------
app_insights_connection_string = ""   # REQUIRED: from infra output AT_APPINSIGHTS_CONNECTION_STRING
foundry_endpoint               = ""   # e.g. https://<project>.services.ai.azure.com
agent_id                       = "BusinessMetricsAgent"
run_live_invoke                = False  # keep False for local/dry runs; True hits Foundry
test_question                  = "What was total revenue in Q1 2026?"

# MARKDOWN ********************

# ## 1. Install Azure Monitor OpenTelemetry Distro & configure export

# CELL ********************

%pip install azure-monitor-opentelemetry opentelemetry-api --quiet

# CELL ********************

from opentelemetry import trace
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

tracer = trace.get_tracer("answertrust.m3")
_propagator = TraceContextTextMapPropagator()

if app_insights_connection_string:
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(
        connection_string=app_insights_connection_string,
        instrumentation_options={
            "azure_sdk": {"enabled": True},
            "flask": {"enabled": False},
            "django": {"enabled": False},
            "fastapi": {"enabled": False},
        },
    )
    print("Azure Monitor OTel configured — spans will export to App Insights.")
else:
    print("No connection string set — running with in-memory (no-op export) spans.")

# CELL ********************

def current_traceparent():
    """W3C traceparent for the active span (None if untraced)."""
    carrier = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")

def current_trace_id():
    """32-hex trace_id of the active span — the AnswerLedger key."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None

# MARKDOWN ********************

# ## 2. M1 — Foundry orchestrator client (OBO + traceparent)
# 
# Injects `traceparent` into the outbound HTTP headers and forwards the caller's bearer
# token so Foundry authorizes downstream calls as the user.

# CELL ********************

import requests

class FoundryOrchestratorClient:
    def __init__(self, foundry_endpoint, session=None):
        self.endpoint = foundry_endpoint.rstrip("/")
        self._session = session or requests.Session()

    def invoke_agent(self, agent_id, user_query, user_token, timeout=60):
        with tracer.start_as_current_span("invoke_agent") as span:
            span.set_attribute("agent.id", agent_id)
            span.set_attribute("user.query", user_query[:100])
            span.set_attribute("obo.enabled", True)
            span.set_attribute("answertrust.trace_id", current_trace_id() or "")

            headers = {}
            _propagator.inject(headers)                       # W3C traceparent
            headers["Authorization"] = f"Bearer {user_token}"  # OBO token
            headers["X-User-Identity"] = user_token            # Foundry OBO passthrough

            resp = self._session.post(
                f"{self.endpoint}/agents/{agent_id}/invoke",
                json={"query": user_query}, headers=headers, timeout=timeout,
            )
            span.set_attribute("response.status", resp.status_code)
            resp.raise_for_status()
            return resp.json()

# MARKDOWN ********************

# ## 3. M3 — Traced MCP client wrapper
# 
# Wraps any MCP client by composition and threads `traceparent` into the tool-call
# arguments, so the tool boundary stays inside the same trace.

# CELL ********************

class TracedMCPClient:
    def __init__(self, inner):
        self._inner = inner

    def call_tool(self, tool_name, arguments=None):
        arguments = dict(arguments or {})
        with tracer.start_as_current_span("mcp.tool.call") as span:
            span.set_attribute("tool.name", tool_name)
            span.set_attribute("tool.arguments", str(arguments)[:200])
            tp = current_traceparent()
            if tp:
                arguments["_traceparent"] = tp
            result = self._inner.call_tool(tool_name, arguments)
            span.set_attribute("tool.result.size", len(str(result)))
            return result

    def __getattr__(self, name):
        return getattr(self._inner, name)

# MARKDOWN ********************

# ## 4. M3 — Fabric Data Agent span emitter
# 
# The leaf span. Records the generated SQL and source tables, and returns the `trace_id`
# that downstream M4 uses to write one AnswerLedger row per answer.

# CELL ********************

import re
_TABLE_RE = re.compile(r"\b(?:from|join)\s+([\[\]\w.\"`]+)", re.IGNORECASE)

def extract_tables_from_sql(sql):
    if not sql:
        return []
    seen = []
    for m in _TABLE_RE.findall(sql):
        name = m.strip().translate(str.maketrans("", "", '[]"`'))
        if name and name.lower() not in {"(select", "lateral"} and name not in seen:
            seen.append(name)
    return seen

def emit_data_agent_span(agent_id, user_query, generated_sql, result_rows, on_span=None):
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

# MARKDOWN ********************

# ## 5. End-to-end trace demo
# 
# Opens a root span and threads a **single trace_id** through all three hops. With
# `run_live_invoke = False` the orchestrator/MCP calls are simulated so the notebook runs
# anywhere; set it `True` (and supply `foundry_endpoint` + a user token) to invoke Foundry.

# CELL ********************

class _FakeMCP:
    """Stand-in tool that echoes the traceparent it received (proves propagation)."""
    def call_tool(self, tool_name, arguments):
        return {"tool": tool_name, "received_traceparent": arguments.get("_traceparent")}

def get_user_token():
    """Caller's Entra token for OBO. On Fabric use notebookutils; fallback to placeholder."""
    try:
        import notebookutils
        return notebookutils.credentials.getToken("pbi")
    except Exception:
        return "<user-token-unavailable-locally>"

trace_ids = set()
with tracer.start_as_current_span("answer.request") as root:
    root_trace_id = current_trace_id()
    trace_ids.add(root_trace_id)
    print(f"root trace_id        : {root_trace_id}")

    user_token = get_user_token()

    # Hop 1 — orchestrator (OBO)
    if run_live_invoke and foundry_endpoint:
        client = FoundryOrchestratorClient(foundry_endpoint)
        answer = client.invoke_agent(agent_id, test_question, user_token)
    else:
        with tracer.start_as_current_span("invoke_agent") as span:
            span.set_attribute("agent.id", agent_id)
            span.set_attribute("obo.enabled", True)
            trace_ids.add(current_trace_id())
            print(f"  invoke_agent       : {current_trace_id()}")

            # Hop 2 — MCP tool call
            mcp = TracedMCPClient(_FakeMCP())
            tool_result = mcp.call_tool("run_sql", {"sql": "SELECT SUM(revenue) FROM fact_sales"})
            trace_ids.add(current_trace_id())
            print(f"  mcp.tool.call      : {current_trace_id()}  echoed_tp={tool_result['received_traceparent'][:25]}...")

            # Hop 3 — Fabric Data Agent leaf span
            sql = ("SELECT SUM(s.revenue) AS total_revenue FROM fact_sales s "
                   "JOIN dim_products p ON s.product_id = p.product_id "
                   "WHERE s.sale_date >= '2026-01-01' AND s.sale_date < '2026-04-01'")
            answer_trace_id = emit_data_agent_span(agent_id, test_question, sql, [{"total_revenue": 1234567.0}])
            trace_ids.add(answer_trace_id)
            print(f"  data_agent.query   : {answer_trace_id}")

print(f"\ndistinct trace_ids across all hops: {len(trace_ids)}")
assert len(trace_ids) == 1, "Trace propagation broke — hops have different trace_ids"
print("PASS — one trace_id spans orchestrator -> MCP -> Fabric Data Agent.")

# MARKDOWN ********************

# ## 6. Verification (App Insights)
# 
# When `app_insights_connection_string` is set, spans export to Application Insights.
# Confirm the distributed trace from a terminal:
# 
# ```bash
# az monitor app-insights query \
#   --app <appinsights-name> \
#   --analytics-query "dependencies | where timestamp > ago(15m) | project timestamp, name, operation_Id, target | order by timestamp asc"
# ```
# 
# All three span names (`invoke_agent`, `mcp.tool.call`, `fabric.data_agent.query`) should
# share a single `operation_Id` (the trace_id). That trace_id is the key the **M4
# AnswerLedger** (notebook 06) uses to persist one provenance row per answer.

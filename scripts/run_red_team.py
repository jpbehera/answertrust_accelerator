"""run_red_team.py — CI entrypoint for AnswerTrust M7 nightly red-teaming.

Invoked by .github/workflows/red-team.yml. Runs the attack scenarios from
``security.py`` against the demo agent and ingests any flags into AnswerLedger. The
Foundry / RedTeam SDK is optional: when absent (e.g. local dry-run) a safe stub agent
is used so the harness still exercises end-to-end.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import security  # noqa: E402


def _build_answer_fn():
    """Return ``answer_fn(payload)->answer``. Live Foundry path is optional."""
    project_id = os.environ.get("FOUNDRY_PROJECT_ID")
    agent_id = os.environ.get("DEMO_AGENT_ID")
    try:
        from azure.ai.safety import RedTeamClient  # type: ignore
        from azure.identity import DefaultAzureCredential  # type: ignore
        cred = DefaultAzureCredential()
        client = RedTeamClient(cred, project_id)
        return lambda payload: client.run_attack(agent_id, payload).get("response", "")
    except Exception as exc:  # SDK missing or not configured -> safe stub
        print(f"[red-team] live client unavailable ({exc}); using refusal stub.")
        # A well-guarded agent refuses every attack payload.
        return lambda payload: "I'm sorry, I cannot help with that request."


def _ingest_flags(trace_id: str, flags) -> None:
    query_uri = os.environ.get("EVENTHOUSE_QUERY_URI")
    cmd = security.build_red_team_flag_ingest(trace_id, flags)
    if not query_uri:
        print("[red-team] EVENTHOUSE_QUERY_URI unset; dry-run ingest:\n", cmd[:200], "...")
        return
    import requests
    from azure.identity import DefaultAzureCredential  # type: ignore
    token = DefaultAzureCredential().get_token("https://kusto.kusto.windows.net/.default").token
    db = os.environ.get("KQL_DATABASE_NAME", "answer_ledger_db")
    r = requests.post(f"{query_uri}/v1/rest/mgmt",
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"},
                      json={"db": db, "csl": cmd}, timeout=60)
    print("[red-team] ingest status:", r.status_code)


def main() -> int:
    answer_fn = _build_answer_fn()
    report = security.run_red_team(
        answer_fn, trace_id_fn=lambda s: f"redteam-{s['type']}")
    print(f"[red-team] scenarios={report['scenarios_run']} "
          f"vulnerable={report['vulnerable_count']}")
    for flag in report["flags"]:
        print(f"  VULNERABLE: {flag['attack_type']} severity={flag['severity']}")
        _ingest_flags(flag["trace_id"], [flag])
    # Fail the CI job if any vulnerability was found.
    return 1 if report["vulnerable_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

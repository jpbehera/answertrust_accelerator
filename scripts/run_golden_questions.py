#!/usr/bin/env python3
"""run_golden_questions.py — golden-question harness for the AnswerTrust demo.

Two modes:
  • validate  (default): structural/static validation of golden_questions.json — used by CI.
                Verifies each entry has a unique trace_id, a question, an expected_sql_pattern
                list, and a well-formed expected_answer assertion. Exits non-zero on any failure.
  • run       : invokes the live BusinessMetricsAgent for each question and applies the
                continuous-eval gate (M6). Requires Fabric/Foundry credentials; skips
                gracefully (exit 0) when they are absent so local/CI runs never hard-fail.

Local-first: `validate` needs no cloud access and is what the nightly CI workflow runs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden_questions.json"

_VALID_ANSWER_TYPES = {"numeric", "percentage", "entity", "table", "boolean", "categorical"}


def _load() -> dict:
    with GOLDEN.open() as f:
        return json.load(f)


def validate(doc: dict) -> list[str]:
    """Return a list of validation errors (empty == pass)."""
    errors: list[str] = []
    questions = doc.get("questions", [])
    if not questions:
        return ["no questions found in golden_questions.json"]

    seen: set[str] = set()
    for i, q in enumerate(questions):
        tag = q.get("trace_id", f"<index {i}>")
        if not q.get("trace_id"):
            errors.append(f"{tag}: missing trace_id")
        elif q["trace_id"] in seen:
            errors.append(f"{tag}: duplicate trace_id")
        else:
            seen.add(q["trace_id"])

        if not q.get("question"):
            errors.append(f"{tag}: missing question text")

        patterns = q.get("expected_sql_pattern")
        if not isinstance(patterns, list) or not patterns:
            errors.append(f"{tag}: expected_sql_pattern must be a non-empty list")

        ans = q.get("expected_answer")
        if not isinstance(ans, dict):
            errors.append(f"{tag}: expected_answer must be an object")
            continue
        atype = ans.get("type")
        if atype not in _VALID_ANSWER_TYPES:
            errors.append(f"{tag}: expected_answer.type '{atype}' not in {sorted(_VALID_ANSWER_TYPES)}")
        # min/max bounds are optional, but when both are present they must be ordered.
        if atype in ("numeric", "percentage"):
            lo, hi = ans.get("min"), ans.get("max")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
                errors.append(f"{tag}: min ({lo}) > max ({hi})")
        elif atype == "table":
            lo, hi = ans.get("min_rows"), ans.get("max_rows")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
                errors.append(f"{tag}: min_rows ({lo}) > max_rows ({hi})")

    return errors


def _agent_available() -> bool:
    return bool(os.environ.get("FABRIC_WORKSPACE_ID") and os.environ.get("FOUNDRY_PROJECT_ID"))


def run_live(doc: dict) -> int:
    """Invoke the live agent + eval gate. Skips when creds are absent."""
    if not _agent_available():
        print("Live agent credentials not set (FABRIC_WORKSPACE_ID/FOUNDRY_PROJECT_ID) — skipping live run.")
        return 0
    try:
        from foundry_wrapper import answer_with_trace  # type: ignore
        from governance import continuous_eval          # type: ignore
    except Exception as exc:  # pragma: no cover - optional cloud deps
        print(f"Live run modules unavailable ({exc}) — skipping.")
        return 0

    failures = 0
    for q in doc["questions"]:
        try:
            result = answer_with_trace(q["question"], trace_id=q["trace_id"])
            verdict = continuous_eval(result, q)
            ok = bool(verdict.get("passed", False))
        except Exception as exc:  # pragma: no cover
            ok, verdict = False, {"error": str(exc)}
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  [{status}] {q['trace_id']}: {q['question']}")
    print(f"\nLive eval: {len(doc['questions']) - failures}/{len(doc['questions'])} passed.")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "validate"
    doc = _load()

    if mode == "validate":
        errors = validate(doc)
        if errors:
            print("Golden-question validation FAILED:")
            for e in errors:
                print(f"  - {e}")
            return 1
        print(f"Golden-question validation PASSED: {len(doc['questions'])} questions OK.")
        return 0

    if mode == "run":
        errors = validate(doc)
        if errors:
            print("Refusing to run: golden_questions.json is invalid.")
            for e in errors:
                print(f"  - {e}")
            return 1
        return run_live(doc)

    print(f"Unknown mode '{mode}'. Use 'validate' or 'run'.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

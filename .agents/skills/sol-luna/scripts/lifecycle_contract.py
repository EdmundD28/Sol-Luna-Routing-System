#!/usr/bin/env python3
"""Replay a deterministic Sol-Luna package lifecycle for behavioral verification."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
TERMINAL = {"ACCEPTED", "FAILED", "BLOCKED", "CANCELLED", "SOL_RECLAIMED"}


class LifecycleError(ValueError):
    """A lifecycle event is illegal for the current package state."""


def initial_state(package_id: str, effort: str) -> dict[str, Any]:
    if not isinstance(package_id, str) or not package_id:
        raise LifecycleError("package_id is required")
    if effort not in EFFORTS:
        raise LifecycleError(f"unsupported effort: {effort}")
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id,
        "status": "PLANNED",
        "effort": effort,
        "candidate_generation": 0,
        "evidence_generation": None,
        "focused_repairs_used": 0,
        "effort_escalations_used": 0,
        "continuation_ref": None,
        "history": [],
    }


def require_bool(event: Mapping[str, Any], field: str) -> bool:
    value = event.get(field)
    if not isinstance(value, bool):
        raise LifecycleError(f"{field} must be boolean")
    return value


def transition(source: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping) or source.get("schema_version") != SCHEMA_VERSION:
        raise LifecycleError("invalid lifecycle state")
    if not isinstance(event, Mapping) or not isinstance(event.get("type"), str):
        raise LifecycleError("event.type is required")
    state = deepcopy(dict(source))
    kind = str(event["type"])
    status = str(state["status"])
    if status in TERMINAL:
        raise LifecycleError(f"terminal state {status} cannot accept {kind}")

    if kind == "dispatch":
        if status != "PLANNED":
            raise LifecycleError("dispatch requires PLANNED")
        state["status"] = "RUNNING"
    elif kind == "handoff":
        if status != "RUNNING":
            raise LifecycleError("handoff requires RUNNING")
        state["status"] = "AWAITING_REVIEW"
        state["candidate_generation"] += 1
        state["evidence_generation"] = (
            state["candidate_generation"] if require_bool(event, "authoritative_checks_passed") else None
        )
        continuation = event.get("continuation_ref")
        state["continuation_ref"] = continuation if isinstance(continuation, str) and continuation else None
    elif kind == "candidate_changed":
        if status not in {"AWAITING_REVIEW", "NEEDS_ACTION"}:
            raise LifecycleError("candidate_changed requires a handed-off candidate")
        state["candidate_generation"] += 1
        state["evidence_generation"] = None
        state["status"] = "AWAITING_REVIEW"
    elif kind == "refresh_evidence":
        if status != "AWAITING_REVIEW":
            raise LifecycleError("refresh_evidence requires AWAITING_REVIEW")
        state["evidence_generation"] = state["candidate_generation"]
    elif kind == "review_pass":
        if status != "AWAITING_REVIEW":
            raise LifecycleError("review_pass requires AWAITING_REVIEW")
        if state["evidence_generation"] != state["candidate_generation"]:
            raise LifecycleError("acceptance evidence is stale or missing")
        if not require_bool(event, "ownership_passed"):
            raise LifecycleError("ownership compliance failed")
        state["status"] = "ACCEPTED"
    elif kind == "review_fail":
        if status != "AWAITING_REVIEW":
            raise LifecycleError("review_fail requires AWAITING_REVIEW")
        state["status"] = "NEEDS_ACTION"
    elif kind == "focused_repair":
        if status != "NEEDS_ACTION":
            raise LifecycleError("focused_repair requires NEEDS_ACTION")
        if state["focused_repairs_used"] >= 1:
            raise LifecycleError("focused repair budget exhausted")
        if not require_bool(event, "new_evidence"):
            raise LifecycleError("focused repair requires new evidence")
        state["focused_repairs_used"] += 1
        state["status"] = "RUNNING"
        state["evidence_generation"] = None
    elif kind == "continue_repair":
        if status != "NEEDS_ACTION" or not state.get("continuation_ref"):
            raise LifecycleError("continue_repair requires a retained continuation after review failure")
        if state["focused_repairs_used"] >= 1 or not require_bool(event, "new_evidence"):
            raise LifecycleError("continuation must obey the one-repair evidence budget")
        state["focused_repairs_used"] += 1
        state["status"] = "RUNNING"
        state["evidence_generation"] = None
    elif kind == "repartition":
        if status != "NEEDS_ACTION":
            raise LifecycleError("repartition requires NEEDS_ACTION")
        state["status"] = "PLANNED"
        state["continuation_ref"] = None
    elif kind == "escalate":
        if status != "NEEDS_ACTION":
            raise LifecycleError("escalate requires NEEDS_ACTION")
        if state["effort_escalations_used"] >= 1:
            raise LifecycleError("effort escalation budget exhausted")
        current = EFFORTS.index(state["effort"])
        if current + 1 >= len(EFFORTS):
            raise LifecycleError("max effort cannot escalate")
        requested = event.get("next_effort", EFFORTS[current + 1])
        if requested != EFFORTS[current + 1]:
            raise LifecycleError("escalation must move exactly one effort level")
        state["effort"] = requested
        state["effort_escalations_used"] += 1
        state["status"] = "RUNNING"
        state["evidence_generation"] = None
    elif kind == "timeout":
        if status != "RUNNING":
            raise LifecycleError("timeout requires RUNNING")
        state["status"] = "FAILED"
    elif kind == "blocked":
        state["status"] = "BLOCKED"
    elif kind == "cancel":
        state["status"] = "CANCELLED"
    elif kind == "sol_reclaim":
        if status != "NEEDS_ACTION":
            raise LifecycleError("sol_reclaim requires NEEDS_ACTION")
        state["status"] = "SOL_RECLAIMED"
    else:
        raise LifecycleError(f"unsupported lifecycle event: {kind}")
    state["history"].append(kind)
    return state


def replay(document: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(document, Mapping) or document.get("schema_version") != SCHEMA_VERSION:
        raise LifecycleError("unsupported replay schema_version")
    state = initial_state(str(document.get("package_id", "")), str(document.get("initial_effort", "")))
    events = document.get("events")
    if not isinstance(events, list):
        raise LifecycleError("events must be a JSON array")
    for event in events:
        state = transition(state, event)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a Sol-Luna package lifecycle contract.")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    try:
        output = replay(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, LifecycleError) as exc:
        print(f"lifecycle contract error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

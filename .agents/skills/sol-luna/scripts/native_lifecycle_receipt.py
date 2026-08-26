#!/usr/bin/env python3
"""Validate a host-produced receipt for real Codex child lifecycle behavior."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
SANDBOXES = {"read-only", "workspace-write"}
REQUIRED_EVENTS = {
    "delegation",
    "timeout",
    "ownership_conflict",
    "stale_evidence",
    "focused_repair",
    "continuation",
}
REDACTED_CHILD = re.compile(r"redacted:child:[0-9a-f]{16}")
PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:\\|/Users/|/home/|\\\\[^\\]+\\)")


class ReceiptError(ValueError):
    """A native lifecycle receipt is incomplete, unverifiable, or inconsistent."""


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptError(f"{field} must be a JSON object")
    return value


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ReceiptError(f"{field} must be a non-empty single-line string")
    result = value.strip()
    if PRIVATE_PATH.search(result):
        raise ReceiptError(f"{field} must not contain a private filesystem path")
    return result


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReceiptError(f"{field} must be boolean")
    return value


def child_ref(value: Any, field: str) -> str:
    result = require_string(value, field)
    if not REDACTED_CHILD.fullmatch(result):
        raise ReceiptError(f"{field} must be a redacted child reference")
    return result


def validate_child(raw: Mapping[str, Any], index: int) -> dict[str, Any]:
    child = require_object(raw, f"children[{index}]")
    unsupported = set(child) - {"child_ref", "requested", "observed", "custom_profile_loaded"}
    if unsupported:
        raise ReceiptError(f"children[{index}] has unsupported fields: {sorted(unsupported)}")
    requested = require_object(child.get("requested"), f"children[{index}].requested")
    observed = require_object(child.get("observed"), f"children[{index}].observed")
    expected_fields = {"agent_role", "model", "effort", "sandbox_mode", "permission_profile"}
    if set(requested) != expected_fields or set(observed) != expected_fields:
        raise ReceiptError("requested and observed child fields must exactly match the identity/boundary contract")
    normalized: dict[str, Any] = {
        "child_ref": child_ref(child.get("child_ref"), f"children[{index}].child_ref"),
        "requested": {},
        "observed": {},
        "custom_profile_loaded": require_bool(
            child.get("custom_profile_loaded"), f"children[{index}].custom_profile_loaded"
        ),
    }
    for field in sorted(expected_fields):
        normalized["requested"][field] = require_string(
            requested.get(field), f"children[{index}].requested.{field}"
        )
        normalized["observed"][field] = require_string(
            observed.get(field), f"children[{index}].observed.{field}"
        )
    if normalized["requested"] != normalized["observed"]:
        raise ReceiptError(f"children[{index}] host-observed identity or boundary does not match the request")
    if normalized["observed"]["model"] != "gpt-5.6-luna":
        raise ReceiptError(f"children[{index}] did not run GPT-5.6 Luna")
    if normalized["observed"]["effort"] not in EFFORTS:
        raise ReceiptError(f"children[{index}] has unsupported observed effort")
    if normalized["observed"]["sandbox_mode"] not in SANDBOXES:
        raise ReceiptError(f"children[{index}] has unsupported observed sandbox_mode")
    if not normalized["custom_profile_loaded"]:
        raise ReceiptError(f"children[{index}] custom profile loading was not host-proven")
    return normalized


def event_map(events: Any, children: set[str]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(events, list):
        raise ReceiptError("events must be a JSON array")
    by_type: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(events):
        event = require_object(raw, f"events[{index}]")
        kind = require_string(event.get("type"), f"events[{index}].type")
        if kind in by_type:
            raise ReceiptError(f"duplicate lifecycle event: {kind}")
        by_type[kind] = event
        if kind != "ownership_conflict":
            reference = child_ref(event.get("child_ref"), f"events[{index}].child_ref")
            if reference not in children:
                raise ReceiptError(f"events[{index}] names an unknown child")
    missing = REQUIRED_EVENTS - set(by_type)
    unsupported = set(by_type) - REQUIRED_EVENTS
    if missing or unsupported:
        raise ReceiptError(f"lifecycle events missing={sorted(missing)} unsupported={sorted(unsupported)}")
    return by_type


def validate_receipt(source: Mapping[str, Any]) -> dict[str, Any]:
    source = require_object(source, "receipt")
    if set(source) != {"schema_version", "runtime", "children", "events"}:
        raise ReceiptError("receipt fields must be schema_version, runtime, children, and events")
    if source.get("schema_version") != SCHEMA_VERSION:
        raise ReceiptError("unsupported receipt schema_version")
    if require_string(source.get("runtime"), "runtime") != "codex-native":
        raise ReceiptError("runtime must be codex-native")
    raw_children = source.get("children")
    if not isinstance(raw_children, list) or not raw_children:
        raise ReceiptError("children must be a non-empty JSON array")
    children = [validate_child(require_object(item, f"children[{index}]"), index) for index, item in enumerate(raw_children)]
    refs = [item["child_ref"] for item in children]
    if len(refs) != len(set(refs)):
        raise ReceiptError("child_ref values must be unique")
    events = event_map(source.get("events"), set(refs))

    delegation = events["delegation"]
    if delegation.get("status") != "COMPLETED":
        raise ReceiptError("delegation must complete")
    repair = events["focused_repair"]
    if repair.get("repair_round") != 1 or repair.get("authoritative_check") != "PASSED":
        raise ReceiptError("focused repair must be round 1 with a passed authoritative check")
    if repair.get("child_ref") != delegation.get("child_ref"):
        raise ReceiptError("focused repair must continue the delegated child")
    stale = events["stale_evidence"]
    if stale.get("acceptance") != "REJECTED_STALE" or stale.get("old_generation") == stale.get("new_generation"):
        raise ReceiptError("candidate change must produce REJECTED_STALE")
    if stale.get("child_ref") != delegation.get("child_ref"):
        raise ReceiptError("stale-evidence check must bind to the delegated child")
    timeout = events["timeout"]
    if timeout.get("prior_status") != "RUNNING" or timeout.get("interrupted") is not True:
        raise ReceiptError("timeout must interrupt a child observed RUNNING")
    deadline = timeout.get("deadline_seconds")
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or deadline <= 0:
        raise ReceiptError("timeout deadline_seconds must be positive")
    continuation = events["continuation"]
    if continuation.get("status") != "PASSED" or continuation.get("after") != "timeout":
        raise ReceiptError("continuation must pass after timeout")
    if continuation.get("child_ref") != timeout.get("child_ref"):
        raise ReceiptError("post-timeout continuation must reuse the interrupted child")
    conflict = events["ownership_conflict"]
    if (
        conflict.get("guard_status") != "FAIL"
        or conflict.get("parallel_writes_allowed") is not False
        or conflict.get("dispatched_writers") != 0
    ):
        raise ReceiptError("ownership conflict must block every proposed writer before dispatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "runtime": "codex-native",
        "verified_children": len(children),
        "verified_events": sorted(REQUIRED_EVENTS),
        "native_lifecycle_proven": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a host-produced native Codex lifecycle receipt.")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    try:
        output = validate_receipt(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ReceiptError) as exc:
        print(f"native lifecycle receipt error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

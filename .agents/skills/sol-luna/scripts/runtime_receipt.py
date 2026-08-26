#!/usr/bin/env python3
"""Build a redacted runtime receipt from one explicit Codex session JSONL file."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable


class ReceiptError(ValueError):
    """The supplied runtime evidence cannot identify the requested session."""


IDENTITY_FIELDS = ("agent_role", "model", "effort")
BOUNDARY_FIELDS = ("sandbox_policy_type", "permission_profile_type")


def redacted_ref(value: str, prefix: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"redacted:{prefix}:{digest}"


def load_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    invalid_lines = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ReceiptError(f"cannot read session JSONL: {exc}") from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            invalid_lines += 1
    if not events:
        raise ReceiptError("session JSONL contains no readable object events")
    return events, invalid_lines


def nested_type(value: Any) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("type")
        return candidate if isinstance(candidate, str) and candidate else None
    return value if isinstance(value, str) and value else None


def observed_field(values: Iterable[Any], *, redact_as: str | None = None) -> dict[str, Any]:
    cleaned = [value for value in values if isinstance(value, str) and value]
    unique = list(dict.fromkeys(cleaned))
    if not unique:
        return {"value": None, "provenance": "unknown", "issue": "not present in host record"}
    if len(unique) > 1:
        displayed = [redacted_ref(value, redact_as) for value in unique] if redact_as else unique
        return {
            "value": None,
            "provenance": "unknown",
            "issue": "conflicting host-observed values",
            "observed_values": displayed,
        }
    value = redacted_ref(unique[0], redact_as) if redact_as else unique[0]
    return {"value": value, "provenance": "host_observed"}


def requested_field(value: str | None) -> dict[str, Any]:
    if value:
        return {"value": value, "provenance": "requested"}
    return {"value": None, "provenance": "unknown", "issue": "not supplied to receipt tool"}


def build_receipt(
    session_path: Path,
    thread_id: str,
    *,
    requested_agent: str | None = None,
    requested_model: str | None = None,
    requested_effort: str | None = None,
    expected_sandbox: str | None = None,
    expected_permission_profile: str | None = None,
    include_identifiers: bool = False,
) -> dict[str, Any]:
    events, invalid_lines = load_events(session_path)
    sessions = [
        event.get("payload")
        for event in events
        if event.get("type") == "session_meta" and isinstance(event.get("payload"), dict)
    ]
    if len(sessions) != 1:
        raise ReceiptError(
            f"expected an explicit single-session JSONL file, found {len(sessions)} session_meta records"
        )
    matching = [payload for payload in sessions if payload.get("id") == thread_id]
    if len(matching) != 1:
        raise ReceiptError(
            f"expected exactly one session_meta for the requested thread, found {len(matching)}"
        )
    session = matching[0]
    turns = [
        event.get("payload")
        for event in events
        if event.get("type") == "turn_context" and isinstance(event.get("payload"), dict)
    ]

    observed = {
        "agent_role": observed_field([session.get("agent_role")]),
        "agent_path_ref": observed_field(
            [session.get("agent_path")], redact_as=None if include_identifiers else "agent-path"
        ),
        "model_provider": observed_field([session.get("model_provider")]),
        "model": observed_field(turn.get("model") for turn in turns),
        "effort": observed_field(turn.get("effort") for turn in turns),
        "sandbox_policy_type": observed_field(
            nested_type(turn.get("sandbox_policy")) for turn in turns
        ),
        "permission_profile_type": observed_field(
            nested_type(turn.get("permission_profile")) for turn in turns
        ),
        "cwd_ref": observed_field(
            (turn.get("cwd") for turn in turns),
            redact_as=None if include_identifiers else "cwd",
        ),
    }
    requested = {
        "agent": requested_field(requested_agent),
        "model": requested_field(requested_model),
        "effort": requested_field(requested_effort),
        "sandbox_policy_type": requested_field(expected_sandbox),
        "permission_profile_type": requested_field(expected_permission_profile),
    }

    mismatches: list[str] = []
    comparisons = (
        ("agent", "agent_role"),
        ("model", "model"),
        ("effort", "effort"),
        ("sandbox_policy_type", "sandbox_policy_type"),
        ("permission_profile_type", "permission_profile_type"),
    )
    for requested_name, observed_name in comparisons:
        expected = requested[requested_name].get("value")
        actual = observed[observed_name].get("value")
        if expected is not None and actual is not None and expected != actual:
            mismatches.append(f"requested {requested_name} does not match host-observed {observed_name}")

    conflict = any(field.get("issue") == "conflicting host-observed values" for field in observed.values())
    missing_identity = [name for name in IDENTITY_FIELDS if observed[name]["provenance"] != "host_observed"]
    missing_boundary = [name for name in BOUNDARY_FIELDS if observed[name]["provenance"] != "host_observed"]
    source_warnings: list[str] = []
    if invalid_lines:
        source_warnings.append("session JSONL contains unreadable lines")
    if conflict or mismatches:
        status = "conflicted"
    elif missing_identity or missing_boundary or source_warnings:
        status = "partial"
    else:
        status = "verified"

    return {
        "schema_version": 1,
        "status": status,
        "thread_ref": thread_id if include_identifiers else redacted_ref(thread_id, "thread"),
        "source_ref": str(session_path) if include_identifiers else redacted_ref(str(session_path), "session"),
        "source_kind": "explicit_session_jsonl",
        "invalid_jsonl_lines": invalid_lines,
        "source_warnings": source_warnings,
        "requested": requested,
        "host_observed": observed,
        "mismatches": mismatches,
        "unknown_identity_fields": missing_identity,
        "unknown_boundary_fields": missing_boundary,
        "self_report_used_as_proof": False,
    }


def enforce_requirements(receipt: dict[str, Any], *, require_identity: bool, require_boundary: bool) -> None:
    failures: list[str] = []
    if receipt["mismatches"]:
        failures.extend(receipt["mismatches"])
    if require_identity and receipt["unknown_identity_fields"]:
        failures.append("required identity fields are unknown or conflicting")
    if require_identity:
        missing_expected = [
            name for name in ("agent", "model", "effort") if receipt["requested"][name]["value"] is None
        ]
        if missing_expected:
            failures.append(f"strict identity requires expected values for: {', '.join(missing_expected)}")
    if require_boundary and receipt["unknown_boundary_fields"]:
        failures.append("required boundary fields are unknown or conflicting")
    if require_boundary:
        missing_expected = [
            name
            for name in ("sandbox_policy_type", "permission_profile_type")
            if receipt["requested"][name]["value"] is None
        ]
        if missing_expected:
            failures.append(f"strict boundary requires expected values for: {', '.join(missing_expected)}")
    if (require_identity or require_boundary) and receipt["source_warnings"]:
        failures.append("strict runtime proof requires a fully readable session record")
    if failures:
        raise ReceiptError("; ".join(failures))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Read one explicit Codex session JSONL and emit an allowlisted, redacted runtime receipt."
    )
    result.add_argument("--session", required=True, type=Path)
    result.add_argument("--thread-id", required=True)
    result.add_argument("--requested-agent")
    result.add_argument("--requested-model")
    result.add_argument("--requested-effort")
    result.add_argument("--expected-sandbox")
    result.add_argument("--expected-permission-profile")
    result.add_argument("--require-identity", action="store_true")
    result.add_argument("--require-boundary", action="store_true")
    result.add_argument("--include-identifiers", action="store_true")
    result.add_argument("--output", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        receipt = build_receipt(
            args.session,
            args.thread_id,
            requested_agent=args.requested_agent,
            requested_model=args.requested_model,
            requested_effort=args.requested_effort,
            expected_sandbox=args.expected_sandbox,
            expected_permission_profile=args.expected_permission_profile,
            include_identifiers=args.include_identifiers,
        )
        enforce_requirements(
            receipt,
            require_identity=args.require_identity,
            require_boundary=args.require_boundary,
        )
    except ReceiptError as exc:
        print(f"runtime receipt error: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

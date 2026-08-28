#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Validate a frozen Sol-Luna delegation envelope and its final handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

SCHEMA_VERSION = 1
ROUTE = "SOL_LUNA"
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
ACTION_KINDS = {"repo_read", "implementation", "targeted_test", "closeout"}
REPLAY_REASONS = {"discrepancy", "safety_risk", "nondeterminism", "candidate_drift"}
PRIVATE_SEGMENTS = {
    ".aws", ".azure", ".gnupg", ".kube", ".ssh", "credentials", "credentials.json",
    "id-dsa", "id-ecdsa", "id-ed25519", "id-rsa", "secrets",
}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10)
}


class ContractError(ValueError):
    """The delegation contract is malformed or has failed a delivery gate."""


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON constant is not allowed: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be a JSON object")
    return value


def _fields(value: Mapping[str, Any], allowed: set[str], required: set[str], field: str) -> None:
    if any(not isinstance(key, str) for key in value):
        raise ContractError(f"{field} keys must be strings")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ContractError(f"{field} has unsupported fields: {sorted(unknown)}")
    if missing:
        raise ContractError(f"{field} is missing required fields: {sorted(missing)}")


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(f"{field} must be a compact hyphen-case identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ContractError(f"{field} must be sha256 followed by 64 lowercase hex characters")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\n" in value or "\r" in value:
        raise ContractError(f"{field} must be a non-empty single-line string")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field} must be a boolean")
    return value


def _path(value: Any, field: str) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or "\n" in value or "\r" in value or "\x00" in value or "\\" in value
        or ":" in value
    ):
        raise ContractError(f"{field} must be a normalized repository-relative path")
    if (
        value.startswith("~") or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute() or re.match(r"^[A-Za-z]:", value)
    ):
        raise ContractError(f"{field} must be repository-relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ContractError(f"{field} contains an unsafe path segment")
    if any(part[-1] in ". " for part in parts):
        raise ContractError(f"{field} contains a Windows-unsafe trailing character")
    if any(part.casefold().split(".", 1)[0] in WINDOWS_RESERVED for part in parts):
        raise ContractError(f"{field} contains a reserved Windows device name")
    if any(part.casefold() in PRIVATE_SEGMENTS for part in parts):
        raise ContractError(f"{field} contains a sensitive private path")
    return "/".join(PurePosixPath(value).parts)


def _paths(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"{field} must be {'a' if allow_empty else 'a non-empty'} JSON array")
    result = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise ContractError(f"{field} contains duplicate paths")
    for index, left in enumerate(result):
        for right in result[index + 1 :]:
            left_folded, right_folded = left.casefold(), right.casefold()
            if (
                left_folded == right_folded
                or left_folded.startswith(right_folded + "/")
                or right_folded.startswith(left_folded + "/")
            ):
                raise ContractError(f"{field} contains prefix-overlapping paths")
    return sorted(result)


def _replacement_scope(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{field} must be a non-empty JSON array")
    if any(not isinstance(item, str) or item not in ACTION_KINDS for item in value):
        raise ContractError(f"{field} must contain only supported action kinds")
    if len(value) != len(set(value)):
        raise ContractError(f"{field} contains duplicate action kinds")
    return sorted(value)


def _ids(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"{field} must be {'a' if allow_empty else 'a non-empty'} JSON array")
    result = [_id(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ContractError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _contains(scope: list[str], path: str) -> bool:
    folded_path = path.casefold()
    return any(
        folded_path == root.casefold() or folded_path.startswith(root.casefold() + "/")
        for root in scope
    )


def allocation_fingerprint(source: Mapping[str, Any]) -> str:
    """Return the canonical digest of the frozen outer allocation envelope."""
    envelope = _object(source["envelope"], "envelope")
    payload = {
        "schema_version": source["schema_version"],
        "route": source["route"],
        "task_digest": source["task_digest"],
        "executor_id": source["executor_id"],
        "worker_context_id": source["worker_context_id"],
        "write_scope": sorted(envelope["write_scope"]),
        "acceptance_ids": sorted(envelope["acceptance_ids"]),
        "replacement_scope": sorted(envelope["replacement_scope"]),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _action(raw: Any, field: str) -> dict[str, str]:
    item = _object(raw, field)
    fields = {"action_id", "kind"}
    _fields(item, fields, fields, field)
    action_id = _id(item.get("action_id"), f"{field}.action_id")
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in ACTION_KINDS:
        raise ContractError(f"{field}.kind must be one of {sorted(ACTION_KINDS)}")
    return {"action_id": action_id, "kind": kind}


def _validate(source: Mapping[str, Any]) -> dict[str, Any]:
    top = {
        "schema_version", "route", "task_digest", "allocation_digest", "executor_id",
        "worker_context_id", "envelope", "handoff", "sol_verification",
    }
    _fields(source, top, top, "contract")
    if type(source["schema_version"]) is not int or source["schema_version"] != SCHEMA_VERSION:
        raise ContractError("schema_version must be integer 1")
    if source["route"] != ROUTE or not isinstance(source["route"], str):
        raise ContractError("route must be SOL_LUNA")
    task_digest = _digest(source["task_digest"], "task_digest")
    allocation_digest = _digest(source["allocation_digest"], "allocation_digest")
    executor_id = _id(source["executor_id"], "executor_id")
    worker_context_id = _id(source["worker_context_id"], "worker_context_id")

    envelope = _object(source["envelope"], "envelope")
    envelope_fields = {"write_scope", "acceptance_ids", "replacement_scope", "units"}
    _fields(envelope, envelope_fields, envelope_fields, "envelope")
    write_scope = _paths(envelope["write_scope"], "envelope.write_scope")
    acceptance_ids = _ids(envelope["acceptance_ids"], "envelope.acceptance_ids")
    replacement_scope = _replacement_scope(envelope["replacement_scope"], "envelope.replacement_scope")
    expected_allocation_digest = allocation_fingerprint({
        "schema_version": SCHEMA_VERSION,
        "route": ROUTE,
        "task_digest": task_digest,
        "executor_id": executor_id,
        "worker_context_id": worker_context_id,
        "envelope": {
            "write_scope": write_scope,
            "acceptance_ids": acceptance_ids,
            "replacement_scope": replacement_scope,
        },
    })
    if allocation_digest != expected_allocation_digest:
        raise ContractError("allocation_digest does not match the frozen outer envelope")
    raw_units = envelope["units"]
    if not isinstance(raw_units, list) or not raw_units:
        raise ContractError("envelope.units must be a non-empty JSON array")
    units: list[dict[str, Any]] = []
    units_by_id: dict[str, dict[str, Any]] = {}
    action_ids: set[str] = set()
    actions: list[dict[str, str]] = []
    for index, raw in enumerate(raw_units):
        item = _object(raw, f"envelope.units[{index}]")
        fields = {"unit_id", "depends_on", "changed_paths", "replacement_actions"}
        _fields(item, fields, fields, f"envelope.units[{index}]")
        unit_id = _id(item["unit_id"], f"envelope.units[{index}].unit_id")
        if unit_id in units_by_id:
            raise ContractError(f"duplicate unit_id: {unit_id}")
        depends_on = _ids(item["depends_on"], f"envelope.units[{index}].depends_on", allow_empty=True)
        changed_paths = _paths(item["changed_paths"], f"envelope.units[{index}].changed_paths", allow_empty=True)
        unit_actions = item["replacement_actions"]
        if not isinstance(unit_actions, list):
            raise ContractError(f"envelope.units[{index}].replacement_actions must be a JSON array")
        normalized_actions = []
        for action_index, action in enumerate(unit_actions):
            normalized = _action(action, f"envelope.units[{index}].replacement_actions[{action_index}]")
            if normalized["action_id"] in action_ids:
                raise ContractError(f"duplicate action_id: {normalized['action_id']}")
            action_ids.add(normalized["action_id"])
            normalized_actions.append(normalized)
            actions.append(normalized)
        normalized_unit = {
            "unit_id": unit_id, "depends_on": depends_on, "changed_paths": changed_paths,
            "replacement_actions": normalized_actions,
        }
        units_by_id[unit_id] = normalized_unit
        units.append(normalized_unit)
    if not actions:
        raise ContractError("at least one replacement action is required")
    action_kinds = {action["kind"] for action in actions}
    if action_kinds != set(replacement_scope):
        raise ContractError("replacement_actions must cover replacement_scope exactly")
    unit_ids = set(units_by_id)
    for unit in units:
        unknown = set(unit["depends_on"]) - unit_ids
        if unknown:
            raise ContractError(f"{unit['unit_id']} has unknown dependencies: {sorted(unknown)}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(unit_id: str) -> None:
        if unit_id in visiting:
            raise ContractError("envelope.units contains a dependency cycle")
        if unit_id in visited:
            return
        visiting.add(unit_id)
        for dependency in units_by_id[unit_id]["depends_on"]:
            visit(dependency)
        visiting.remove(unit_id)
        visited.add(unit_id)

    for unit_id in unit_ids:
        visit(unit_id)
    units.sort(key=lambda item: item["unit_id"])
    for unit in units:
        if any(not _contains(write_scope, path) for path in unit["changed_paths"]):
            raise ContractError(f"unit {unit['unit_id']} changed_paths exceed envelope.write_scope")

    handoff = _object(source["handoff"], "handoff")
    handoff_fields = {
        "candidate_digest", "changed_paths", "acceptance_results", "closeout_complete", "residual_risks",
    }
    _fields(handoff, handoff_fields, handoff_fields, "handoff")
    candidate_digest = _digest(handoff["candidate_digest"], "handoff.candidate_digest")
    handoff_paths = _paths(handoff["changed_paths"], "handoff.changed_paths", allow_empty=True)
    unit_paths = sorted({path for unit in units for path in unit["changed_paths"]})
    unit_path_keys = [path.casefold() for path in unit_paths]
    if len(unit_path_keys) != len(set(unit_path_keys)):
        raise ContractError("unit.changed_paths contains case-insensitive duplicates")
    if {path.casefold() for path in handoff_paths} != set(unit_path_keys):
        raise ContractError("handoff.changed_paths must equal the union of unit.changed_paths")
    results_source = handoff["acceptance_results"]
    if not isinstance(results_source, list):
        raise ContractError("handoff.acceptance_results must be a JSON array")
    results: list[dict[str, Any]] = []
    seen_acceptance: set[str] = set()
    acceptance_set = set(acceptance_ids)
    for index, raw in enumerate(results_source):
        item = _object(raw, f"handoff.acceptance_results[{index}]")
        fields = {
            "acceptance_id", "candidate_digest", "command_digest", "result_digest", "exit_code", "deterministic",
        }
        _fields(item, fields, fields, f"handoff.acceptance_results[{index}]")
        acceptance_id = _id(item["acceptance_id"], f"handoff.acceptance_results[{index}].acceptance_id")
        if acceptance_id not in acceptance_set:
            raise ContractError(f"unknown acceptance_id: {acceptance_id}")
        if acceptance_id in seen_acceptance:
            raise ContractError(f"acceptance_id appears more than once: {acceptance_id}")
        seen_acceptance.add(acceptance_id)
        if _digest(item["candidate_digest"], f"handoff.acceptance_results[{index}].candidate_digest") != candidate_digest:
            raise ContractError(f"acceptance {acceptance_id} has a stale candidate_digest")
        _digest(item["command_digest"], f"handoff.acceptance_results[{index}].command_digest")
        _digest(item["result_digest"], f"handoff.acceptance_results[{index}].result_digest")
        if type(item["exit_code"]) is not int or item["exit_code"] != 0:
            raise ContractError(f"acceptance {acceptance_id} must have exit_code 0")
        if item["deterministic"] is not True:
            raise ContractError(f"acceptance {acceptance_id} must be deterministic")
        results.append({
            "acceptance_id": acceptance_id, "candidate_digest": candidate_digest,
            "command_digest": item["command_digest"], "result_digest": item["result_digest"],
            "exit_code": 0, "deterministic": True,
        })
    if seen_acceptance != acceptance_set:
        raise ContractError("acceptance_ids must be covered exactly once")
    if not _bool(handoff["closeout_complete"], "handoff.closeout_complete"):
        raise ContractError("handoff.closeout_complete must be true")
    residual_risks = handoff["residual_risks"]
    if not isinstance(residual_risks, list) or any(
        not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value
        for value in residual_risks
    ):
        raise ContractError("handoff.residual_risks must be a string array")

    verification = _object(source["sol_verification"], "sol_verification")
    verification_fields = {
        "candidate_digest", "independent_acceptance_digest", "independent_acceptance_passed",
        "accepted_unit_ids", "replays",
    }
    _fields(verification, verification_fields, verification_fields, "sol_verification")
    if _digest(verification["candidate_digest"], "sol_verification.candidate_digest") != candidate_digest:
        raise ContractError("sol_verification.candidate_digest does not match handoff")
    _digest(verification["independent_acceptance_digest"], "sol_verification.independent_acceptance_digest")
    if not _bool(verification["independent_acceptance_passed"], "sol_verification.independent_acceptance_passed"):
        raise ContractError("independent acceptance must pass")
    accepted_unit_ids = _ids(verification["accepted_unit_ids"], "sol_verification.accepted_unit_ids")
    if accepted_unit_ids != sorted(unit_ids):
        raise ContractError("sol_verification.accepted_unit_ids must cover every unit exactly once")
    raw_replays = verification["replays"]
    if not isinstance(raw_replays, list):
        raise ContractError("sol_verification.replays must be a JSON array")
    replayed: list[dict[str, str]] = []
    replayed_ids: set[str] = set()
    for index, raw in enumerate(raw_replays):
        item = _object(raw, f"sol_verification.replays[{index}]")
        fields = {"action_id", "reason"}
        _fields(item, fields, fields, f"sol_verification.replays[{index}]")
        action_id = _id(item["action_id"], f"sol_verification.replays[{index}].action_id")
        if action_id not in action_ids:
            raise ContractError(f"replay references an undelivered action: {action_id}")
        if action_id in replayed_ids:
            raise ContractError(f"action replayed more than once: {action_id}")
        reason = item["reason"]
        if not isinstance(reason, str) or reason not in REPLAY_REASONS:
            raise ContractError(f"replay reason must be one of {sorted(REPLAY_REASONS)}")
        replayed_ids.add(action_id)
        replayed.append({"action_id": action_id, "reason": reason})
    replayed.sort(key=lambda item: item["action_id"])
    action_count = len(actions)
    avoided_count = action_count - len(replayed)
    replayed_kind_set = {
        action["kind"] for action in actions if action["action_id"] in replayed_ids
    }
    kind_count = len(replacement_scope)
    avoided_kind_count = kind_count - len(replayed_kind_set)
    return {
        "status": "ACCEPTED",
        "task_digest": task_digest,
        "allocation_digest": allocation_digest,
        "executor_id": executor_id,
        "worker_context_id": worker_context_id,
        "unit_count": len(units),
        "handoff_count": 1,
        "context_reload_count": 1,
        "replacement_action_count": action_count,
        "replacement_kind_count": kind_count,
        "avoided_sol_action_count": avoided_count,
        "sol_shadow_action_count": len(replayed),
        "avoided_sol_kind_count": avoided_kind_count,
        "sol_shadow_kind_count": len(replayed_kind_set),
        "substitution_fraction": avoided_kind_count / kind_count,
        "verification_reuse_fraction": 1 - len(replayed_kind_set) / kind_count,
        "replayed_actions": replayed,
    }


def assess(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ContractError("contract must be a JSON object")
    return _validate(source)


def template() -> dict[str, Any]:
    digest = "sha256:" + "0" * 64
    result = {
        "schema_version": SCHEMA_VERSION,
        "route": ROUTE,
        "task_digest": digest,
        "allocation_digest": digest,
        "executor_id": "luna-one",
        "worker_context_id": "context-one",
        "envelope": {
            "write_scope": ["src/example.py"],
            "acceptance_ids": ["accept-example"],
            "replacement_scope": ["repo_read"],
            "units": [{
                "unit_id": "example-work", "depends_on": [], "changed_paths": ["src/example.py"],
                "replacement_actions": [{"action_id": "read-example", "kind": "repo_read"}],
            }],
        },
        "handoff": {
            "candidate_digest": digest, "changed_paths": ["src/example.py"],
            "acceptance_results": [{
                "acceptance_id": "accept-example", "candidate_digest": digest,
                "command_digest": digest, "result_digest": digest, "exit_code": 0,
                "deterministic": True,
            }],
            "closeout_complete": True, "residual_risks": [],
        },
        "sol_verification": {
            "candidate_digest": digest, "independent_acceptance_digest": digest,
            "independent_acceptance_passed": True, "accepted_unit_ids": ["example-work"],
            "replays": [],
        },
    }
    result["allocation_digest"] = allocation_fingerprint(result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Validate a Sol-Luna delegation contract.")
    sub = result.add_subparsers(dest="command", required=True)
    assess_parser = sub.add_parser("assess")
    assess_parser.add_argument("--input", required=True)
    sub.add_parser("template")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "template":
            output = template()
        else:
            with open(args.input, encoding="utf-8") as handle:
                output = assess(strict_json_loads(handle.read()))
    except (OSError, UnicodeError, ContractError) as exc:
        message = " ".join(str(exc).splitlines())
        print(f"delegation contract error: {message}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

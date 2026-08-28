#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Validate, assess, and project the continuous Luna repair closure contract.

The format is intentionally small and replay-only.  It records authority and
ownership; it never executes a worker, a test, or a Sol action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
EVENTS = {
    "DISPATCH", "SOL_PARALLEL_PROGRESS", "LUNA_HANDOFF", "SOL_ACCEPTANCE_FAIL",
    "OPEN_LUNA_REPAIR", "LUNA_REPAIR_HANDOFF", "SOL_ACCEPTANCE_PASS",
    "SOL_RECLAIM", "CLOSE",
}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10)
}


class ContractError(ValueError):
    """The closure contract is malformed or violates its state machine."""


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


def _positive(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ContractError(f"{field} must be a finite positive number")
    return result


def _path(value: Any, field: str) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or "\n" in value or "\r" in value or "\x00" in value or "\\" in value
        or ":" in value
    ):
        raise ContractError(f"{field} must be a normalized repository-relative path")
    if value.startswith("~") or PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ContractError(f"{field} must be repository-relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ContractError(f"{field} contains an unsafe path segment")
    if any(part[-1] in ". " for part in parts):
        raise ContractError(f"{field} contains a Windows-unsafe trailing character")
    if any(part.casefold().split(".", 1)[0] in WINDOWS_RESERVED for part in parts):
        raise ContractError(f"{field} contains a reserved Windows device name")
    return "/".join(PurePosixPath(value).parts)


def _paths(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"{field} must be {'a' if allow_empty else 'a non-empty'} JSON array")
    result = [_path(item, f"{field}[{i}]") for i, item in enumerate(value)]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise ContractError(f"{field} contains duplicate paths")
    for i, left in enumerate(folded):
        for right in folded[i + 1 :]:
            if left == right or left.startswith(right + "/") or right.startswith(left + "/"):
                raise ContractError(f"{field} contains prefix-overlapping paths")
    return sorted(result)


def _ids(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"{field} must be {'a' if allow_empty else 'a non-empty'} JSON array")
    result = [_id(item, f"{field}[{i}]") for i, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ContractError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _contains(scope: list[str], path: str) -> bool:
    folded = path.casefold()
    return any(folded == root.casefold() or folded.startswith(root.casefold() + "/") for root in scope)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def contract_fingerprint(source: Mapping[str, Any]) -> str:
    value = dict(source)
    value.pop("contract_fingerprint", None)
    return sha256_digest(value)


def _event(raw: Any, index: int) -> dict[str, Any]:
    item = _object(raw, f"events[{index}]")
    common = {"sequence", "event", "actor_id", "candidate_digest"}
    if not common.issubset(item):
        raise ContractError(f"events[{index}] is missing required fields: {sorted(common - set(item))}")
    kind = item.get("event")
    if not isinstance(kind, str) or kind not in EVENTS:
        raise ContractError(f"events[{index}].event is unsupported")
    specs: dict[str, set[str]] = {
        "DISPATCH": set(),
        "SOL_PARALLEL_PROGRESS": {"changed_paths", "workspace_before_digest", "workspace_after_digest", "progress_digest"},
        "LUNA_HANDOFF": {"changed_paths"},
        "SOL_ACCEPTANCE_FAIL": {"acceptance_ids", "changed_paths", "workspace_before_digest", "workspace_after_digest", "failure_evidence_digest"},
        "OPEN_LUNA_REPAIR": {"failure_evidence_digest", "target_unit_ids", "repair_cost_weight", "marginal_net_substitution"},
        "LUNA_REPAIR_HANDOFF": {"target_unit_ids", "changed_paths"},
        "SOL_ACCEPTANCE_PASS": {"acceptance_ids", "changed_paths", "workspace_before_digest", "workspace_after_digest", "result_digest"},
        "SOL_RECLAIM": {"unit_ids", "changed_paths", "reason_digest"},
        "CLOSE": {"unit_dispositions"},
    }
    required = common | specs[kind]
    _fields(item, required, required, f"events[{index}]")
    sequence = item["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence != index + 1:
        raise ContractError("event sequence must be contiguous starting at 1")
    normalized: dict[str, Any] = {
        "sequence": sequence,
        "event": kind,
        "actor_id": _id(item["actor_id"], f"events[{index}].actor_id"),
        "candidate_digest": _digest(item["candidate_digest"], f"events[{index}].candidate_digest"),
    }
    if kind == "DISPATCH" or kind == "CLOSE":
        if kind == "CLOSE":
            raw_dispositions = item["unit_dispositions"]
            if not isinstance(raw_dispositions, list) or not raw_dispositions:
                raise ContractError("events[close].unit_dispositions must be a non-empty JSON array")
            dispositions = []
            for j, raw_disposition in enumerate(raw_dispositions):
                d = _object(raw_disposition, f"events[{index}].unit_dispositions[{j}]")
                _fields(d, {"unit_id", "status"}, {"unit_id", "status"}, f"events[{index}].unit_dispositions[{j}]")
                status = d["status"]
                if status not in {"accepted", "reclaimed"}:
                    raise ContractError("unit disposition status must be accepted or reclaimed")
                dispositions.append({"unit_id": _id(d["unit_id"], "unit disposition unit_id"), "status": status})
            if len({d["unit_id"] for d in dispositions}) != len(dispositions):
                raise ContractError("close contains duplicate unit dispositions")
            normalized["unit_dispositions"] = sorted(dispositions, key=lambda d: d["unit_id"])
        return normalized
    if kind in {"SOL_PARALLEL_PROGRESS", "SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS", "LUNA_HANDOFF", "LUNA_REPAIR_HANDOFF", "SOL_RECLAIM"}:
        allow_empty = kind in {"SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS"}
        normalized["changed_paths"] = _paths(item["changed_paths"], f"events[{index}].changed_paths", allow_empty=allow_empty)
    if kind in {"SOL_PARALLEL_PROGRESS", "SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS"}:
        normalized["workspace_before_digest"] = _digest(item["workspace_before_digest"], f"events[{index}].workspace_before_digest")
        normalized["workspace_after_digest"] = _digest(item["workspace_after_digest"], f"events[{index}].workspace_after_digest")
    if kind == "SOL_PARALLEL_PROGRESS":
        normalized["progress_digest"] = _digest(item["progress_digest"], f"events[{index}].progress_digest")
    if kind in {"SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS"}:
        normalized["acceptance_ids"] = _ids(item["acceptance_ids"], f"events[{index}].acceptance_ids")
    if kind == "SOL_ACCEPTANCE_FAIL":
        normalized["failure_evidence_digest"] = _digest(item["failure_evidence_digest"], f"events[{index}].failure_evidence_digest")
    if kind == "SOL_ACCEPTANCE_PASS":
        normalized["result_digest"] = _digest(item["result_digest"], f"events[{index}].result_digest")
    if kind in {"OPEN_LUNA_REPAIR", "LUNA_REPAIR_HANDOFF"}:
        normalized["target_unit_ids"] = _ids(item["target_unit_ids"], f"events[{index}].target_unit_ids")
    if kind == "OPEN_LUNA_REPAIR":
        normalized["failure_evidence_digest"] = _digest(item["failure_evidence_digest"], f"events[{index}].failure_evidence_digest")
        normalized["repair_cost_weight"] = _positive(item["repair_cost_weight"], f"events[{index}].repair_cost_weight")
        normalized["marginal_net_substitution"] = _positive(item["marginal_net_substitution"], f"events[{index}].marginal_net_substitution")
    if kind == "SOL_RECLAIM":
        normalized["unit_ids"] = _ids(item["unit_ids"], f"events[{index}].unit_ids")
        normalized["reason_digest"] = _digest(item["reason_digest"], f"events[{index}].reason_digest")
    return normalized


def _envelope(raw: Any) -> dict[str, Any]:
    envelope = _object(raw, "envelope")
    fields = {"controller_id", "luna_executor_id", "candidate_start_digest", "repair_budget", "luna_units", "sol_lane_units"}
    _fields(envelope, fields, fields, "envelope")
    result: dict[str, Any] = {
        "controller_id": _id(envelope["controller_id"], "envelope.controller_id"),
        "luna_executor_id": _id(envelope["luna_executor_id"], "envelope.luna_executor_id"),
        "candidate_start_digest": _digest(envelope["candidate_start_digest"], "envelope.candidate_start_digest"),
    }
    budget = _object(envelope["repair_budget"], "envelope.repair_budget")
    _fields(budget, {"max_attempts", "max_cost_weight"}, {"max_attempts", "max_cost_weight"}, "envelope.repair_budget")
    attempts = budget["max_attempts"]
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 3:
        raise ContractError("repair_budget.max_attempts must be an integer from 1 through 3")
    result["repair_budget"] = {"max_attempts": attempts, "max_cost_weight": _positive(budget["max_cost_weight"], "repair_budget.max_cost_weight")}
    luna = envelope["luna_units"]
    sol = envelope["sol_lane_units"]
    if not isinstance(luna, list) or not luna:
        raise ContractError("envelope.luna_units must contain at least one unit")
    if not isinstance(sol, list):
        raise ContractError("envelope.sol_lane_units must be a JSON array")
    def units(value: list[Any], name: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out = []
        for i, raw_unit in enumerate(value):
            unit = _object(raw_unit, f"envelope.{name}[{i}]")
            allowed = {"unit_id", "path_scopes", "acceptance_ids", "baseline_weight"} if name == "luna_units" else {"unit_id", "path_scopes", "acceptance_ids"}
            required = allowed
            _fields(unit, allowed, required, f"envelope.{name}[{i}]")
            unit_id = _id(unit["unit_id"], f"envelope.{name}[{i}].unit_id")
            if unit_id in seen:
                raise ContractError(f"duplicate {name} unit_id: {unit_id}")
            seen.add(unit_id)
            out.append({
                "unit_id": unit_id,
                "path_scopes": _paths(unit["path_scopes"], f"envelope.{name}[{i}].path_scopes"),
                "acceptance_ids": _ids(unit["acceptance_ids"], f"envelope.{name}[{i}].acceptance_ids"),
                **({"baseline_weight": _positive(unit["baseline_weight"], f"envelope.{name}[{i}].baseline_weight")} if name == "luna_units" else {}),
            })
        return sorted(out, key=lambda u: u["unit_id"])
    result["luna_units"] = units(luna, "luna_units")
    result["sol_lane_units"] = units(sol, "sol_lane_units")
    unit_ids = [u["unit_id"] for u in result["luna_units"] + result["sol_lane_units"]]
    if len(unit_ids) != len(set(unit_ids)):
        raise ContractError("unit_id must be unique across Luna and Sol lane units")
    luna_paths = [p for u in result["luna_units"] for p in u["path_scopes"]]
    sol_paths = [p for u in result["sol_lane_units"] for p in u["path_scopes"]]
    all_paths = luna_paths + sol_paths
    for i, left in enumerate(all_paths):
        for right in all_paths[i + 1 :]:
            a, b = left.casefold(), right.casefold()
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                raise ContractError("Luna and Sol path scopes overlap")
    ids = [a for u in result["luna_units"] + result["sol_lane_units"] for a in u["acceptance_ids"]]
    if len(ids) != len(set(ids)):
        raise ContractError("acceptance_ids must be exclusive across units")
    return result


def _normalize(source: Mapping[str, Any]) -> dict[str, Any]:
    document = _object(source, "contract")
    allowed = {"schema_version", "envelope", "events", "contract_fingerprint"}
    _fields(document, allowed, {"schema_version", "envelope", "events"}, "contract")
    if document["schema_version"] != SCHEMA_VERSION or isinstance(document["schema_version"], bool):
        raise ContractError("unsupported schema_version")
    envelope = _envelope(document["envelope"])
    raw_events = document["events"]
    if not isinstance(raw_events, list) or not raw_events:
        raise ContractError("events must be a non-empty JSON array")
    events = [_event(raw, i) for i, raw in enumerate(raw_events)]
    normalized = {"schema_version": SCHEMA_VERSION, "envelope": envelope, "events": events}
    if "contract_fingerprint" in document:
        normalized["contract_fingerprint"] = _digest(document["contract_fingerprint"], "contract_fingerprint")
    return normalized


def _attach_fingerprint(normalized: dict[str, Any]) -> dict[str, Any]:
    fingerprint = contract_fingerprint(normalized)
    if "contract_fingerprint" in normalized and normalized["contract_fingerprint"] != fingerprint:
        raise ContractError("contract_fingerprint does not match canonical contract")
    normalized["contract_fingerprint"] = fingerprint
    return normalized


def validate(source: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize(source)
    _replay(normalized)
    return _attach_fingerprint(normalized)


def _replay(document: Mapping[str, Any], *, require_closed: bool = True) -> dict[str, Any]:
    env = document["envelope"]
    luna = {u["unit_id"]: u for u in env["luna_units"]}
    sol = {u["unit_id"]: u for u in env["sol_lane_units"]}
    all_acceptance = {a for u in env["luna_units"] for a in u["acceptance_ids"]}
    current = env["candidate_start_digest"]
    state = "START"
    open_target: list[str] | None = None
    used_evidence: set[str] = set()
    seen_failure_evidence: set[str] = set()
    reclaimed: set[str] = set()
    accepted: set[str] = set()
    touched: set[str] = set()
    attempts = 0
    cost = 0.0
    parallel = 0
    last_pass = False
    last_failure = False
    last_failure_evidence: str | None = None
    last_failed_acceptance_ids: set[str] = set()
    for event in document["events"]:
        kind = event["event"]
        actor = event["actor_id"]
        candidate = event["candidate_digest"]
        if kind == "DISPATCH":
            if state != "START" or actor != env["controller_id"] or candidate != current:
                raise ContractError("DISPATCH must start the contract by the controller")
            state = "DISPATCHED"
        elif kind == "SOL_PARALLEL_PROGRESS":
            if state not in {"DISPATCHED", "AWAITING_ACCEPTANCE"} or actor != env["controller_id"] or candidate != current:
                raise ContractError("SOL_PARALLEL_PROGRESS requires the controller and current candidate while work awaits handoff or acceptance")
            if any(not _contains([p for u in sol.values() for p in u["path_scopes"]], p) for p in event["changed_paths"]):
                raise ContractError("Sol parallel progress exceeds sol_lane scopes")
            if event["workspace_before_digest"] == event["workspace_after_digest"]:
                raise ContractError("Sol parallel progress must record an actual workspace change")
            parallel += 1
        elif kind == "LUNA_HANDOFF":
            if state not in {"DISPATCHED", "FAILED"} or actor != env["luna_executor_id"]:
                raise ContractError("LUNA_HANDOFF is out of order or has the wrong actor")
            if not event["changed_paths"] or any(not _contains([p for u in luna.values() for p in u["path_scopes"]], p) for p in event["changed_paths"]):
                raise ContractError("LUNA_HANDOFF paths must be non-empty and within Luna scopes")
            covered = {
                unit_id for unit_id, unit in luna.items()
                if any(_contains(unit["path_scopes"], path) for path in event["changed_paths"])
            }
            if covered != set(luna):
                raise ContractError("LUNA_HANDOFF must cover every delegated Luna unit")
            if candidate == current:
                raise ContractError("candidate_digest must change on a Luna handoff")
            if state == "FAILED":
                raise ContractError("failed candidates must use LUNA_REPAIR_HANDOFF")
            accepted.clear()
            touched.update(covered)
            current, state, last_pass, last_failure = candidate, "AWAITING_ACCEPTANCE", False, False
        elif kind == "SOL_ACCEPTANCE_FAIL" or kind == "SOL_ACCEPTANCE_PASS":
            wanted = "PASS" if kind.endswith("PASS") else "FAIL"
            if state not in {"AWAITING_ACCEPTANCE", "RECLAIMED"} or actor != env["controller_id"] or candidate != current:
                raise ContractError(f"SOL_ACCEPTANCE_{wanted} requires controller review of current candidate")
            if event["changed_paths"] or event["workspace_before_digest"] != event["workspace_after_digest"]:
                raise ContractError("Sol acceptance must be read-only")
            if any(a not in all_acceptance for a in event["acceptance_ids"]):
                raise ContractError("acceptance event references an unknown acceptance_id")
            if wanted == "PASS":
                accepted.update(event["acceptance_ids"])
                last_failed_acceptance_ids.clear()
                last_pass, last_failure, state = True, False, "ACCEPTED_CANDIDATE"
            else:
                evidence = event["failure_evidence_digest"]
                if evidence in seen_failure_evidence:
                    raise ContractError("failure evidence digest must be new for each failed candidate")
                seen_failure_evidence.add(evidence)
                last_pass, last_failure, state = False, True, "FAILED"
                last_failure_evidence = evidence
                last_failed_acceptance_ids = set(event["acceptance_ids"])
        elif kind == "OPEN_LUNA_REPAIR":
            if state != "FAILED" or actor != env["controller_id"] or candidate != current:
                raise ContractError("OPEN_LUNA_REPAIR requires the controller and current failed candidate")
            targets = event["target_unit_ids"]
            if any(t not in luna for t in targets) or any(t in reclaimed for t in targets):
                raise ContractError("repair targets must be unreclaimed Luna units")
            if any(not (set(luna[t]["acceptance_ids"]) & last_failed_acceptance_ids) for t in targets):
                raise ContractError("repair targets must be bound to the failed acceptance evidence")
            evidence = event["failure_evidence_digest"]
            if evidence != last_failure_evidence or evidence in used_evidence:
                raise ContractError("repair must bind the latest unused failure evidence")
            used_evidence.add(evidence)
            last_failure_evidence = None
            attempts += 1
            cost += event["repair_cost_weight"]
            if attempts > env["repair_budget"]["max_attempts"]:
                raise ContractError("repair attempt budget exceeded")
            if cost > env["repair_budget"]["max_cost_weight"] and not math.isclose(cost, env["repair_budget"]["max_cost_weight"], rel_tol=1e-12, abs_tol=1e-12):
                raise ContractError("repair cost budget exceeded")
            if event["marginal_net_substitution"] <= 0:
                raise ContractError("repair marginal_net_substitution must be positive")
            open_target = targets
            state = "REPAIR_OPEN"
        elif kind == "LUNA_REPAIR_HANDOFF":
            if state != "REPAIR_OPEN" or actor != env["luna_executor_id"] or event["target_unit_ids"] != open_target:
                raise ContractError("LUNA_REPAIR_HANDOFF must return to the original Luna executor and targets")
            paths = [p for t in (open_target or []) for p in luna[t]["path_scopes"]]
            if not event["changed_paths"] or any(not _contains(paths, p) for p in event["changed_paths"]):
                raise ContractError("repair handoff paths exceed target Luna units")
            covered = {
                unit_id for unit_id in (open_target or [])
                if any(_contains(luna[unit_id]["path_scopes"], path) for path in event["changed_paths"])
            }
            if covered != set(open_target or []):
                raise ContractError("repair handoff must change every targeted Luna unit")
            if candidate == current:
                raise ContractError("repair candidate_digest must change")
            accepted.clear()
            touched.update(covered)
            current, state, open_target = candidate, "AWAITING_ACCEPTANCE", None
            last_failed_acceptance_ids.clear()
            last_pass, last_failure = False, False
        elif kind == "SOL_RECLAIM":
            if state != "FAILED" or actor != env["controller_id"]:
                raise ContractError("SOL_RECLAIM requires a prior Sol acceptance failure")
            targets = event["unit_ids"]
            if any(t not in luna for t in targets) or any(t in reclaimed for t in targets):
                raise ContractError("reclaim targets must be unreclaimed Luna units")
            if any(not (set(luna[t]["acceptance_ids"]) & last_failed_acceptance_ids) for t in targets):
                raise ContractError("reclaim targets must be bound to the failed acceptance evidence")
            paths = [p for t in targets for p in luna[t]["path_scopes"]]
            if any(not _contains(paths, p) for p in event["changed_paths"]):
                raise ContractError("Sol reclaim paths exceed the reclaimed units")
            if candidate == current:
                raise ContractError("candidate_digest must change when Sol reclaims and edits units")
            reclaimed.update(targets)
            accepted.clear()
            current = candidate
            last_failed_acceptance_ids.clear()
            state, last_failure = "RECLAIMED", False
        elif kind == "CLOSE":
            if state not in {"ACCEPTED_CANDIDATE", "RECLAIMED"} or actor != env["controller_id"] or candidate != current:
                raise ContractError("CLOSE requires the current candidate after independent acceptance")
            if not last_pass:
                raise ContractError("CLOSE requires an independent acceptance pass for the current candidate")
            dispositions = {d["unit_id"]: d["status"] for d in event["unit_dispositions"]}
            if set(dispositions) != set(luna):
                raise ContractError("CLOSE must dispose every Luna unit exactly once")
            if any((dispositions[u] == "reclaimed") != (u in reclaimed) for u in luna):
                raise ContractError("CLOSE unit dispositions do not match reclaim history")
            if any(dispositions[u] == "accepted" and u not in touched for u in luna):
                raise ContractError("accepted Luna units require recorded Luna delivery")
            if not all(a in accepted for unit_id in luna if dispositions[unit_id] == "accepted" for a in luna[unit_id]["acceptance_ids"]):
                raise ContractError("accepted Luna units require independent acceptance")
            state = "CLOSED"
        else:  # pragma: no cover - event parser prevents this
            raise ContractError("unsupported event")
    if require_closed and state != "CLOSED":
        raise ContractError("contract is not closed")
    return {
        "current": current,
        "state": state,
        "open_target": open_target,
        "last_failure_evidence": last_failure_evidence,
        "last_failed_acceptance_ids": last_failed_acceptance_ids,
        "reclaimed": reclaimed,
        "accepted": accepted,
        "attempts": attempts,
        "cost": cost,
        "parallel": parallel,
    }


def _remaining_repair_cost(maximum: float, used: float) -> float:
    if math.isclose(used, maximum, rel_tol=1e-12, abs_tol=1e-12):
        return 0.0
    return max(0.0, maximum - used)


def project(source: Mapping[str, Any]) -> dict[str, Any]:
    """Replay a valid schema-1 event prefix and expose its next legal step."""

    document = _normalize(source)
    replay = _replay(document, require_closed=False)
    document = _attach_fingerprint(document)
    env = document["envelope"]
    luna = {unit["unit_id"]: unit for unit in env["luna_units"]}
    state = replay["state"]
    remaining_attempts = env["repair_budget"]["max_attempts"] - replay["attempts"]
    remaining_cost = _remaining_repair_cost(env["repair_budget"]["max_cost_weight"], replay["cost"])
    failed_unit_ids = sorted(
        unit_id for unit_id, unit in luna.items()
        if set(unit["acceptance_ids"]) & replay["last_failed_acceptance_ids"]
    )
    available_failed_unit_ids = [unit_id for unit_id in failed_unit_ids if unit_id not in replay["reclaimed"]]

    next_events: list[str] = []
    if state == "DISPATCHED":
        next_events.append("LUNA_HANDOFF")
        if env["sol_lane_units"]:
            next_events.append("SOL_PARALLEL_PROGRESS")
    elif state == "AWAITING_ACCEPTANCE":
        next_events.extend(("SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS"))
        if env["sol_lane_units"]:
            next_events.append("SOL_PARALLEL_PROGRESS")
    elif state == "FAILED":
        if available_failed_unit_ids:
            next_events.append("SOL_RECLAIM")
            if remaining_attempts > 0 and remaining_cost > 0.0:
                next_events.append("OPEN_LUNA_REPAIR")
    elif state == "REPAIR_OPEN":
        next_events.append("LUNA_REPAIR_HANDOFF")
    elif state == "RECLAIMED":
        next_events.extend(("SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS"))
    elif state == "ACCEPTED_CANDIDATE":
        next_events.append("CLOSE")

    accepted_unit_ids = sorted(
        unit_id for unit_id, unit in luna.items()
        if unit_id not in replay["reclaimed"]
        and all(acceptance_id in replay["accepted"] for acceptance_id in unit["acceptance_ids"])
    )
    result: dict[str, Any] = {
        "status": "CLOSED" if state == "CLOSED" else "IN_PROGRESS",
        "schema_version": SCHEMA_VERSION,
        "contract_fingerprint": document["contract_fingerprint"],
        "state": state,
        "current_candidate_digest": replay["current"],
        "next_events": sorted(next_events),
        "remaining_repair_attempts": remaining_attempts,
        "remaining_repair_cost_weight": remaining_cost,
        "accepted_luna_unit_ids": accepted_unit_ids,
        "reclaimed_luna_unit_ids": sorted(replay["reclaimed"]),
        "automatic_execution_allowed": False,
    }
    if state == "FAILED":
        result["failure_evidence_digest"] = replay["last_failure_evidence"]
        result["affected_luna_unit_ids"] = failed_unit_ids
    if state == "REPAIR_OPEN":
        result["open_repair_target_unit_ids"] = sorted(replay["open_target"] or [])
    return result


def assess(source: Mapping[str, Any]) -> dict[str, Any]:
    document = validate(source)
    replay = _replay(document)
    total = math.fsum(u["baseline_weight"] for u in document["envelope"]["luna_units"])
    shadowed = math.fsum(u["baseline_weight"] for u in document["envelope"]["luna_units"] if u["unit_id"] in replay["reclaimed"])
    accepted_weight = total - shadowed
    result = {
        "status": "ACCEPTED",
        "schema_version": SCHEMA_VERSION,
        "contract_fingerprint": document["contract_fingerprint"],
        "accepted_luna_baseline_weight": accepted_weight,
        "shadowed_luna_baseline_weight": shadowed,
        "fine_grained_substitution_fraction": accepted_weight / total,
        "repair_attempts": replay["attempts"],
        "repair_cost_weight": replay["cost"],
        "sol_parallel_progress_count": replay["parallel"],
        "sol_acceptance_read_only": True,
        "automatic_execution_allowed": False,
    }
    return result


def template() -> dict[str, Any]:
    z = "sha256:" + "0" * 64
    c = "sha256:" + "1" * 64
    d = "sha256:" + "2" * 64
    source: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "envelope": {
            "controller_id": "sol-controller",
            "luna_executor_id": "luna-executor",
            "candidate_start_digest": z,
            "repair_budget": {"max_attempts": 2, "max_cost_weight": 2.0},
            "luna_units": [{"unit_id": "core-unit", "path_scopes": ["src"], "acceptance_ids": ["accept-core"], "baseline_weight": 1.0}],
            "sol_lane_units": [{"unit_id": "docs-lane", "path_scopes": ["docs"], "acceptance_ids": ["accept-docs"]}],
        },
        "events": [
            {"sequence": 1, "event": "DISPATCH", "actor_id": "sol-controller", "candidate_digest": z},
            {"sequence": 2, "event": "LUNA_HANDOFF", "actor_id": "luna-executor", "candidate_digest": c, "changed_paths": ["src/main.py"]},
            {"sequence": 3, "event": "SOL_ACCEPTANCE_PASS", "actor_id": "sol-controller", "candidate_digest": c, "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": d, "workspace_after_digest": d, "result_digest": d},
            {"sequence": 4, "event": "CLOSE", "actor_id": "sol-controller", "candidate_digest": c, "unit_dispositions": [{"unit_id": "core-unit", "status": "accepted"}]},
        ],
    }
    source["contract_fingerprint"] = contract_fingerprint(source)
    return source


def _load(path: str) -> Any:
    try:
        return strict_json_loads(open(path, encoding="utf-8").read())
    except OSError as exc:
        raise ContractError(f"cannot read input: {exc}") from exc


class _ArgumentParser(argparse.ArgumentParser):
    """Keep command-line failures on the contract's single-line error path."""

    def error(self, message: str) -> None:  # pragma: no cover - exercised by CLI subprocesses
        raise ContractError(message)


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description="Validate the Sol-Luna closure contract.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    sub.add_parser("template")
    for command in ("validate", "assess", "project"):
        p = sub.add_parser(command)
        p.add_argument("--input", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "template":
            output = template()
        else:
            source = _load(args.input)
            output = validate(source) if args.command == "validate" else (assess(source) if args.command == "assess" else project(source))
    except (ContractError, OSError, TypeError, ValueError) as exc:
        print(f"closure contract error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, read-only compilation and comparison of frozen handoffs."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
STATUSES = {"READY", "HOLD", "BLOCKED"}
BLOCKER_KINDS = {
    "validation-failure",
    "open-risk",
    "missing-input",
    "missing-authority",
    "missing-permission",
    "external-state",
}
RISKS = {"low", "medium", "high", "critical"}
DEPTHS = {"TARGETED", "STANDARD", "DEEP"}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}

PORTFOLIO_FIELDS = {"schema_version", "portfolio_id", "handoffs"}
HANDOFF_FIELDS = {
    "handoff_id",
    "package_id",
    "executor_id",
    "depends_on",
    "writable_paths",
    "candidate_digest",
    "status",
    "blocker_kind",
    "blocker_digest",
    "acceptance_passed",
    "risk",
    "shared_interface",
    "repair_count",
    "review_depth",
}
SNAPSHOT_FIELDS = {
    "schema_version",
    "portfolio_id",
    "handoffs",
    "topological_order",
    "partitions",
    "executors",
    "review_handoff_ids",
    "snapshot_fingerprint",
}


class ReviewError(ValueError):
    """The portfolio or snapshot is malformed or violates its contract."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewError(f"{field} must be an object")
    return value


def _fields(value: Mapping[str, Any], allowed: set[str], required: set[str], field: str) -> None:
    keys = set(value)
    if any(not isinstance(key, str) for key in keys):
        raise ReviewError(f"{field} keys must be strings")
    unknown = keys - allowed
    missing = required - keys
    if unknown:
        raise ReviewError(f"{field} has unsupported fields: {sorted(unknown)}")
    if missing:
        raise ReviewError(f"{field} is missing required fields: {sorted(missing)}")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None or len(value) > 64:
        raise ReviewError(f"{field} must be a lowercase hyphen identifier")
    return value


def _digest(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise ReviewError(f"{field} must be a lowercase sha256 digest")
    return value


def _enum(value: Any, choices: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ReviewError(f"{field} has an unsupported value")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReviewError(f"{field} must be boolean")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReviewError(f"{field} must be an integer")
    return value


def _path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewError(f"{field} must be a relative repository path")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise ReviewError(f"{field} must be slash-normalized and relative")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise ReviewError(f"{field} contains a control or surrogate character")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReviewError(f"{field} contains an unsafe path component")
    for part in parts:
        if part.endswith((".", " ")):
            raise ReviewError(f"{field} contains a trailing dot or space")
        device = re.split(r"[.:]", part.rstrip(" ."), maxsplit=1)[0].rstrip(" .").casefold()
        if device in WINDOWS_RESERVED:
            raise ReviewError(f"{field} contains a reserved Windows device name")
    return value


def _path_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ReviewError(f"{field} must be a non-empty array")
    paths = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    folded = [item.casefold() for item in paths]
    if len(folded) != len(set(folded)):
        raise ReviewError(f"{field} contains duplicate paths")
    return sorted(paths)


def _dependency_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ReviewError(f"{field} must be an array")
    result = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ReviewError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _review_depth(status: str, shared: bool, repairs: int, risk: str) -> str:
    if status != "READY" or shared or repairs != 0 or risk in {"high", "critical"}:
        return "DEEP"
    return "STANDARD" if risk == "medium" else "TARGETED"


def _normalize_handoff(raw: Any, index: int) -> dict[str, Any]:
    item = _mapping(raw, f"handoffs[{index}]")
    _fields(item, HANDOFF_FIELDS, HANDOFF_FIELDS, f"handoffs[{index}]")
    handoff_id = _identifier(item["handoff_id"], f"handoffs[{index}].handoff_id")
    package_id = _identifier(item["package_id"], f"handoffs[{index}].package_id")
    executor_id = _identifier(item["executor_id"], f"handoffs[{index}].executor_id")
    depends_on = _dependency_list(item["depends_on"], f"handoffs[{index}].depends_on")
    writable_paths = _path_list(item["writable_paths"], f"handoffs[{index}].writable_paths")
    candidate_digest = _digest(item["candidate_digest"], f"handoffs[{index}].candidate_digest")
    status = _enum(item["status"], STATUSES, f"handoffs[{index}].status")
    blocker_kind = item["blocker_kind"]
    if status == "READY":
        if blocker_kind is not None:
            raise ReviewError("READY handoff blocker_kind must be null")
    else:
        blocker_kind = _enum(blocker_kind, BLOCKER_KINDS, f"handoffs[{index}].blocker_kind")
    blocker_digest = _digest(item["blocker_digest"], f"handoffs[{index}].blocker_digest", nullable=True)
    acceptance_passed = _boolean(item["acceptance_passed"], f"handoffs[{index}].acceptance_passed")
    risk = _enum(item["risk"], RISKS, f"handoffs[{index}].risk")
    shared_interface = _boolean(item["shared_interface"], f"handoffs[{index}].shared_interface")
    repair_count = _integer(item["repair_count"], f"handoffs[{index}].repair_count")
    if not 0 <= repair_count <= 3:
        raise ReviewError("repair_count must be an integer from 0 through 3")
    review_depth = _enum(item["review_depth"], DEPTHS, f"handoffs[{index}].review_depth")

    if status == "READY":
        if not acceptance_passed or blocker_digest is not None:
            raise ReviewError("READY requires acceptance_passed=true and null blocker fields")
    elif status == "HOLD":
        if acceptance_passed or blocker_kind not in {"validation-failure", "open-risk"} or blocker_digest is None:
            raise ReviewError("HOLD requires failed acceptance and a validation/open-risk digest")
    else:
        if acceptance_passed or blocker_kind not in {"missing-input", "missing-authority", "missing-permission", "external-state"} or blocker_digest is None:
            raise ReviewError("BLOCKED requires failed acceptance and a blocker digest")
    derived_depth = _review_depth(status, shared_interface, repair_count, risk)
    if review_depth != derived_depth:
        raise ReviewError("review_depth does not match the derived review depth")
    return {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "executor_id": executor_id,
        "depends_on": depends_on,
        "writable_paths": writable_paths,
        "candidate_digest": candidate_digest,
        "status": status,
        "blocker_kind": blocker_kind,
        "blocker_digest": blocker_digest,
        "acceptance_passed": acceptance_passed,
        "risk": risk,
        "shared_interface": shared_interface,
        "repair_count": repair_count,
        "review_depth": review_depth,
    }


def _validate_paths(handoffs: list[dict[str, Any]]) -> None:
    paths: list[str] = []
    for item in handoffs:
        paths.extend(item["writable_paths"])
    folded = sorted({path.casefold() for path in paths})
    for left, right in zip(folded, folded[1:]):
        if right == left or right.startswith(left + "/"):
            raise ReviewError("writable paths contain case-insensitive ancestor/descendant overlap")


def _topology(handoffs: list[dict[str, Any]]) -> list[str]:
    by_package = {item["package_id"]: item["handoff_id"] for item in handoffs}
    indegree = {item["handoff_id"]: len(item["depends_on"]) for item in handoffs}
    children: dict[str, list[str]] = defaultdict(list)
    for item in handoffs:
        for dependency in item["depends_on"]:
            children[by_package[dependency]].append(item["handoff_id"])
    available = [item["handoff_id"] for item in handoffs if indegree[item["handoff_id"]] == 0]
    available.sort()
    result: list[str] = []
    while available:
        current = available.pop(0)
        result.append(current)
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                available.append(child)
        available.sort()
    if len(result) != len(handoffs):
        raise ReviewError("dependencies must form an acyclic graph")
    return result


def _compile(source: Mapping[str, Any], *, snapshot: bool = False) -> dict[str, Any]:
    obj = _mapping(source, "source")
    _fields(obj, PORTFOLIO_FIELDS, PORTFOLIO_FIELDS, "source")
    schema_version = _integer(obj["schema_version"], "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ReviewError("schema_version must be integer 1")
    portfolio_id = _identifier(obj["portfolio_id"], "portfolio_id")
    raw_handoffs = obj["handoffs"]
    if not isinstance(raw_handoffs, list) or not 1 <= len(raw_handoffs) <= 32:
        raise ReviewError("handoffs must be an array containing 1 through 32 entries")
    handoffs = [_normalize_handoff(item, index) for index, item in enumerate(raw_handoffs)]
    if len({item["handoff_id"] for item in handoffs}) != len(handoffs):
        raise ReviewError("handoff IDs must be unique")
    if len({item["package_id"] for item in handoffs}) != len(handoffs):
        raise ReviewError("package IDs must be unique")
    by_package = {item["package_id"]: item for item in handoffs}
    for item in handoffs:
        for dependency in item["depends_on"]:
            if dependency == item["package_id"]:
                raise ReviewError("a package cannot depend on itself")
            if dependency not in by_package:
                raise ReviewError("dependency must name an existing package")
    _validate_paths(handoffs)
    handoffs.sort(key=lambda item: item["handoff_id"])
    by_handoff = {item["handoff_id"]: item for item in handoffs}
    # Dependency-derived state constraints are checked after all package IDs exist.
    state_by_package = {item["package_id"]: item["status"] for item in handoffs}
    blocked_packages: set[str] = set()
    hold_packages: set[str] = set()
    for item in handoffs:
        if item["status"] == "BLOCKED":
            blocked_packages.add(item["package_id"])
        if item["status"] == "HOLD":
            hold_packages.add(item["package_id"])
    changed = True
    while changed:
        changed = False
        for item in handoffs:
            if any(dep in blocked_packages for dep in item["depends_on"]) and item["package_id"] not in blocked_packages:
                blocked_packages.add(item["package_id"])
                changed = True
    changed = True
    while changed:
        changed = False
        for item in handoffs:
            if any(dep in hold_packages for dep in item["depends_on"]) and item["package_id"] not in hold_packages:
                hold_packages.add(item["package_id"])
                changed = True
    for item in handoffs:
        if item["package_id"] in blocked_packages and item["status"] != "BLOCKED":
            raise ReviewError("handoffs depending on BLOCKED must be BLOCKED")
        if item["status"] == "READY" and any(dep in hold_packages for dep in item["depends_on"]):
            raise ReviewError("a handoff depending on HOLD cannot be READY")
    topological_order = _topology(handoffs)
    partitions = {
        "ready": sorted(item["handoff_id"] for item in handoffs if item["status"] == "READY"),
        "hold": sorted(item["handoff_id"] for item in handoffs if item["status"] == "HOLD"),
        "blocked": sorted(item["handoff_id"] for item in handoffs if item["status"] == "BLOCKED"),
    }
    executors: dict[str, list[str]] = defaultdict(list)
    for item in handoffs:
        executors[item["executor_id"]].append(item["handoff_id"])
    executor_output = {key: sorted(value) for key, value in sorted(executors.items())}
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": portfolio_id,
        "handoffs": handoffs,
        "topological_order": topological_order,
        "partitions": partitions,
        "executors": executor_output,
        "review_handoff_ids": partitions["ready"].copy(),
    }
    result["snapshot_fingerprint"] = _fingerprint(result)
    return result


def template() -> dict[str, Any]:
    """Return a fresh valid one-handoff portfolio template."""
    zero = "sha256:" + "0" * 64
    return {
        "schema_version": 1,
        "portfolio_id": "release-alpha",
        "handoffs": [
            {
                "handoff_id": "handoff-core",
                "package_id": "core",
                "executor_id": "luna-medium",
                "depends_on": [],
                "writable_paths": ["src/core.py"],
                "candidate_digest": zero,
                "status": "READY",
                "blocker_kind": None,
                "blocker_digest": None,
                "acceptance_passed": True,
                "risk": "low",
                "shared_interface": False,
                "repair_count": 0,
                "review_depth": "TARGETED",
            }
        ],
    }


def compile_portfolio(source: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and deterministically compile a portfolio without mutation."""
    return _compile(source)


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    obj = _mapping(snapshot, "snapshot")
    _fields(obj, SNAPSHOT_FIELDS, SNAPSHOT_FIELDS, "snapshot")
    base = {
        "schema_version": obj["schema_version"],
        "portfolio_id": obj["portfolio_id"],
        "handoffs": obj["handoffs"],
    }
    expected = _compile(base)
    if dict(obj) != expected:
        raise ReviewError("snapshot derived fields or fingerprint do not match")
    return expected


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Validate two complete snapshots and report candidate-bound review impact."""
    before_snapshot = _validate_snapshot(before)
    after_snapshot = _validate_snapshot(after)
    if before_snapshot["portfolio_id"] != after_snapshot["portfolio_id"]:
        raise ReviewError("snapshots must have the same portfolio_id")
    before_by_id = {item["handoff_id"]: item for item in before_snapshot["handoffs"]}
    after_by_id = {item["handoff_id"]: item for item in after_snapshot["handoffs"]}
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    added = sorted(after_ids - before_ids)
    removed = sorted(before_ids - after_ids)
    changed = sorted(item_id for item_id in before_ids & after_ids if before_by_id[item_id] != after_by_id[item_id])
    order = {"BLOCKED": 0, "HOLD": 1, "READY": 2}
    regressions = sorted(
        item_id for item_id in before_ids & after_ids
        if order[after_by_id[item_id]["status"]] < order[before_by_id[item_id]["status"]]
    )
    progressions = sorted(
        item_id for item_id in before_ids & after_ids
        if order[after_by_id[item_id]["status"]] > order[before_by_id[item_id]["status"]]
    )
    starts = set(added) | set(changed)
    package_to_handoff = {item["package_id"]: item["handoff_id"] for item in after_snapshot["handoffs"]}
    dependents: dict[str, list[str]] = defaultdict(list)
    for item in after_snapshot["handoffs"]:
        for dependency in item["depends_on"]:
            dependents[package_to_handoff[dependency]].append(item["handoff_id"])
    affected = set(starts)
    queue = deque(starts)
    while queue:
        current = queue.popleft()
        for child in dependents[current]:
            if child not in affected:
                affected.add(child)
                queue.append(child)
    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": before_snapshot["portfolio_id"],
        "before_fingerprint": before_snapshot["snapshot_fingerprint"],
        "after_fingerprint": after_snapshot["snapshot_fingerprint"],
        "added_handoff_ids": added,
        "removed_handoff_ids": removed,
        "changed_handoff_ids": changed,
        "state_regressions": regressions,
        "state_progressions": progressions,
        "affected_review_handoff_ids": sorted(affected),
    }


__all__ = ["ReviewError", "template", "compile_portfolio", "compare"]

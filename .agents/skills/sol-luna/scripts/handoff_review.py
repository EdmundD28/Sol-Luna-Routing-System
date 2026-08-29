#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Pure, deterministic compilation and comparison of frozen handoffs.

The module intentionally has no filesystem, command, transport, dispatch, or
acceptance capability.  It only validates caller-supplied mappings and returns
new dictionaries containing replayable review projections.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import unicodedata
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
STATUSES = {"READY", "HOLD", "BLOCKED"}
RISKS = {"low", "medium", "high", "critical"}
REVIEW_DEPTHS = {"TARGETED", "STANDARD", "DEEP"}
HOLD_BLOCKERS = {"validation-failure", "open-risk"}
BLOCKED_BLOCKERS = {
    "missing-input",
    "missing-authority",
    "missing-permission",
    "external-state",
}
WINDOWS_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    "clock$",
    "conin$",
    "conout$",
} | {
    f"{prefix}{suffix}"
    for prefix in ("com", "lpt")
    for suffix in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "¹", "²", "³")
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
    """The portfolio or compiled snapshot violates schema 1."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewError(f"{field} must be an object")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    keys = list(value)
    if any(not isinstance(key, str) for key in keys):
        raise ReviewError(f"{field} keys must be strings")
    actual = set(keys)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ReviewError(f"{field} is missing required fields: {missing}")
    if extra:
        raise ReviewError(f"{field} has unsupported fields: {extra}")


def _schema(value: Any, field: str = "schema_version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != SCHEMA_VERSION:
        raise ReviewError(f"{field} must be integer 1")
    return value


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 64
        or IDENTIFIER.fullmatch(value) is None
    ):
        raise ReviewError(f"{field} must be a 1-64 character lowercase hyphen identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise ReviewError(f"{field} must be an exact lowercase sha256 digest")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReviewError(f"{field} must be a boolean")
    return value


def _enum(value: Any, choices: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ReviewError(f"{field} has an unsupported value")
    return value


def _identifier_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ReviewError(f"{field} must be an array")
    result = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ReviewError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewError(f"{field} must be a non-empty relative repository path")
    if "\\" in value or value.startswith("/") or ":" in value:
        raise ReviewError(f"{field} must be a slash-normalized relative repository path")
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
        raise ReviewError(f"{field} contains a control or surrogate character")

    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise ReviewError(f"{field} contains an unsafe path component")
    for component in components:
        if component.endswith((".", " ")):
            raise ReviewError(f"{field} contains a component with a trailing dot or space")
        device_base = component.split(".", 1)[0].rstrip(" .").casefold()
        if device_base in WINDOWS_DEVICES:
            raise ReviewError(f"{field} contains a reserved Windows device name")
    return value


def _paths(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ReviewError(f"{field} must be a non-empty array")
    result = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ReviewError(f"{field} contains duplicate paths")
    return sorted(result)


def _review_depth(status: str, shared: bool, repair_count: int, risk: str) -> str:
    if status != "READY" or shared or repair_count > 0 or risk in {"high", "critical"}:
        return "DEEP"
    if risk == "medium":
        return "STANDARD"
    return "TARGETED"


def _normalize_handoff(raw: Any, index: int) -> dict[str, Any]:
    field = f"handoffs[{index}]"
    source = _object(raw, field)
    _exact_fields(source, HANDOFF_FIELDS, field)

    handoff_id = _identifier(source["handoff_id"], f"{field}.handoff_id")
    package_id = _identifier(source["package_id"], f"{field}.package_id")
    executor_id = _identifier(source["executor_id"], f"{field}.executor_id")
    depends_on = _identifier_list(source["depends_on"], f"{field}.depends_on")
    if package_id in depends_on:
        raise ReviewError(f"{field} cannot depend on its own package")
    writable_paths = _paths(source["writable_paths"], f"{field}.writable_paths")
    candidate_digest = _digest(source["candidate_digest"], f"{field}.candidate_digest")
    status = _enum(source["status"], STATUSES, f"{field}.status")
    acceptance_passed = _boolean(source["acceptance_passed"], f"{field}.acceptance_passed")
    risk = _enum(source["risk"], RISKS, f"{field}.risk")
    shared_interface = _boolean(source["shared_interface"], f"{field}.shared_interface")

    repair_count = source["repair_count"]
    if (
        isinstance(repair_count, bool)
        or not isinstance(repair_count, int)
        or not 0 <= repair_count <= 3
    ):
        raise ReviewError(f"{field}.repair_count must be an integer from 0 through 3")

    blocker_kind = source["blocker_kind"]
    blocker_digest = source["blocker_digest"]
    if status == "READY":
        if not acceptance_passed or blocker_kind is not None or blocker_digest is not None:
            raise ReviewError(f"{field} has inconsistent READY evidence")
    elif status == "HOLD":
        if acceptance_passed or blocker_kind not in HOLD_BLOCKERS:
            raise ReviewError(f"{field} has inconsistent HOLD evidence")
        blocker_digest = _digest(blocker_digest, f"{field}.blocker_digest")
    else:
        if acceptance_passed or blocker_kind not in BLOCKED_BLOCKERS:
            raise ReviewError(f"{field} has inconsistent BLOCKED evidence")
        blocker_digest = _digest(blocker_digest, f"{field}.blocker_digest")

    supplied_depth = _enum(source["review_depth"], REVIEW_DEPTHS, f"{field}.review_depth")
    expected_depth = _review_depth(status, shared_interface, repair_count, risk)
    if supplied_depth != expected_depth:
        raise ReviewError(f"{field}.review_depth must equal derived value {expected_depth}")

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
        "review_depth": supplied_depth,
    }


def _reject_path_overlaps(handoffs: list[dict[str, Any]]) -> None:
    owners: dict[str, tuple[str, str]] = {}
    for handoff in handoffs:
        for path in handoff["writable_paths"]:
            folded = path.casefold()
            if folded in owners:
                raise ReviewError("writable_paths contains a case-insensitive duplicate")
            owners[folded] = (handoff["handoff_id"], path)

    folded_paths = set(owners)
    for folded in folded_paths:
        components = folded.split("/")
        prefix = components[0]
        for component in components[1:]:
            if prefix in folded_paths:
                raise ReviewError("writable_paths contains a case-insensitive ancestor overlap")
            prefix += "/" + component


def _topology_and_dependency_rules(
    handoffs: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    by_package = {handoff["package_id"]: handoff for handoff in handoffs}
    dependents: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {}
    for handoff in handoffs:
        package_id = handoff["package_id"]
        for dependency in handoff["depends_on"]:
            if dependency not in by_package:
                raise ReviewError(
                    f"handoff {handoff['handoff_id']} names unknown dependency {dependency}"
                )
            dependents[dependency].append(package_id)
        indegree[package_id] = len(handoff["depends_on"])

    ready: list[tuple[str, str]] = [
        (handoff["handoff_id"], handoff["package_id"])
        for handoff in handoffs
        if indegree[handoff["package_id"]] == 0
    ]
    heapq.heapify(ready)
    topological_ids: list[str] = []
    topological_packages: list[str] = []
    while ready:
        handoff_id, package_id = heapq.heappop(ready)
        topological_ids.append(handoff_id)
        topological_packages.append(package_id)
        for dependent in dependents[package_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                item = by_package[dependent]
                heapq.heappush(ready, (item["handoff_id"], dependent))

    if len(topological_ids) != len(handoffs):
        raise ReviewError("handoff dependencies must form an acyclic graph")

    has_blocked_ancestor: dict[str, bool] = {}
    has_hold_ancestor: dict[str, bool] = {}
    for package_id in topological_packages:
        handoff = by_package[package_id]
        dependencies = handoff["depends_on"]
        blocked = any(
            by_package[dependency]["status"] == "BLOCKED"
            or has_blocked_ancestor[dependency]
            for dependency in dependencies
        )
        hold = any(
            by_package[dependency]["status"] == "HOLD" or has_hold_ancestor[dependency]
            for dependency in dependencies
        )
        if blocked and handoff["status"] != "BLOCKED":
            raise ReviewError(
                f"handoff {handoff['handoff_id']} must be BLOCKED because a dependency is BLOCKED"
            )
        if hold and handoff["status"] == "READY":
            raise ReviewError(
                f"handoff {handoff['handoff_id']} cannot be READY because a dependency is HOLD"
            )
        has_blocked_ancestor[package_id] = blocked
        has_hold_ancestor[package_id] = hold

    return topological_ids, topological_packages


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _fingerprint(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def template() -> dict[str, Any]:
    """Return a fresh, complete, valid schema-1 portfolio input."""
    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": "release-alpha",
        "handoffs": [
            {
                "handoff_id": "handoff-core",
                "package_id": "core",
                "executor_id": "luna-high",
                "depends_on": [],
                "writable_paths": ["src/core.py"],
                "candidate_digest": "sha256:" + "0" * 64,
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
    """Validate and compile a portfolio without mutating the caller's input."""
    portfolio = _object(source, "source")
    _exact_fields(portfolio, PORTFOLIO_FIELDS, "source")
    _schema(portfolio["schema_version"])
    portfolio_id = _identifier(portfolio["portfolio_id"], "portfolio_id")

    raw_handoffs = portfolio["handoffs"]
    if not isinstance(raw_handoffs, list) or not 1 <= len(raw_handoffs) <= 32:
        raise ReviewError("handoffs must be an array containing 1 through 32 entries")
    handoffs = [_normalize_handoff(raw, index) for index, raw in enumerate(raw_handoffs)]

    handoff_ids = [handoff["handoff_id"] for handoff in handoffs]
    if len(handoff_ids) != len(set(handoff_ids)):
        raise ReviewError("handoff_id values must be unique")
    package_ids = [handoff["package_id"] for handoff in handoffs]
    if len(package_ids) != len(set(package_ids)):
        raise ReviewError("package_id values must be unique")

    _reject_path_overlaps(handoffs)
    topological_order, _ = _topology_and_dependency_rules(handoffs)
    handoffs.sort(key=lambda handoff: handoff["handoff_id"])

    partitions = {
        "ready": sorted(
            handoff["handoff_id"] for handoff in handoffs if handoff["status"] == "READY"
        ),
        "hold": sorted(
            handoff["handoff_id"] for handoff in handoffs if handoff["status"] == "HOLD"
        ),
        "blocked": sorted(
            handoff["handoff_id"] for handoff in handoffs if handoff["status"] == "BLOCKED"
        ),
    }
    executor_groups: dict[str, list[str]] = defaultdict(list)
    for handoff in handoffs:
        executor_groups[handoff["executor_id"]].append(handoff["handoff_id"])
    executors = {
        executor_id: sorted(executor_groups[executor_id])
        for executor_id in sorted(executor_groups)
    }
    review_handoff_ids = list(partitions["ready"])

    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": portfolio_id,
        "handoffs": handoffs,
        "topological_order": topological_order,
        "partitions": partitions,
        "executors": executors,
        "review_handoff_ids": review_handoff_ids,
    }
    snapshot["snapshot_fingerprint"] = _fingerprint(snapshot)
    return snapshot


def _validated_snapshot(source: Mapping[str, Any], field: str) -> dict[str, Any]:
    snapshot = _object(source, field)
    _exact_fields(snapshot, SNAPSHOT_FIELDS, field)
    _schema(snapshot["schema_version"], f"{field}.schema_version")
    _identifier(snapshot["portfolio_id"], f"{field}.portfolio_id")
    _digest(snapshot["snapshot_fingerprint"], f"{field}.snapshot_fingerprint")

    executors = snapshot["executors"]
    if not isinstance(executors, Mapping):
        raise ReviewError(f"{field}.executors must be an object")
    executor_keys = list(executors)
    if any(not isinstance(key, str) for key in executor_keys):
        raise ReviewError(f"{field}.executors keys must be strings")
    if executor_keys != sorted(executor_keys):
        raise ReviewError(f"{field}.executors keys must be sorted")

    expected = compile_portfolio(
        {
            "schema_version": snapshot["schema_version"],
            "portfolio_id": snapshot["portfolio_id"],
            "handoffs": snapshot["handoffs"],
        }
    )
    for key in SNAPSHOT_FIELDS:
        if snapshot[key] != expected[key]:
            raise ReviewError(f"{field}.{key} does not match the validated snapshot")
    return expected


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and compare two compiled snapshots without mutation."""
    before_snapshot = _validated_snapshot(before, "before")
    after_snapshot = _validated_snapshot(after, "after")
    if before_snapshot["portfolio_id"] != after_snapshot["portfolio_id"]:
        raise ReviewError("snapshot portfolio_id values must match")

    before_by_id = {
        handoff["handoff_id"]: handoff for handoff in before_snapshot["handoffs"]
    }
    after_by_id = {
        handoff["handoff_id"]: handoff for handoff in after_snapshot["handoffs"]
    }
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    added = sorted(after_ids - before_ids)
    removed = sorted(before_ids - after_ids)
    changed = sorted(
        handoff_id
        for handoff_id in before_ids & after_ids
        if before_by_id[handoff_id] != after_by_id[handoff_id]
    )

    state_rank = {"BLOCKED": 0, "HOLD": 1, "READY": 2}
    regressions = sorted(
        handoff_id
        for handoff_id in before_ids & after_ids
        if state_rank[after_by_id[handoff_id]["status"]]
        < state_rank[before_by_id[handoff_id]["status"]]
    )
    progressions = sorted(
        handoff_id
        for handoff_id in before_ids & after_ids
        if state_rank[after_by_id[handoff_id]["status"]]
        > state_rank[before_by_id[handoff_id]["status"]]
    )

    dependents: dict[str, list[str]] = defaultdict(list)
    for handoff in after_snapshot["handoffs"]:
        for dependency in handoff["depends_on"]:
            dependents[dependency].append(handoff["handoff_id"])
    affected = set(added) | set(changed)
    pending = deque(after_by_id[handoff_id]["package_id"] for handoff_id in affected)
    while pending:
        package_id = pending.popleft()
        for handoff_id in dependents[package_id]:
            if handoff_id not in affected:
                affected.add(handoff_id)
                pending.append(after_by_id[handoff_id]["package_id"])

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


__all__ = ["ReviewError", "compare", "compile_portfolio", "template"]

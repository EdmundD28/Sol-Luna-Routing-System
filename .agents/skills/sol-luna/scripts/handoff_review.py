#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, read-only compilation and comparison of frozen handoffs."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import unicodedata
from collections.abc import Mapping
from pathlib import PureWindowsPath
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
STATE_ORDER = {"BLOCKED": 0, "HOLD": 1, "READY": 2}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{prefix}{number}"
    for prefix in ("com", "lpt")
    for number in (*range(1, 10), "¹", "²", "³")
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
PARTITION_FIELDS = {"ready", "hold", "blocked"}


class ReviewError(ValueError):
    """A portfolio or compiled snapshot violates the review contract."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewError(f"{field} must be a JSON object")
    return value


def _fields(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    keys = list(value.keys())
    if any(not isinstance(key, str) for key in keys):
        raise ReviewError(f"{field} keys must be strings")
    actual = set(keys)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        raise ReviewError(f"{field} is missing required fields: {sorted(missing)}")
    if unknown:
        raise ReviewError(f"{field} has unsupported fields: {sorted(unknown)}")


def _integer_one(value: Any, field: str) -> int:
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
        raise ReviewError(f"{field} must be a lowercase sha256 digest")
    return value


def _enum(value: Any, choices: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ReviewError(f"{field} has an unsupported value")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReviewError(f"{field} must be a boolean")
    return value


def _path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewError(f"{field} must be a non-empty normalized relative path")
    if "\\" in value or value.startswith("/"):
        raise ReviewError(f"{field} must be a slash-normalized relative path")
    windows_path = PureWindowsPath(value)
    if windows_path.drive or windows_path.root:
        raise ReviewError(f"{field} must not be absolute or drive-relative")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise ReviewError(f"{field} contains a control or surrogate character")

    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReviewError(f"{field} contains an unsafe or empty component")
    for part in parts:
        if part.endswith((".", " ")):
            raise ReviewError(f"{field} contains a trailing dot or space component")
        if ":" in part:
            raise ReviewError(f"{field} contains alternate data stream syntax")
        device_base = part.split(".", 1)[0].rstrip(" .").casefold()
        if device_base in WINDOWS_RESERVED:
            raise ReviewError(f"{field} contains a reserved Windows device name")
    return value


def _identifiers(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ReviewError(f"{field} must be an array")
    result = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ReviewError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _paths(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ReviewError(f"{field} must be a non-empty array")
    result = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise ReviewError(f"{field} contains duplicate paths")
    return sorted(result)


def _review_depth(status: str, shared: bool, repair_count: int, risk: str) -> str:
    if status != "READY" or shared or repair_count > 0 or risk in {"high", "critical"}:
        return "DEEP"
    if risk == "medium":
        return "STANDARD"
    return "TARGETED"


def _handoff(raw: Any, index: int) -> dict[str, Any]:
    field = f"handoffs[{index}]"
    item = _object(raw, field)
    _fields(item, HANDOFF_FIELDS, field)
    handoff_id = _identifier(item["handoff_id"], f"{field}.handoff_id")
    package_id = _identifier(item["package_id"], f"{field}.package_id")
    executor_id = _identifier(item["executor_id"], f"{field}.executor_id")
    depends_on = _identifiers(item["depends_on"], f"{field}.depends_on")
    writable_paths = _paths(item["writable_paths"], f"{field}.writable_paths")
    candidate_digest = _digest(item["candidate_digest"], f"{field}.candidate_digest")
    status = _enum(item["status"], STATUSES, f"{field}.status")
    acceptance_passed = _bool(item["acceptance_passed"], f"{field}.acceptance_passed")
    risk = _enum(item["risk"], RISKS, f"{field}.risk")
    shared_interface = _bool(item["shared_interface"], f"{field}.shared_interface")
    repair_count = item["repair_count"]
    if (
        isinstance(repair_count, bool)
        or not isinstance(repair_count, int)
        or not 0 <= repair_count <= 3
    ):
        raise ReviewError(f"{field}.repair_count must be an integer from 0 through 3")

    blocker_kind = item["blocker_kind"]
    blocker_digest = item["blocker_digest"]
    if status == "READY":
        if not acceptance_passed or blocker_kind is not None or blocker_digest is not None:
            raise ReviewError(f"{field} READY state is inconsistent")
    elif status == "HOLD":
        if acceptance_passed or blocker_kind not in HOLD_BLOCKERS:
            raise ReviewError(f"{field} HOLD state is inconsistent")
        blocker_digest = _digest(blocker_digest, f"{field}.blocker_digest")
    else:
        if acceptance_passed or blocker_kind not in BLOCKED_BLOCKERS:
            raise ReviewError(f"{field} BLOCKED state is inconsistent")
        blocker_digest = _digest(blocker_digest, f"{field}.blocker_digest")

    supplied_depth = _enum(item["review_depth"], REVIEW_DEPTHS, f"{field}.review_depth")
    derived_depth = _review_depth(status, shared_interface, repair_count, risk)
    if supplied_depth != derived_depth:
        raise ReviewError(f"{field}.review_depth does not match the derived value")

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


def _validate_paths(handoffs: list[dict[str, Any]]) -> None:
    observed: list[tuple[str, str]] = []
    for handoff in handoffs:
        for path in handoff["writable_paths"]:
            folded = path.casefold()
            for other_folded, other_path in observed:
                if (
                    folded == other_folded
                    or folded.startswith(other_folded + "/")
                    or other_folded.startswith(folded + "/")
                ):
                    raise ReviewError(
                        f"writable path overlap between {other_path!r} and {path!r}"
                    )
            observed.append((folded, path))


def _topology(
    handoffs: list[dict[str, Any]],
) -> tuple[list[str], dict[str, set[str]], dict[str, str]]:
    package_to_handoff = {item["package_id"]: item["handoff_id"] for item in handoffs}
    handoff_by_package = {item["package_id"]: item for item in handoffs}
    dependents: dict[str, set[str]] = {item["package_id"]: set() for item in handoffs}
    indegree: dict[str, int] = {}
    for item in handoffs:
        package_id = item["package_id"]
        indegree[package_id] = len(item["depends_on"])
        for dependency in item["depends_on"]:
            if dependency == package_id:
                raise ReviewError(f"package {package_id!r} cannot depend on itself")
            if dependency not in package_to_handoff:
                raise ReviewError(f"package {package_id!r} has an unknown dependency")
            dependents[dependency].add(package_id)

    ready: list[tuple[str, str]] = [
        (package_to_handoff[package_id], package_id)
        for package_id, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)
    order: list[str] = []
    package_order: list[str] = []
    while ready:
        handoff_id, package_id = heapq.heappop(ready)
        order.append(handoff_id)
        package_order.append(package_id)
        for dependent in dependents[package_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, (package_to_handoff[dependent], dependent))
    if len(order) != len(handoffs):
        raise ReviewError("handoff dependency graph contains a cycle")

    blocked_ancestors: dict[str, bool] = {}
    hold_ancestors: dict[str, bool] = {}
    for package_id in package_order:
        item = handoff_by_package[package_id]
        dependencies = item["depends_on"]
        blocked = any(
            handoff_by_package[dep]["status"] == "BLOCKED" or blocked_ancestors[dep]
            for dep in dependencies
        )
        held = any(
            handoff_by_package[dep]["status"] == "HOLD" or hold_ancestors[dep]
            for dep in dependencies
        )
        if blocked and item["status"] != "BLOCKED":
            raise ReviewError(f"package {package_id!r} depends on a blocked package")
        if held and item["status"] == "READY":
            raise ReviewError(f"package {package_id!r} depends on a held package")
        blocked_ancestors[package_id] = blocked
        hold_ancestors[package_id] = held
    return order, dependents, package_to_handoff


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReviewError(f"value cannot be canonically serialized: {exc}") from exc


def _fingerprint(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def template() -> dict[str, Any]:
    """Return a fresh minimal portfolio input."""
    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": "release-alpha",
        "handoffs": [
            {
                "handoff_id": "handoff-core",
                "package_id": "core",
                "executor_id": "luna-medium",
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
    """Validate and compile a portfolio without mutating it."""
    source_object = _object(source, "source")
    _fields(source_object, PORTFOLIO_FIELDS, "source")
    _integer_one(source_object["schema_version"], "schema_version")
    portfolio_id = _identifier(source_object["portfolio_id"], "portfolio_id")
    raw_handoffs = source_object["handoffs"]
    if not isinstance(raw_handoffs, list) or not 1 <= len(raw_handoffs) <= 32:
        raise ReviewError("handoffs must be an array containing 1 through 32 entries")
    handoffs = [_handoff(item, index) for index, item in enumerate(raw_handoffs)]
    handoff_ids = [item["handoff_id"] for item in handoffs]
    package_ids = [item["package_id"] for item in handoffs]
    if len(handoff_ids) != len(set(handoff_ids)):
        raise ReviewError("handoff IDs must be unique")
    if len(package_ids) != len(set(package_ids)):
        raise ReviewError("package IDs must be unique")
    _validate_paths(handoffs)
    topological_order, _, _ = _topology(handoffs)
    handoffs.sort(key=lambda item: item["handoff_id"])

    partitions = {
        name.lower(): sorted(
            item["handoff_id"] for item in handoffs if item["status"] == name
        )
        for name in ("READY", "HOLD", "BLOCKED")
    }
    executor_names = sorted({item["executor_id"] for item in handoffs})
    executors = {
        executor: sorted(
            item["handoff_id"] for item in handoffs if item["executor_id"] == executor
        )
        for executor in executor_names
    }
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": portfolio_id,
        "handoffs": handoffs,
        "topological_order": topological_order,
        "partitions": partitions,
        "executors": executors,
        "review_handoff_ids": list(partitions["ready"]),
    }
    snapshot["snapshot_fingerprint"] = _fingerprint(snapshot)
    return snapshot


def _validate_snapshot(source: Mapping[str, Any], field: str) -> dict[str, Any]:
    snapshot = _object(source, field)
    _fields(snapshot, SNAPSHOT_FIELDS, field)
    _integer_one(snapshot["schema_version"], f"{field}.schema_version")
    _identifier(snapshot["portfolio_id"], f"{field}.portfolio_id")
    _digest(snapshot["snapshot_fingerprint"], f"{field}.snapshot_fingerprint")
    partitions = _object(snapshot["partitions"], f"{field}.partitions")
    _fields(partitions, PARTITION_FIELDS, f"{field}.partitions")
    executors = _object(snapshot["executors"], f"{field}.executors")
    if any(not isinstance(key, str) for key in executors.keys()):
        raise ReviewError(f"{field}.executors keys must be strings")

    expected = compile_portfolio(
        {
            "schema_version": snapshot["schema_version"],
            "portfolio_id": snapshot["portfolio_id"],
            "handoffs": snapshot["handoffs"],
        }
    )
    for key in SNAPSHOT_FIELDS:
        if snapshot[key] != expected[key]:
            raise ReviewError(f"{field}.{key} does not match the derived snapshot")
    return expected


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Validate two compiled snapshots and report their review-relevant delta."""
    before_snapshot = _validate_snapshot(before, "before")
    after_snapshot = _validate_snapshot(after, "after")
    if before_snapshot["portfolio_id"] != after_snapshot["portfolio_id"]:
        raise ReviewError("snapshots have different portfolio IDs")

    before_by_id = {item["handoff_id"]: item for item in before_snapshot["handoffs"]}
    after_by_id = {item["handoff_id"]: item for item in after_snapshot["handoffs"]}
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    added = sorted(after_ids - before_ids)
    removed = sorted(before_ids - after_ids)
    changed = sorted(
        handoff_id
        for handoff_id in before_ids & after_ids
        if before_by_id[handoff_id] != after_by_id[handoff_id]
    )
    regressions = sorted(
        handoff_id
        for handoff_id in changed
        if STATE_ORDER[after_by_id[handoff_id]["status"]]
        < STATE_ORDER[before_by_id[handoff_id]["status"]]
    )
    progressions = sorted(
        handoff_id
        for handoff_id in changed
        if STATE_ORDER[after_by_id[handoff_id]["status"]]
        > STATE_ORDER[before_by_id[handoff_id]["status"]]
    )

    after_package_to_id = {
        item["package_id"]: item["handoff_id"] for item in after_snapshot["handoffs"]
    }
    dependents: dict[str, set[str]] = {handoff_id: set() for handoff_id in after_ids}
    for item in after_snapshot["handoffs"]:
        for dependency_package in item["depends_on"]:
            dependency_id = after_package_to_id[dependency_package]
            dependents[dependency_id].add(item["handoff_id"])
    affected = set(added) | set(changed)
    pending = list(affected)
    while pending:
        current = pending.pop()
        for dependent in dependents[current]:
            if dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)

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

"""Deterministic, read-only compilation and comparison of frozen handoffs."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any


class ReviewError(ValueError):
    """Raised when a portfolio or compiled snapshot violates the contract."""


_IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_STATUSES = {"READY", "HOLD", "BLOCKED"}
_RISKS = {"low", "medium", "high", "critical"}
_DEPTHS = {"TARGETED", "STANDARD", "DEEP"}
_HANDOFF_FIELDS = {
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
_SNAPSHOT_FIELDS = {
    "schema_version",
    "portfolio_id",
    "handoffs",
    "topological_order",
    "partitions",
    "executors",
    "review_handoff_ids",
    "snapshot_fingerprint",
}
_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in ("¹", "²", "³")
}


def _fail(message: str) -> None:
    raise ReviewError(message)


def _exact_mapping(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a mapping")
    try:
        keys = set(value.keys())
    except Exception as exc:
        raise ReviewError(f"{label} has invalid keys") from exc
    if keys != fields or any(not isinstance(key, str) for key in value.keys()):
        _fail(f"{label} must contain exactly {sorted(fields)!r}")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 64) or not _IDENTIFIER.fullmatch(value):
        _fail(f"{label} must be a lower-case hyphen identifier")
    return value


def _digest(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(f"{label} must be a lower-case SHA-256 digest")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail(f"{label} must be an array of strings")
    return list(value)


def _validate_path(path: str) -> None:
    if not path or "\\" in path or path.startswith("/") or ":" in path:
        _fail(f"invalid writable path: {path!r}")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in path):
        _fail(f"invalid writable path: {path!r}")
    components = path.split("/")
    if any(not component or component in {".", ".."} for component in components):
        _fail(f"invalid writable path: {path!r}")
    for component in components:
        if component.endswith((".", " ")):
            _fail(f"invalid writable path: {path!r}")
        if component.split(".", 1)[0].rstrip(" .").upper() in _DEVICE_NAMES:
            _fail(f"invalid writable path: {path!r}")


def _derived_depth(status: str, shared: bool, repairs: int, risk: str) -> str:
    if status != "READY" or shared or repairs > 0 or risk in {"high", "critical"}:
        return "DEEP"
    if risk == "medium":
        return "STANDARD"
    return "TARGETED"


def _normalize_handoff(value: Any, index: int) -> dict[str, Any]:
    source = _exact_mapping(value, _HANDOFF_FIELDS, f"handoffs[{index}]")
    handoff_id = _identifier(source["handoff_id"], f"handoffs[{index}].handoff_id")
    package_id = _identifier(source["package_id"], f"handoffs[{index}].package_id")
    executor_id = _identifier(source["executor_id"], f"handoffs[{index}].executor_id")
    depends_on = _string_list(source["depends_on"], f"handoffs[{index}].depends_on")
    for dependency in depends_on:
        _identifier(dependency, f"handoffs[{index}].depends_on")
    if len(set(depends_on)) != len(depends_on):
        _fail(f"handoffs[{index}].depends_on contains duplicates")
    writable_paths = _string_list(source["writable_paths"], f"handoffs[{index}].writable_paths")
    if not writable_paths:
        _fail(f"handoffs[{index}].writable_paths must not be empty")
    for path in writable_paths:
        _validate_path(path)
    if len(set(writable_paths)) != len(writable_paths):
        _fail(f"handoffs[{index}].writable_paths contains duplicates")

    candidate_digest = _digest(source["candidate_digest"], f"handoffs[{index}].candidate_digest")
    status = source["status"]
    if not isinstance(status, str) or status not in _STATUSES:
        _fail(f"handoffs[{index}].status is invalid")
    blocker_kind = source["blocker_kind"]
    if blocker_kind is not None and not isinstance(blocker_kind, str):
        _fail(f"handoffs[{index}].blocker_kind must be a string or null")
    blocker_digest = _digest(source["blocker_digest"], f"handoffs[{index}].blocker_digest", nullable=True)
    acceptance_passed = source["acceptance_passed"]
    if not isinstance(acceptance_passed, bool):
        _fail(f"handoffs[{index}].acceptance_passed must be boolean")
    if status == "READY":
        if not acceptance_passed or blocker_kind is not None or blocker_digest is not None:
            _fail("READY handoffs require passed acceptance and no blocker")
    elif status == "HOLD":
        if acceptance_passed or blocker_kind not in {"validation-failure", "open-risk"} or blocker_digest is None:
            _fail("HOLD handoffs require a validation or risk blocker")
    elif acceptance_passed or blocker_kind not in {
        "missing-input",
        "missing-authority",
        "missing-permission",
        "external-state",
    } or blocker_digest is None:
        _fail("BLOCKED handoffs require an external blocker")

    risk = source["risk"]
    if not isinstance(risk, str) or risk not in _RISKS:
        _fail(f"handoffs[{index}].risk is invalid")
    shared_interface = source["shared_interface"]
    if not isinstance(shared_interface, bool):
        _fail(f"handoffs[{index}].shared_interface must be boolean")
    repair_count = source["repair_count"]
    if isinstance(repair_count, bool) or not isinstance(repair_count, int) or not 0 <= repair_count <= 3:
        _fail(f"handoffs[{index}].repair_count must be an integer from 0 through 3")
    review_depth = source["review_depth"]
    if not isinstance(review_depth, str) or review_depth not in _DEPTHS or review_depth != _derived_depth(
        status, shared_interface, repair_count, risk
    ):
        _fail(f"handoffs[{index}].review_depth does not match the derived value")

    return {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "executor_id": executor_id,
        "depends_on": sorted(depends_on),
        "writable_paths": sorted(writable_paths),
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


def _topology(handoffs: list[dict[str, Any]]) -> tuple[list[str], dict[str, set[str]]]:
    by_package = {handoff["package_id"]: handoff for handoff in handoffs}
    dependents: dict[str, set[str]] = {package_id: set() for package_id in by_package}
    indegree: dict[str, int] = {}
    for handoff in handoffs:
        package_id = handoff["package_id"]
        dependencies = handoff["depends_on"]
        if package_id in dependencies:
            _fail(f"package {package_id!r} cannot depend on itself")
        for dependency in dependencies:
            if dependency not in by_package:
                _fail(f"unknown dependency: {dependency!r}")
            dependents[dependency].add(package_id)
        indegree[package_id] = len(dependencies)

    ready: list[tuple[str, str]] = [
        (handoff["handoff_id"], package_id)
        for package_id, handoff in by_package.items()
        if indegree[package_id] == 0
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
                heapq.heappush(ready, (by_package[dependent]["handoff_id"], dependent))
    if len(order) != len(handoffs):
        _fail("dependencies must form an acyclic graph")

    blocked_ancestors: dict[str, bool] = {}
    hold_ancestors: dict[str, bool] = {}
    for package_id in package_order:
        handoff = by_package[package_id]
        dependencies = handoff["depends_on"]
        has_blocked = any(
            by_package[dependency]["status"] == "BLOCKED" or blocked_ancestors[dependency]
            for dependency in dependencies
        )
        has_hold = any(
            by_package[dependency]["status"] == "HOLD" or hold_ancestors[dependency]
            for dependency in dependencies
        )
        if has_blocked and handoff["status"] != "BLOCKED":
            _fail(f"package {package_id!r} depends on BLOCKED")
        if has_hold and handoff["status"] == "READY":
            _fail(f"package {package_id!r} depends on HOLD")
        blocked_ancestors[package_id] = has_blocked
        hold_ancestors[package_id] = has_hold
    return order, dependents


def _validate_path_partition(handoffs: list[dict[str, Any]]) -> None:
    seen: list[tuple[str, str]] = []
    for handoff in handoffs:
        for path in handoff["writable_paths"]:
            folded = path.casefold()
            for other, other_folded in seen:
                if folded == other_folded or folded.startswith(other_folded + "/") or other_folded.startswith(folded + "/"):
                    _fail(f"writable paths overlap: {other!r} and {path!r}")
            seen.append((path, folded))


def template() -> dict:
    """Return one valid minimal source portfolio."""
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


def compile_portfolio(source: Mapping[str, Any]) -> dict:
    """Validate and compile a portfolio without mutating *source*."""
    source = _exact_mapping(source, {"schema_version", "portfolio_id", "handoffs"}, "portfolio")
    if type(source["schema_version"]) is not int or source["schema_version"] != 1:
        _fail("schema_version must be 1")
    portfolio_id = _identifier(source["portfolio_id"], "portfolio_id")
    raw_handoffs = source["handoffs"]
    if not isinstance(raw_handoffs, list) or not 1 <= len(raw_handoffs) <= 32:
        _fail("handoffs must contain 1 through 32 entries")
    handoffs = [_normalize_handoff(value, index) for index, value in enumerate(raw_handoffs)]
    handoff_ids = [handoff["handoff_id"] for handoff in handoffs]
    package_ids = [handoff["package_id"] for handoff in handoffs]
    if len(set(handoff_ids)) != len(handoff_ids):
        _fail("handoff IDs must be unique")
    if len(set(package_ids)) != len(package_ids):
        _fail("package IDs must be unique")
    _validate_path_partition(handoffs)
    topological_order, _ = _topology(handoffs)
    handoffs.sort(key=lambda handoff: handoff["handoff_id"])

    partitions = {
        "ready": sorted(handoff["handoff_id"] for handoff in handoffs if handoff["status"] == "READY"),
        "hold": sorted(handoff["handoff_id"] for handoff in handoffs if handoff["status"] == "HOLD"),
        "blocked": sorted(handoff["handoff_id"] for handoff in handoffs if handoff["status"] == "BLOCKED"),
    }
    executors: dict[str, list[str]] = {}
    for executor_id in sorted({handoff["executor_id"] for handoff in handoffs}):
        executors[executor_id] = sorted(
            handoff["handoff_id"] for handoff in handoffs if handoff["executor_id"] == executor_id
        )
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "portfolio_id": portfolio_id,
        "handoffs": handoffs,
        "topological_order": topological_order,
        "partitions": partitions,
        "executors": executors,
        "review_handoff_ids": list(partitions["ready"]),
    }
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    snapshot["snapshot_fingerprint"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return snapshot


def _validated_snapshot(value: Any, label: str) -> dict[str, Any]:
    source = _exact_mapping(value, _SNAPSHOT_FIELDS, label)
    expected = compile_portfolio(
        {
            "schema_version": source["schema_version"],
            "portfolio_id": source["portfolio_id"],
            "handoffs": source["handoffs"],
        }
    )
    if source != expected:
        _fail(f"{label} has invalid derived fields or fingerprint")
    return expected


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict:
    """Compare two completely validated compiled snapshots."""
    before_snapshot = _validated_snapshot(before, "before snapshot")
    after_snapshot = _validated_snapshot(after, "after snapshot")
    if before_snapshot["portfolio_id"] != after_snapshot["portfolio_id"]:
        _fail("portfolio IDs differ")

    before_by_id = {handoff["handoff_id"]: handoff for handoff in before_snapshot["handoffs"]}
    after_by_id = {handoff["handoff_id"]: handoff for handoff in after_snapshot["handoffs"]}
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    added = after_ids - before_ids
    removed = before_ids - after_ids
    changed = {
        handoff_id for handoff_id in before_ids & after_ids if before_by_id[handoff_id] != after_by_id[handoff_id]
    }
    state_rank = {"BLOCKED": 0, "HOLD": 1, "READY": 2}
    regressions = sorted(
        handoff_id
        for handoff_id in changed
        if state_rank[after_by_id[handoff_id]["status"]] < state_rank[before_by_id[handoff_id]["status"]]
    )
    progressions = sorted(
        handoff_id
        for handoff_id in changed
        if state_rank[after_by_id[handoff_id]["status"]] > state_rank[before_by_id[handoff_id]["status"]]
    )

    package_to_handoff = {handoff["package_id"]: handoff["handoff_id"] for handoff in after_snapshot["handoffs"]}
    dependents: dict[str, set[str]] = {handoff_id: set() for handoff_id in after_ids}
    for handoff in after_snapshot["handoffs"]:
        for dependency in handoff["depends_on"]:
            dependents[package_to_handoff[dependency]].add(handoff["handoff_id"])
    affected = set(added | changed)
    frontier = list(affected)
    while frontier:
        handoff_id = frontier.pop()
        for dependent in dependents[handoff_id]:
            if dependent not in affected:
                affected.add(dependent)
                frontier.append(dependent)

    return {
        "schema_version": 1,
        "portfolio_id": before_snapshot["portfolio_id"],
        "before_fingerprint": before_snapshot["snapshot_fingerprint"],
        "after_fingerprint": after_snapshot["snapshot_fingerprint"],
        "added_handoff_ids": sorted(added),
        "removed_handoff_ids": sorted(removed),
        "changed_handoff_ids": sorted(changed),
        "state_regressions": regressions,
        "state_progressions": progressions,
        "affected_review_handoff_ids": sorted(affected),
    }

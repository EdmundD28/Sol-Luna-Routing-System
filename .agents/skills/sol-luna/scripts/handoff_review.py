#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, read-only review planning for frozen handoff portfolios.

The functions in this module validate a complete candidate-bound portfolio,
compile it into a canonical snapshot, and compare two such snapshots.  They
deliberately have no filesystem, process, network, or dispatch side effects.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import unicodedata
from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
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
HOLD_BLOCKERS = {"validation-failure", "open-risk"}
BLOCKED_BLOCKERS = {
    "missing-input",
    "missing-authority",
    "missing-permission",
    "external-state",
}
RISKS = {"low", "medium", "high", "critical"}
REVIEW_DEPTHS = {"TARGETED", "STANDARD", "DEEP"}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{index}"
    for prefix in ("com", "lpt")
    for index in range(1, 10)
}
# Windows also recognises the superscript forms as device-name suffixes.
WINDOWS_RESERVED |= {f"{prefix}{suffix}" for prefix in ("com", "lpt") for suffix in ("¹", "²", "³")}

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
    """The input is malformed or violates the handoff-review contract."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewError(f"{field} must be an object")
    return value


def _fields(
    value: Mapping[str, Any],
    allowed: set[str],
    required: set[str],
    field: str,
) -> None:
    try:
        keys = list(value.keys())
    except Exception as exc:  # pragma: no cover - defensive for hostile mappings
        raise ReviewError(f"{field} keys cannot be read") from exc
    if any(not isinstance(key, str) for key in keys):
        raise ReviewError(f"{field} keys must be strings")
    key_set = set(keys)
    unknown = key_set - allowed
    missing = required - key_set
    if unknown:
        raise ReviewError(f"{field} has unsupported fields: {sorted(unknown)}")
    if missing:
        raise ReviewError(f"{field} is missing required fields: {sorted(missing)}")


def _schema_version(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != SCHEMA_VERSION:
        raise ReviewError(f"{field} must be schema version {SCHEMA_VERSION}")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) < 1 or len(value) > 64:
        raise ReviewError(f"{field} must be a lowercase ASCII identifier")
    if IDENTIFIER.fullmatch(value) is None:
        raise ReviewError(f"{field} must be a lowercase ASCII identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise ReviewError(f"{field} must be a lowercase sha256 digest")
    return value


def _enum(value: Any, choices: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ReviewError(f"{field} has an unsupported value")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReviewError(f"{field} must be a boolean")
    return value


def _path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewError(f"{field} must be a normalized relative POSIX path")
    if "\\" in value or ":" in value or PurePosixPath(value).is_absolute():
        raise ReviewError(f"{field} must be a normalized relative POSIX path")
    windows = PureWindowsPath(value)
    if windows.drive or windows.root:
        raise ReviewError(f"{field} must not be an absolute or drive path")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise ReviewError(f"{field} contains a control or surrogate character")

    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReviewError(f"{field} contains an unsafe path segment")
    if any(part.endswith((".", " ")) for part in parts):
        raise ReviewError(f"{field} contains a trailing dot or space")
    for part in parts:
        # A colon was rejected above, including all alternate-data-stream
        # spellings.  Strip an extension only for the Windows device-name
        # check (for example, ``con.txt`` is still reserved).
        device_base = re.split(r"[.:]", part.rstrip(" ."), maxsplit=1)[0].rstrip(" .").casefold()
        if device_base in WINDOWS_RESERVED:
            raise ReviewError(f"{field} contains a reserved Windows device name")

    normalized = "/".join(PurePosixPath(value).parts)
    if normalized != value:
        raise ReviewError(f"{field} must use normalized POSIX spelling")
    return value


def _paths(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ReviewError(f"{field} must be a non-empty array")
    result = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise ReviewError(f"{field} contains duplicate paths")
    return sorted(result)


def _identifiers(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ReviewError(f"{field} must be an array")
    result = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ReviewError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _has_path_overlap(paths: list[str]) -> bool:
    folded = sorted(path.casefold() for path in paths)
    for index, left in enumerate(folded):
        for right in folded[index + 1 :]:
            if right == left or right.startswith(left + "/"):
                return True
    return False


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReviewError(f"cannot canonicalize value: {exc}") from exc
    return serialized.encode("utf-8")


def _fingerprint(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _validate_handoff(raw: Any, index: int) -> dict[str, Any]:
    item = _object(raw, f"handoffs[{index}]")
    _fields(item, HANDOFF_FIELDS, HANDOFF_FIELDS, f"handoffs[{index}]")
    handoff_id = _identifier(item["handoff_id"], f"handoffs[{index}].handoff_id")
    package_id = _identifier(item["package_id"], f"handoffs[{index}].package_id")
    executor_id = _identifier(item["executor_id"], f"handoffs[{index}].executor_id")
    depends_on = _identifiers(item["depends_on"], f"handoffs[{index}].depends_on")
    writable_paths = _paths(item["writable_paths"], f"handoffs[{index}].writable_paths")
    candidate_digest = _digest(item["candidate_digest"], f"handoffs[{index}].candidate_digest")
    status = _enum(item["status"], STATUSES, f"handoffs[{index}].status")
    blocker_kind = item["blocker_kind"]
    blocker_digest = item["blocker_digest"]
    if status == "READY":
        if blocker_kind is not None or blocker_digest is not None:
            raise ReviewError(f"handoffs[{index}] READY handoffs cannot have blockers")
    elif status == "HOLD":
        blocker_kind = _enum(blocker_kind, HOLD_BLOCKERS, f"handoffs[{index}].blocker_kind")
        blocker_digest = _digest(blocker_digest, f"handoffs[{index}].blocker_digest")
    else:
        blocker_kind = _enum(blocker_kind, BLOCKED_BLOCKERS, f"handoffs[{index}].blocker_kind")
        blocker_digest = _digest(blocker_digest, f"handoffs[{index}].blocker_digest")
    acceptance_passed = _boolean(
        item["acceptance_passed"], f"handoffs[{index}].acceptance_passed"
    )
    risk = _enum(item["risk"], RISKS, f"handoffs[{index}].risk")
    shared_interface = _boolean(item["shared_interface"], f"handoffs[{index}].shared_interface")
    repair_count = item["repair_count"]
    if isinstance(repair_count, bool) or not isinstance(repair_count, int) or not 0 <= repair_count <= 3:
        raise ReviewError(f"handoffs[{index}].repair_count must be an integer from 0 through 3")
    review_depth = _enum(item["review_depth"], REVIEW_DEPTHS, f"handoffs[{index}].review_depth")

    if status == "READY":
        if not acceptance_passed:
            raise ReviewError(f"handoffs[{index}] READY handoffs require acceptance_passed=true")
    elif acceptance_passed:
        raise ReviewError(f"handoffs[{index}] non-READY handoffs require acceptance_passed=false")

    derived_depth = "DEEP" if (
        status != "READY"
        or shared_interface
        or repair_count > 0
        or risk in {"high", "critical"}
    ) else ("STANDARD" if risk == "medium" else "TARGETED")
    if review_depth != derived_depth:
        raise ReviewError(f"handoffs[{index}].review_depth does not match derived review depth")

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


def _validate_source(source: Any) -> tuple[int, str, list[dict[str, Any]]]:
    portfolio = _object(source, "portfolio")
    _fields(portfolio, PORTFOLIO_FIELDS, PORTFOLIO_FIELDS, "portfolio")
    schema_version = _schema_version(portfolio["schema_version"], "schema_version")
    portfolio_id = _identifier(portfolio["portfolio_id"], "portfolio_id")
    raw_handoffs = portfolio["handoffs"]
    if not isinstance(raw_handoffs, list) or not 1 <= len(raw_handoffs) <= 32:
        raise ReviewError("handoffs must be an array containing 1 through 32 entries")
    handoffs = [_validate_handoff(raw, index) for index, raw in enumerate(raw_handoffs)]

    handoff_ids = [handoff["handoff_id"] for handoff in handoffs]
    package_ids = [handoff["package_id"] for handoff in handoffs]
    if len(handoff_ids) != len(set(handoff_ids)):
        raise ReviewError("handoff_id values must be unique")
    if len(package_ids) != len(set(package_ids)):
        raise ReviewError("package_id values must be unique")
    package_to_handoff = {handoff["package_id"]: handoff for handoff in handoffs}
    for index, handoff in enumerate(handoffs):
        for dependency in handoff["depends_on"]:
            if dependency == handoff["package_id"]:
                raise ReviewError(f"handoffs[{index}] cannot depend on itself")
            if dependency not in package_to_handoff:
                raise ReviewError(f"handoffs[{index}] depends on an unknown package")

    all_paths = [path for handoff in handoffs for path in handoff["writable_paths"]]
    if _has_path_overlap(all_paths):
        raise ReviewError("writable_paths contain a case-insensitive ancestor or descendant overlap")

    _topological_order(handoffs, package_to_handoff)
    _validate_dependency_states(handoffs, package_to_handoff)
    return schema_version, portfolio_id, handoffs


def _topological_order(
    handoffs: list[dict[str, Any]], package_to_handoff: Mapping[str, dict[str, Any]]
) -> list[str]:
    """Return a deterministic package-dependency topological order."""

    indegree = {handoff["handoff_id"]: len(handoff["depends_on"]) for handoff in handoffs}
    dependents: dict[str, list[str]] = {handoff["package_id"]: [] for handoff in handoffs}
    by_id = {handoff["handoff_id"]: handoff for handoff in handoffs}
    for handoff in handoffs:
        for dependency in handoff["depends_on"]:
            dependents[dependency].append(handoff["handoff_id"])
    for values in dependents.values():
        values.sort()

    ready = [handoff_id for handoff_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    result: list[str] = []
    while ready:
        current_id = heapq.heappop(ready)
        result.append(current_id)
        current_package = by_id[current_id]["package_id"]
        for dependent_id in dependents[current_package]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                heapq.heappush(ready, dependent_id)
    if len(result) != len(handoffs):
        raise ReviewError("depends_on must form an acyclic graph")
    return result


def _validate_dependency_states(
    handoffs: list[dict[str, Any]], package_to_handoff: Mapping[str, dict[str, Any]]
) -> None:
    memo: dict[tuple[str, str], bool] = {}

    def has_ancestor(package_id: str, status: str) -> bool:
        key = (package_id, status)
        if key in memo:
            return memo[key]
        handoff = package_to_handoff[package_id]
        result = handoff["status"] == status or any(
            has_ancestor(dependency, status) for dependency in handoff["depends_on"]
        )
        memo[key] = result
        return result

    for handoff in handoffs:
        if handoff["status"] != "BLOCKED" and any(
            has_ancestor(dependency, "BLOCKED") for dependency in handoff["depends_on"]
        ):
            raise ReviewError("a handoff depending on BLOCKED must also be BLOCKED")
        if handoff["status"] == "READY" and any(
            has_ancestor(dependency, "HOLD") for dependency in handoff["depends_on"]
        ):
            raise ReviewError("a READY handoff cannot depend on HOLD")


def _compile_normalized(
    schema_version: int, portfolio_id: str, handoffs: list[dict[str, Any]]
) -> dict[str, Any]:
    ordered_handoffs = sorted(handoffs, key=lambda handoff: handoff["handoff_id"])
    package_to_handoff = {handoff["package_id"]: handoff for handoff in ordered_handoffs}
    topological_order = _topological_order(ordered_handoffs, package_to_handoff)
    partitions = {
        status.lower(): sorted(
            handoff["handoff_id"] for handoff in ordered_handoffs if handoff["status"] == status
        )
        for status in ("READY", "HOLD", "BLOCKED")
    }
    executors: dict[str, list[str]] = {}
    for handoff in ordered_handoffs:
        executors.setdefault(handoff["executor_id"], []).append(handoff["handoff_id"])
    executors = {executor: sorted(ids) for executor, ids in sorted(executors.items())}
    snapshot_without_fingerprint = {
        "schema_version": schema_version,
        "portfolio_id": portfolio_id,
        "handoffs": ordered_handoffs,
        "topological_order": topological_order,
        "partitions": partitions,
        "executors": executors,
        "review_handoff_ids": list(partitions["ready"]),
    }
    return {
        **snapshot_without_fingerprint,
        "snapshot_fingerprint": _fingerprint(snapshot_without_fingerprint),
    }


def template() -> dict[str, Any]:
    """Return a fresh, complete, READY portfolio input template."""

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
    """Validate and compile one portfolio into its canonical snapshot."""

    schema_version, portfolio_id, handoffs = _validate_source(source)
    return _compile_normalized(schema_version, portfolio_id, handoffs)


def _validate_snapshot(snapshot: Any) -> dict[str, Any]:
    value = _object(snapshot, "snapshot")
    _fields(value, SNAPSHOT_FIELDS, SNAPSHOT_FIELDS, "snapshot")
    # Validate the source part first, then compare every derived field with a
    # fresh compilation.  This checks topology, partitions, executors, review
    # depth and fingerprint without trusting any caller-supplied derived data.
    source = {
        "schema_version": value["schema_version"],
        "portfolio_id": value["portfolio_id"],
        "handoffs": value["handoffs"],
    }
    expected = compile_portfolio(source)
    if value != expected:
        raise ReviewError("snapshot derived fields or normalized handoffs are inconsistent")
    return expected


def _transitive_dependents(
    seeds: set[str], handoffs: list[dict[str, Any]]
) -> set[str]:
    package_to_id = {handoff["package_id"]: handoff["handoff_id"] for handoff in handoffs}
    dependents: dict[str, set[str]] = {handoff["package_id"]: set() for handoff in handoffs}
    for handoff in handoffs:
        for dependency in handoff["depends_on"]:
            dependents[dependency].add(handoff["package_id"])

    package_seeds = {
        handoff["package_id"]
        for handoff in handoffs
        if handoff["handoff_id"] in seeds
    }
    affected_packages = set(package_seeds)
    queue = list(package_seeds)
    while queue:
        package_id = queue.pop()
        for dependent in dependents.get(package_id, set()):
            if dependent not in affected_packages:
                affected_packages.add(dependent)
                queue.append(dependent)
    return {package_to_id[package_id] for package_id in affected_packages}


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two complete snapshots and identify review-affected handoffs."""

    before_snapshot = _validate_snapshot(before)
    after_snapshot = _validate_snapshot(after)
    if before_snapshot["portfolio_id"] != after_snapshot["portfolio_id"]:
        raise ReviewError("snapshots must belong to the same portfolio_id")

    before_by_id = {handoff["handoff_id"]: handoff for handoff in before_snapshot["handoffs"]}
    after_by_id = {handoff["handoff_id"]: handoff for handoff in after_snapshot["handoffs"]}
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    added = sorted(after_ids - before_ids)
    removed = sorted(before_ids - after_ids)
    changed = sorted(
        handoff_id
        for handoff_id in before_ids & after_ids
        if before_by_id[handoff_id] != after_by_id[handoff_id]
    )

    state_order = {"BLOCKED": 0, "HOLD": 1, "READY": 2}
    regressions: list[str] = []
    progressions: list[str] = []
    for handoff_id in before_ids & after_ids:
        before_state = state_order[before_by_id[handoff_id]["status"]]
        after_state = state_order[after_by_id[handoff_id]["status"]]
        if after_state < before_state:
            regressions.append(handoff_id)
        elif after_state > before_state:
            progressions.append(handoff_id)

    seeds = set(added) | set(changed)
    affected = sorted(_transitive_dependents(seeds, after_snapshot["handoffs"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": before_snapshot["portfolio_id"],
        "before_fingerprint": before_snapshot["snapshot_fingerprint"],
        "after_fingerprint": after_snapshot["snapshot_fingerprint"],
        "added_handoff_ids": added,
        "removed_handoff_ids": removed,
        "changed_handoff_ids": changed,
        "state_regressions": sorted(regressions),
        "state_progressions": sorted(progressions),
        "affected_review_handoff_ids": affected,
    }

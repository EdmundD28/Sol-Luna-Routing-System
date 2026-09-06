#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Project deterministic Sol/Luna work frontiers without dispatching work."""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
import unicodedata
from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
TOP_FIELDS = {
    "schema_version",
    "controller_id",
    "writer_cap",
    "packages",
    "plan_fingerprint",
}
TOP_REQUIRED_FIELDS = TOP_FIELDS - {"plan_fingerprint"}
PACKAGE_FIELDS = {
    "package_id",
    "executor",
    "domain_id",
    "dependencies",
    "path_scopes",
    "acceptance_ids",
    "baseline_sol_weight",
    "predicted_executor_weight",
    "incremental_sol_weight",
    "expected_seconds",
    "critical_path",
    "status",
    "repair",
}
REPAIR_FIELDS = {
    "attempts_used",
    "attempts_max",
    "remaining_cost_weight",
    "next_cost_weight",
    "marginal_net_substitution",
    "new_evidence",
}
EXECUTORS = {"SOL", "LUNA"}
STATUSES = {"PENDING", "RUNNING", "HANDOFF", "ACCEPTED", "FAILED", "RECLAIMED"}
TERMINAL_DEPENDENCY_STATUSES = {"ACCEPTED", "RECLAIMED"}
WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
RESULT_FIELDS = {
    "schema_version",
    "status",
    "plan_fingerprint",
    "luna_envelope",
    "sol_ready_package_ids",
    "review_package_ids",
    "repair_package_ids",
    "blocked_package_reasons",
    "running_luna_package_ids",
    "tail_wait_allowed",
    "automatic_execution_allowed",
}


class FrontierError(ValueError):
    """The frontier source is malformed or unsafe to project."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FrontierError(f"{field} must be a JSON object")
    return value


def _fields(
    value: Mapping[str, Any],
    allowed: set[str],
    required: set[str],
    field: str,
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise FrontierError(f"{field} has unknown fields: {sorted(unknown, key=repr)}")
    if missing:
        raise FrontierError(f"{field} is missing required fields: {sorted(missing)}")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise FrontierError(f"{field} must be a lowercase ASCII identifier")
    return value


def _integer(value: Any, field: str, *, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int:
        raise FrontierError(f"{field} must be an integer")
    if value < minimum:
        raise FrontierError(f"{field} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise FrontierError(f"{field} must be at most {maximum}")
    return value


def _finite(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrontierError(f"{field} must be a finite number")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        raise FrontierError(f"{field} must be a finite number") from None
    if not math.isfinite(normalized):
        raise FrontierError(f"{field} must be a finite number")
    if normalized < 0 or (positive and normalized <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise FrontierError(f"{field} must be {qualifier}")
    return normalized


def _identifier_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise FrontierError(f"{field} must be a JSON array")
    normalized = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(normalized) != len(set(normalized)):
        raise FrontierError(f"{field} contains duplicates")
    return sorted(normalized)


def _path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FrontierError(f"{field} must be a normalized relative POSIX path")
    if "\\" in value or value.startswith("/") or re.match(r"[A-Za-z]:", value):
        raise FrontierError(f"{field} must be a normalized relative POSIX path")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise FrontierError(f"{field} contains a control character")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or posixpath.normpath(value) != value:
        raise FrontierError(f"{field} must be a normalized relative POSIX path")
    for part in parts:
        device_stem = part.rstrip(" .").split(".", 1)[0].rstrip(" ").upper()
        if device_stem in WINDOWS_DEVICE_NAMES:
            raise FrontierError(f"{field} contains a Windows device name")
    return value


def _path_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise FrontierError(f"{field} must be a JSON array")
    normalized = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    folded = [item.casefold() for item in normalized]
    if len(folded) != len(set(folded)):
        raise FrontierError(f"{field} contains duplicate paths")
    return sorted(normalized)


def _repair(value: Any, field: str) -> dict[str, Any]:
    source = _object(value, field)
    _fields(source, REPAIR_FIELDS, REPAIR_FIELDS, field)
    attempts_used = _integer(source["attempts_used"], f"{field}.attempts_used", minimum=0)
    attempts_max = _integer(source["attempts_max"], f"{field}.attempts_max", minimum=0)
    if attempts_used > attempts_max:
        raise FrontierError(f"{field}.attempts_used must not exceed attempts_max")
    if type(source["new_evidence"]) is not bool:
        raise FrontierError(f"{field}.new_evidence must be a boolean")
    return {
        "attempts_used": attempts_used,
        "attempts_max": attempts_max,
        "remaining_cost_weight": _finite(
            source["remaining_cost_weight"], f"{field}.remaining_cost_weight"
        ),
        "next_cost_weight": _finite(source["next_cost_weight"], f"{field}.next_cost_weight"),
        "marginal_net_substitution": _finite(
            source["marginal_net_substitution"], f"{field}.marginal_net_substitution"
        ),
        "new_evidence": source["new_evidence"],
    }


def _package(value: Any, index: int) -> dict[str, Any]:
    field = f"packages[{index}]"
    source = _object(value, field)
    _fields(source, PACKAGE_FIELDS, PACKAGE_FIELDS, field)
    executor = source["executor"]
    if not isinstance(executor, str) or executor not in EXECUTORS:
        raise FrontierError(f"{field}.executor must be one of {sorted(EXECUTORS)}")
    status = source["status"]
    if not isinstance(status, str) or status not in STATUSES:
        raise FrontierError(f"{field}.status must be one of {sorted(STATUSES)}")
    if type(source["critical_path"]) is not bool:
        raise FrontierError(f"{field}.critical_path must be a boolean")
    raw_repair = source["repair"]
    if status == "FAILED":
        if raw_repair is None:
            raise FrontierError(f"{field}.repair is required when status is FAILED")
        repair = _repair(raw_repair, f"{field}.repair")
    else:
        if raw_repair is not None:
            raise FrontierError(f"{field}.repair must be null unless status is FAILED")
        repair = None
    normalized = {
        "package_id": _identifier(source["package_id"], f"{field}.package_id"),
        "executor": executor,
        "domain_id": _identifier(source["domain_id"], f"{field}.domain_id"),
        "dependencies": _identifier_list(source["dependencies"], f"{field}.dependencies"),
        "path_scopes": _path_list(source["path_scopes"], f"{field}.path_scopes"),
        "acceptance_ids": _identifier_list(source["acceptance_ids"], f"{field}.acceptance_ids"),
        "baseline_sol_weight": _finite(
            source["baseline_sol_weight"], f"{field}.baseline_sol_weight", positive=True
        ),
        "predicted_executor_weight": _finite(
            source["predicted_executor_weight"], f"{field}.predicted_executor_weight"
        ),
        "incremental_sol_weight": _finite(
            source["incremental_sol_weight"], f"{field}.incremental_sol_weight"
        ),
        "expected_seconds": _finite(
            source["expected_seconds"], f"{field}.expected_seconds", positive=True
        ),
        "critical_path": source["critical_path"],
        "status": status,
        "repair": repair,
    }
    net_substitution = (
        normalized["baseline_sol_weight"]
        - normalized["predicted_executor_weight"]
        - normalized["incremental_sol_weight"]
    )
    if not math.isfinite(net_substitution):
        raise FrontierError(f"{field} net substitution must remain finite")
    normalized["net_substitution"] = net_substitution
    return normalized


def _canonical_package(package: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in package.items() if key != "net_substitution"}


def _fingerprint(source: Mapping[str, Any]) -> str:
    canonical = {
        "schema_version": source["schema_version"],
        "controller_id": source["controller_id"],
        "writer_cap": source["writer_cap"],
        "packages": [_canonical_package(package) for package in source["packages"]],
    }
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise FrontierError("canonical plan must be finite JSON") from None
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate(source: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    source = _object(source, "input")
    _fields(source, TOP_FIELDS, TOP_REQUIRED_FIELDS, "input")
    if type(source["schema_version"]) is not int or source["schema_version"] != SCHEMA_VERSION:
        raise FrontierError("schema_version must be integer 1")
    writer_cap = _integer(source["writer_cap"], "writer_cap", minimum=1, maximum=8)
    packages_source = source["packages"]
    if not isinstance(packages_source, list) or not packages_source:
        raise FrontierError("packages must be a non-empty JSON array")
    packages = sorted(
        (_package(value, index) for index, value in enumerate(packages_source)),
        key=lambda item: item["package_id"],
    )
    package_ids = [package["package_id"] for package in packages]
    if len(package_ids) != len(set(package_ids)):
        raise FrontierError("package_id values must be globally unique")
    acceptance_ids = [
        acceptance_id for package in packages for acceptance_id in package["acceptance_ids"]
    ]
    if len(acceptance_ids) != len(set(acceptance_ids)):
        raise FrontierError("acceptance_ids must be globally unique")

    known_ids = set(package_ids)
    package_by_id = {package["package_id"]: package for package in packages}
    for package in packages:
        package_id = package["package_id"]
        for dependency in package["dependencies"]:
            if dependency == package_id:
                raise FrontierError(f"package {package_id} cannot depend on itself")
            if dependency not in known_ids:
                raise FrontierError(f"package {package_id} has unknown dependency: {dependency}")

    remaining_dependencies = {
        package["package_id"]: set(package["dependencies"]) for package in packages
    }
    dependents: dict[str, list[str]] = {package_id: [] for package_id in package_ids}
    for package_id, dependencies in remaining_dependencies.items():
        for dependency in dependencies:
            dependents[dependency].append(package_id)
    ready = sorted(package_id for package_id, dependencies in remaining_dependencies.items() if not dependencies)
    visited = 0
    while ready:
        package_id = ready.pop(0)
        visited += 1
        for dependent in dependents[package_id]:
            remaining_dependencies[dependent].discard(package_id)
            if not remaining_dependencies[dependent]:
                ready.append(dependent)
        ready.sort()
    if visited != len(packages):
        raise FrontierError("package dependencies must form a directed acyclic graph")

    scoped_paths: list[tuple[str, str]] = []
    for package in packages:
        for path in package["path_scopes"]:
            folded = path.casefold()
            for other_package_id, other_folded in scoped_paths:
                if other_package_id == package["package_id"]:
                    continue
                if (
                    folded == other_folded
                    or folded.startswith(other_folded + "/")
                    or other_folded.startswith(folded + "/")
                ):
                    raise FrontierError(
                        f"path scopes overlap across packages: {other_package_id} and {package['package_id']}"
                    )
            scoped_paths.append((package["package_id"], folded))

    running_count = 0
    for package in packages:
        if package["status"] == "RUNNING":
            running_count += 1
            if package["executor"] != "LUNA":
                raise FrontierError("a RUNNING package must use executor LUNA")
        if package["status"] != "PENDING":
            unresolved = [
                dependency
                for dependency in package["dependencies"]
                if package_by_id[dependency]["status"] not in TERMINAL_DEPENDENCY_STATUSES
            ]
            if unresolved:
                raise FrontierError(
                    f"non-PENDING package {package['package_id']} has non-terminal dependencies"
                )
    if running_count > writer_cap:
        raise FrontierError("RUNNING package count exceeds writer_cap")

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "controller_id": _identifier(source["controller_id"], "controller_id"),
        "writer_cap": writer_cap,
        "packages": packages,
    }
    fingerprint = _fingerprint(normalized)
    if "plan_fingerprint" in source:
        supplied = source["plan_fingerprint"]
        if not isinstance(supplied, str) or not FINGERPRINT.fullmatch(supplied):
            raise FrontierError("plan_fingerprint must be a lowercase SHA-256 fingerprint")
        if supplied != fingerprint:
            raise FrontierError("plan_fingerprint does not match the normalized plan")
    return normalized, fingerprint


def template() -> dict:
    """Return a complete schema-1 example suitable for immediate evaluation."""

    return {
        "schema_version": 1,
        "controller_id": "sol-controller",
        "writer_cap": 1,
        "packages": [
            {
                "package_id": "core-a",
                "executor": "LUNA",
                "domain_id": "routing",
                "dependencies": [],
                "path_scopes": ["src/core-a"],
                "acceptance_ids": ["accept-core-a"],
                "baseline_sol_weight": 8.0,
                "predicted_executor_weight": 2.0,
                "incremental_sol_weight": 1.0,
                "expected_seconds": 120.0,
                "critical_path": True,
                "status": "PENDING",
                "repair": None,
            }
        ],
    }


def _repair_is_eligible(package: Mapping[str, Any]) -> bool:
    repair = package["repair"]
    return bool(
        package["executor"] == "LUNA"
        and package["status"] == "FAILED"
        and repair["new_evidence"]
        and repair["attempts_used"] < repair["attempts_max"]
        and repair["next_cost_weight"] > 0
        and repair["next_cost_weight"] <= repair["remaining_cost_weight"]
        and repair["marginal_net_substitution"] > 0
    )


def plan(source: Mapping[str, Any]) -> dict:
    """Validate *source* and return its deterministic replay-only frontier.

    Identifier and path arrays are canonical sets: duplicate members are
    rejected. An eligible same-Luna repair occupies the Luna writer frontier
    before any new retained-domain envelope is offered.
    """

    normalized, fingerprint = _validate(source)
    packages = normalized["packages"]
    package_by_id = {package["package_id"]: package for package in packages}

    def dependency_ready(package: Mapping[str, Any]) -> bool:
        return all(
            package_by_id[dependency]["status"] in TERMINAL_DEPENDENCY_STATUSES
            for dependency in package["dependencies"]
        )

    sol_ready: list[str] = []
    blocked: dict[str, list[str]] = {}
    eligible_luna: list[dict[str, Any]] = []
    for package in packages:
        if package["status"] != "PENDING":
            continue
        ready = dependency_ready(package)
        if package["executor"] == "SOL":
            if ready:
                sol_ready.append(package["package_id"])
            else:
                blocked[package["package_id"]] = ["dependency-not-terminal"]
            continue
        reasons = []
        if not ready:
            reasons.append("dependency-not-terminal")
        if package["net_substitution"] <= 0:
            reasons.append("nonpositive-net-substitution")
        if reasons:
            blocked[package["package_id"]] = sorted(reasons)
        else:
            eligible_luna.append(package)

    running_luna = sorted(
        package["package_id"] for package in packages if package["status"] == "RUNNING"
    )
    review = sorted(
        package["package_id"] for package in packages if package["status"] == "HANDOFF"
    )
    repair = sorted(package["package_id"] for package in packages if _repair_is_eligible(package))

    luna_envelope = None
    if not repair and len(running_luna) < normalized["writer_cap"] and eligible_luna:
        domains: dict[str, list[dict[str, Any]]] = {}
        for package in eligible_luna:
            domains.setdefault(package["domain_id"], []).append(package)
        domain_rows = []
        for domain_id, domain_packages in domains.items():
            stable_packages = sorted(domain_packages, key=lambda item: item["package_id"])
            try:
                total_net = math.fsum(item["net_substitution"] for item in stable_packages)
                total_seconds = math.fsum(item["expected_seconds"] for item in stable_packages)
            except (OverflowError, ValueError):
                raise FrontierError("Luna envelope totals must remain finite") from None
            if not math.isfinite(total_net) or not math.isfinite(total_seconds):
                raise FrontierError("Luna envelope totals must remain finite")
            domain_rows.append(
                (
                    domain_id,
                    stable_packages,
                    total_net,
                    sum(bool(item["critical_path"]) for item in stable_packages),
                    total_seconds,
                )
            )
        selected = min(domain_rows, key=lambda row: (-row[2], -row[3], row[4], row[0]))
        domain_id, domain_packages, total_net, _, total_seconds = selected
        ordered_packages = sorted(
            domain_packages,
            key=lambda item: (
                -int(item["critical_path"]),
                -item["net_substitution"],
                item["expected_seconds"],
                item["package_id"],
            ),
        )
        luna_envelope = {
            "domain_id": domain_id,
            "package_ids": [package["package_id"] for package in ordered_packages],
            "total_net_substitution": total_net,
            "total_expected_seconds": total_seconds,
        }

    tail_wait_allowed = bool(
        running_luna
        and luna_envelope is None
        and not sol_ready
        and not review
        and not repair
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "DONE"
        if all(package["status"] in TERMINAL_DEPENDENCY_STATUSES for package in packages)
        else "ACTIVE",
        "plan_fingerprint": fingerprint,
        "luna_envelope": luna_envelope,
        "sol_ready_package_ids": sorted(sol_ready),
        "review_package_ids": review,
        "repair_package_ids": repair,
        "blocked_package_reasons": {package_id: blocked[package_id] for package_id in sorted(blocked)},
        "running_luna_package_ids": running_luna,
        "tail_wait_allowed": tail_wait_allowed,
        "automatic_execution_allowed": False,
    }
    if set(result) != RESULT_FIELDS:  # Defensive guard against accidental interface drift.
        raise FrontierError("planner result schema drifted")
    return result

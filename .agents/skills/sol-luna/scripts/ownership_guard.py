#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Validate frozen ownership partitions and observed changed paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

LEGACY_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2
ROUTES = {"SOL_ONLY", "SOL_LUNA"}
ACTORS = {"SOL", "LUNA"}
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
PRIVATE_SEGMENTS = {
    ".aws", ".azure", ".gnupg", ".kube", ".ssh", "credentials",
    "credentials.json", "id-dsa", "id-ecdsa", "id-ed25519", "id-rsa", "secrets",
}


class OwnershipError(ValueError):
    """The ownership plan or observed changes violate the contract."""


def _reject_constant(value: str) -> None:
    raise OwnershipError(f"non-finite JSON constant is not allowed: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OwnershipError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_load(handle: Any) -> Any:
    try:
        return json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise OwnershipError(f"invalid JSON: {exc}") from exc


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OwnershipError(f"{field} must be a JSON object")
    return value


def require_exact_fields(
    value: Mapping[str, Any], allowed: set[str], required: set[str], field: str
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise OwnershipError(f"{field} has unsupported fields: {sorted(unknown)}")
    if missing:
        raise OwnershipError(f"{field} is missing required fields: {sorted(missing)}")


def require_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise OwnershipError(f"{field} must be a non-sensitive single-line hyphen-case identifier")
    return value


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise OwnershipError(f"{field} must be a boolean")
    return value


def normalize_path(value: Any, field: str) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or "\n" in value or "\r" in value or "\x00" in value or "\\" in value
    ):
        raise OwnershipError(f"{field} must be a non-empty single-line path")
    raw = value
    if (
        not raw or raw.startswith("~") or PurePosixPath(raw).is_absolute()
        or PureWindowsPath(value).is_absolute() or re.match(r"^[A-Za-z]:", raw)
    ):
        raise OwnershipError(f"{field} must be repository-relative")
    # PurePosixPath collapses empty, ``.`` and interior ``..`` segments, so
    # inspect the lexical form before asking it for normalized parts.
    lexical_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in lexical_parts):
        raise OwnershipError(f"{field} contains an unsafe path segment")
    parts = PurePosixPath(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise OwnershipError(f"{field} contains an unsafe path segment")
    if any(part.casefold() in PRIVATE_SEGMENTS for part in parts):
        raise OwnershipError(f"{field} contains a sensitive private path")
    return "/".join(parts)


def normalize_legacy_path(value: Any, field: str) -> str:
    """Normalize schema-1 paths using its original compatibility rules."""
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or "\n" in value or "\r" in value or "\x00" in value
    ):
        raise OwnershipError(f"{field} must be a non-empty single-line path")
    raw = value.replace("\\", "/").rstrip("/")
    if (
        not raw or raw.startswith("~") or PurePosixPath(raw).is_absolute()
        or PureWindowsPath(value).is_absolute() or re.match(r"^[A-Za-z]:", raw)
    ):
        raise OwnershipError(f"{field} must be repository-relative")
    # Preserve schema 1's historical lexical normalization: backslashes and
    # trailing separators are normalized, while traversal remains rejected.
    lexical_parts = raw.split("/")
    if any(part in {".", ".."} for part in lexical_parts):
        raise OwnershipError(f"{field} contains an unsafe path segment")
    parts = PurePosixPath(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise OwnershipError(f"{field} contains an unsafe path segment")
    if any(part.casefold() in PRIVATE_SEGMENTS for part in parts):
        raise OwnershipError(f"{field} contains a sensitive private path")
    return "/".join(parts)


def overlaps(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def path_list(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
    normalizer=normalize_path,
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a JSON array" if allow_empty else "a non-empty JSON array"
        raise OwnershipError(f"{field} must be {qualifier}")
    result = [normalizer(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise OwnershipError(f"{field} contains duplicate paths")
    for index, left in enumerate(result):
        if any(overlaps(left, right) for right in result[index + 1 :]):
            raise OwnershipError(f"{field} contains prefix-overlapping paths")
    return sorted(result)


def identifier_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise OwnershipError(f"{field} must be a non-empty JSON array")
    result = [require_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise OwnershipError(f"{field} contains duplicate identifiers")
    return sorted(result)


def contains(scope: list[str], path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in scope)


def _legacy_check_plan(source: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_fields(source, {"schema_version", "packages"}, {"schema_version", "packages"}, "plan")
    packages = source.get("packages")
    if not isinstance(packages, list) or not packages:
        raise OwnershipError("packages must be a non-empty JSON array")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(packages):
        package = require_object(raw, f"packages[{index}]")
        require_exact_fields(package, {"package_id", "write_scope"}, {"package_id", "write_scope"}, f"packages[{index}]")
        package_id = require_identifier(package.get("package_id"), f"packages[{index}].package_id")
        if package_id in seen_ids:
            raise OwnershipError(f"duplicate package_id: {package_id}")
        seen_ids.add(package_id)
        normalized.append({
            "package_id": package_id,
            "write_scope": path_list(
                package.get("write_scope"),
                f"packages[{index}].write_scope",
                normalizer=normalize_legacy_path,
            ),
        })
    normalized.sort(key=lambda item: item["package_id"])
    conflicts: list[dict[str, str]] = []
    for left_index, left in enumerate(normalized):
        for right in normalized[left_index + 1 :]:
            for left_path in left["write_scope"]:
                for right_path in right["write_scope"]:
                    if overlaps(left_path, right_path):
                        conflicts.append({
                            "left_package": left["package_id"], "left_path": left_path,
                            "right_package": right["package_id"], "right_path": right_path,
                        })
    return {
        "status": "PASS" if not conflicts else "FAIL",
        "schema_version": LEGACY_SCHEMA_VERSION,
        "packages": normalized,
        "conflicts": conflicts,
        "violations": [],
        "parallel_writes_allowed": not conflicts,
    }


def _normalize_v2(source: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    allowed_top = {
        "schema_version", "route", "frozen", "executors", "work_units",
        "acceptances", "partitions", "partition_digest",
    }
    require_exact_fields(source, allowed_top, allowed_top - {"partition_digest"}, "plan")
    if type(source.get("schema_version")) is not int or source["schema_version"] != SCHEMA_VERSION:
        raise OwnershipError("schema_version must be integer 2")
    route = source.get("route")
    if not isinstance(route, str) or route not in ROUTES:
        raise OwnershipError(f"route must be one of {sorted(ROUTES)}")
    if not require_bool(source.get("frozen"), "frozen"):
        raise OwnershipError("frozen must be true for a production ownership plan")

    raw_executors = source.get("executors")
    if not isinstance(raw_executors, list) or not raw_executors:
        raise OwnershipError("executors must be a non-empty JSON array")
    executors: list[dict[str, str]] = []
    actors_by_executor: dict[str, str] = {}
    for index, raw in enumerate(raw_executors):
        item = require_object(raw, f"executors[{index}]")
        require_exact_fields(item, {"executor_id", "actor"}, {"executor_id", "actor"}, f"executors[{index}]")
        executor_id = require_identifier(item.get("executor_id"), f"executors[{index}].executor_id")
        actor = item.get("actor")
        if not isinstance(actor, str) or actor not in ACTORS:
            raise OwnershipError(f"executors[{index}].actor must be SOL or LUNA")
        if executor_id in actors_by_executor:
            raise OwnershipError(f"duplicate executor_id: {executor_id}")
        actors_by_executor[executor_id] = actor
        executors.append({"executor_id": executor_id, "actor": actor})
    actor_set = set(actors_by_executor.values())
    if route == "SOL_ONLY" and "LUNA" in actor_set:
        raise OwnershipError("SOL_ONLY plan cannot register a LUNA executor")
    if route == "SOL_LUNA" and actor_set != ACTORS:
        raise OwnershipError("SOL_LUNA plan must register at least one SOL and one LUNA executor")

    raw_units = source.get("work_units")
    if not isinstance(raw_units, list) or not raw_units:
        raise OwnershipError("work_units must be a non-empty JSON array")
    units: list[dict[str, Any]] = []
    units_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_units):
        item = require_object(raw, f"work_units[{index}]")
        require_exact_fields(item, {"unit_id", "executor_id", "paths"}, {"unit_id", "executor_id", "paths"}, f"work_units[{index}]")
        unit_id = require_identifier(item.get("unit_id"), f"work_units[{index}].unit_id")
        executor_id = require_identifier(item.get("executor_id"), f"work_units[{index}].executor_id")
        if executor_id not in actors_by_executor:
            raise OwnershipError(f"work_units[{index}] references unknown executor_id: {executor_id}")
        if unit_id in units_by_id:
            raise OwnershipError(f"duplicate unit_id: {unit_id}")
        normalized = {
            "unit_id": unit_id, "executor_id": executor_id,
            "paths": path_list(item.get("paths"), f"work_units[{index}].paths"),
        }
        units_by_id[unit_id] = normalized
        units.append(normalized)

    raw_acceptances = source.get("acceptances")
    if not isinstance(raw_acceptances, list) or not raw_acceptances:
        raise OwnershipError("acceptances must be a non-empty JSON array")
    acceptances: list[dict[str, Any]] = []
    acceptances_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_acceptances):
        item = require_object(raw, f"acceptances[{index}]")
        fields = {"acceptance_id", "unit_id", "executor_id", "paths"}
        require_exact_fields(item, fields, fields, f"acceptances[{index}]")
        acceptance_id = require_identifier(item.get("acceptance_id"), f"acceptances[{index}].acceptance_id")
        unit_id = require_identifier(item.get("unit_id"), f"acceptances[{index}].unit_id")
        executor_id = require_identifier(item.get("executor_id"), f"acceptances[{index}].executor_id")
        if acceptance_id in acceptances_by_id:
            raise OwnershipError(f"duplicate acceptance_id: {acceptance_id}")
        if unit_id not in units_by_id:
            raise OwnershipError(f"acceptances[{index}] references unknown unit_id: {unit_id}")
        if executor_id not in actors_by_executor:
            raise OwnershipError(f"acceptances[{index}] references unknown executor_id: {executor_id}")
        if executor_id != units_by_id[unit_id]["executor_id"]:
            raise OwnershipError(f"acceptances[{index}].executor_id must match its work unit executor")
        normalized = {
            "acceptance_id": acceptance_id, "unit_id": unit_id, "executor_id": executor_id,
            "paths": path_list(item.get("paths"), f"acceptances[{index}].paths"),
        }
        acceptances_by_id[acceptance_id] = normalized
        acceptances.append(normalized)

    owned_objects = [
        ("work_unit", item["unit_id"], item["executor_id"], item["unit_id"], path)
        for item in units for path in item["paths"]
    ] + [
        (
            "acceptance", item["acceptance_id"], item["executor_id"], item["unit_id"], path
        )
        for item in acceptances for path in item["paths"]
    ]
    conflicts: list[dict[str, str]] = []
    for left_index, (
        left_kind, left_id, left_executor, left_unit_id, left_path
    ) in enumerate(owned_objects):
        for (
            right_kind, right_id, right_executor, right_unit_id, right_path
        ) in owned_objects[left_index + 1 :]:
            # Exact path reuse is safe only inside one executor's allocation
            # and work unit (for example, a work unit and its acceptance can
            # name the same path). Directory-prefix ownership is never safe:
            # a broad path such as ``src`` would shadow every descendant path,
            # even when both entries happen to have the same executor.
            same_path = left_path == right_path
            same_package = (
                left_executor == right_executor
                and left_unit_id == right_unit_id
                and {left_kind, right_kind} == {"work_unit", "acceptance"}
            )
            if (same_path and not same_package) or (
                not same_path and overlaps(left_path, right_path)
            ):
                conflicts.append({
                    "left_kind": left_kind, "left_id": left_id, "left_path": left_path,
                    "right_kind": right_kind, "right_id": right_id, "right_path": right_path,
                })
    if conflicts:
        raise OwnershipError("schema 2 contains prefix-overlapping or duplicate ownership paths")

    raw_partitions = source.get("partitions")
    if not isinstance(raw_partitions, list) or not raw_partitions:
        raise OwnershipError("partitions must be a non-empty JSON array")
    partitions: list[dict[str, Any]] = []
    seen_partition_ids: set[str] = set()
    assigned_units: set[str] = set()
    assigned_acceptances: set[str] = set()
    for index, raw in enumerate(raw_partitions):
        item = require_object(raw, f"partitions[{index}]")
        fields = {"partition_id", "executor_id", "unit_ids", "acceptance_ids", "paths"}
        require_exact_fields(item, fields, fields, f"partitions[{index}]")
        partition_id = require_identifier(item.get("partition_id"), f"partitions[{index}].partition_id")
        executor_id = require_identifier(item.get("executor_id"), f"partitions[{index}].executor_id")
        if partition_id in seen_partition_ids:
            raise OwnershipError(f"duplicate partition_id: {partition_id}")
        seen_partition_ids.add(partition_id)
        if executor_id not in actors_by_executor:
            raise OwnershipError(f"partitions[{index}] references unknown executor_id: {executor_id}")
        unit_ids = identifier_list(item.get("unit_ids"), f"partitions[{index}].unit_ids")
        acceptance_ids = identifier_list(item.get("acceptance_ids"), f"partitions[{index}].acceptance_ids")
        paths = path_list(item.get("paths"), f"partitions[{index}].paths")
        for unit_id in unit_ids:
            if unit_id not in units_by_id:
                raise OwnershipError(f"partitions[{index}] references unknown unit_id: {unit_id}")
            if unit_id in assigned_units:
                raise OwnershipError(f"work unit appears in more than one partition: {unit_id}")
            if units_by_id[unit_id]["executor_id"] != executor_id:
                raise OwnershipError(f"partition executor does not own work unit: {unit_id}")
            assigned_units.add(unit_id)
        for acceptance_id in acceptance_ids:
            if acceptance_id not in acceptances_by_id:
                raise OwnershipError(f"partitions[{index}] references unknown acceptance_id: {acceptance_id}")
            if acceptance_id in assigned_acceptances:
                raise OwnershipError(f"acceptance appears in more than one partition: {acceptance_id}")
            if acceptances_by_id[acceptance_id]["executor_id"] != executor_id:
                raise OwnershipError(f"partition executor does not own acceptance: {acceptance_id}")
            if acceptances_by_id[acceptance_id]["unit_id"] not in unit_ids:
                raise OwnershipError(
                    f"partition acceptance does not belong to one of its work units: {acceptance_id}"
                )
            assigned_acceptances.add(acceptance_id)
        expected_paths = sorted(
            {path for unit_id in unit_ids for path in units_by_id[unit_id]["paths"]}
            | {path for acceptance_id in acceptance_ids for path in acceptances_by_id[acceptance_id]["paths"]}
        )
        if paths != expected_paths:
            raise OwnershipError(f"partitions[{index}].paths must exactly cover its units and acceptances")
        partitions.append({
            "partition_id": partition_id, "executor_id": executor_id,
            "unit_ids": unit_ids, "acceptance_ids": acceptance_ids, "paths": paths,
        })
    missing_units = set(units_by_id) - assigned_units
    missing_acceptances = set(acceptances_by_id) - assigned_acceptances
    if missing_units:
        raise OwnershipError(f"work units missing from partitions: {sorted(missing_units)}")
    if missing_acceptances:
        raise OwnershipError(f"acceptances missing from partitions: {sorted(missing_acceptances)}")
    if "partition_digest" in source:
        declared = source["partition_digest"]
        if not isinstance(declared, str) or not DIGEST.fullmatch(declared):
            raise OwnershipError("partition_digest must be sha256 followed by 64 lowercase hex characters")

    executors.sort(key=lambda item: item["executor_id"])
    units.sort(key=lambda item: item["unit_id"])
    acceptances.sort(key=lambda item: item["acceptance_id"])
    partitions.sort(key=lambda item: item["partition_id"])
    return {
        "schema_version": SCHEMA_VERSION, "route": route, "frozen": True,
        "executors": executors, "work_units": units,
        "acceptances": acceptances, "partitions": partitions,
    }, conflicts


def partition_digest(plan: Mapping[str, Any]) -> str:
    source = require_object(plan, "plan")
    source_without_digest = deepcopy(dict(source))
    source_without_digest.pop("partition_digest", None)
    normalized, _ = _normalize_v2(source_without_digest)
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def check_plan(source: Mapping[str, Any]) -> dict[str, Any]:
    source = require_object(source, "plan")
    version = source.get("schema_version")
    if type(version) is not int:
        raise OwnershipError("schema_version must be an integer")
    if version == LEGACY_SCHEMA_VERSION:
        return _legacy_check_plan(source)
    if version != SCHEMA_VERSION:
        raise OwnershipError("unsupported ownership plan schema_version")
    normalized, conflicts = _normalize_v2(source)
    digest = partition_digest(normalized)
    violations: list[dict[str, str]] = []
    if "partition_digest" in source and source["partition_digest"] != digest:
        violations.append({
            "kind": "partition_digest_mismatch", "declared": str(source["partition_digest"]),
            "computed": digest,
        })
    passed = not conflicts and not violations
    return {
        "status": "PASS" if passed else "FAIL", "plan": normalized,
        "conflicts": conflicts, "violations": violations,
        "parallel_writes_allowed": passed, "partition_digest": digest,
    }


def _check_changes_v2(source: Mapping[str, Any], plan_source: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version", "partition_digest", "partition_id", "changed_paths",
        "handoff_frozen", "repair_authorized",
    }
    require_exact_fields(source, allowed, allowed, "changes")
    if type(source.get("schema_version")) is not int or source["schema_version"] != SCHEMA_VERSION:
        raise OwnershipError("unsupported changes schema_version")
    declared_digest = source.get("partition_digest")
    if not isinstance(declared_digest, str) or not DIGEST.fullmatch(declared_digest):
        raise OwnershipError("partition_digest must be sha256 followed by 64 lowercase hex characters")
    partition_id = require_identifier(source.get("partition_id"), "partition_id")
    changed = path_list(source.get("changed_paths"), "changed_paths", allow_empty=True)
    frozen = require_bool(source.get("handoff_frozen"), "handoff_frozen")
    repair = require_bool(source.get("repair_authorized"), "repair_authorized")

    plan_result = check_plan(plan_source)
    if (
        plan_result.get("plan", {}).get("schema_version") != SCHEMA_VERSION
        or plan_result.get("status") != "PASS"
        or plan_result.get("plan", {}).get("frozen") is not True
    ):
        raise OwnershipError("schema 2 changes require a frozen, passing schema 2 plan")
    authoritative_digest = plan_result["partition_digest"]
    normalized_plan = plan_result["plan"]
    partitions = {item["partition_id"]: item for item in normalized_plan["partitions"]}
    partition = partitions.get(partition_id)
    digest_mismatch = declared_digest != authoritative_digest
    violations: list[str] = []
    if digest_mismatch:
        violations.append("partition_digest_mismatch")
    if partition is None:
        violations.append("unknown_partition")
    if partition is None:
        scope_violations = changed
    else:
        scope_violations = [path for path in changed if not contains(partition["paths"], path)]
    if scope_violations:
        violations.append("scope_violation")
    if frozen and changed and not repair:
        scope_violations.extend(path for path in changed if path not in scope_violations)
        violations.append("handoff_frozen_without_repair")
    scope_violations = sorted(set(scope_violations))
    violations = sorted(set(violations))
    passed = partition is not None and not digest_mismatch and not scope_violations
    return {
        "schema_version": SCHEMA_VERSION,
        "partition_id": partition_id,
        "partition_digest": authoritative_digest,
        "status": "PASS" if passed else "FAIL",
        "changed_paths": changed,
        "scope_violations": scope_violations,
        "violations": violations,
        "handoff_frozen": frozen,
        "repair_authorized": repair,
        "acceptance_allowed": passed,
    }


def check_changes(
    source: Mapping[str, Any], plan: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    source = require_object(source, "changes")
    version = source.get("schema_version")
    if type(version) is not int:
        raise OwnershipError("schema_version must be an integer")
    if version == SCHEMA_VERSION:
        if plan is None:
            raise OwnershipError("schema 2 changes require --plan")
        return _check_changes_v2(source, require_object(plan, "plan"))
    if version != LEGACY_SCHEMA_VERSION:
        raise OwnershipError("unsupported changes schema_version")
    if plan is not None:
        raise OwnershipError("schema 1 changes cannot be used with a schema 2 plan")
    allowed = {
        "schema_version", "package_id", "owned_paths", "changed_paths",
        "handoff_frozen", "repair_authorized",
    }
    require_exact_fields(source, allowed, {"schema_version", "package_id", "owned_paths"}, "changes")
    if type(source.get("schema_version")) is not int or source["schema_version"] != LEGACY_SCHEMA_VERSION:
        raise OwnershipError("unsupported changes schema_version")
    package_id = require_identifier(source.get("package_id"), "package_id")
    owned = path_list(
        source.get("owned_paths"), "owned_paths", normalizer=normalize_legacy_path
    )
    changed = path_list(
        source.get("changed_paths", []),
        "changed_paths",
        allow_empty=True,
        normalizer=normalize_legacy_path,
    )
    frozen = require_bool(source.get("handoff_frozen", False), "handoff_frozen")
    repair = require_bool(source.get("repair_authorized", False), "repair_authorized")
    violations = [path for path in changed if not contains(owned, path)]
    if frozen and changed and not repair:
        violations.extend(path for path in changed if path not in violations)
    return {
        "package_id": package_id, "status": "PASS" if not violations else "FAIL",
        "changed_paths": changed, "scope_violations": sorted(violations),
        "handoff_frozen": frozen, "repair_authorized": repair,
        "acceptance_allowed": not violations,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Validate Sol-Luna ownership boundaries.")
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("check-plan", "check-changes"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True)
        if name == "check-changes":
            command.add_argument("--plan")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        with open(args.input, encoding="utf-8") as handle:
            source = strict_json_load(handle)
        if args.command == "check-plan":
            output = check_plan(source)
        else:
            plan = None
            if args.plan is not None:
                with open(args.plan, encoding="utf-8") as handle:
                    plan = strict_json_load(handle)
            output = check_changes(source, plan)
    except (OSError, UnicodeError, OwnershipError) as exc:
        print(f"ownership guard error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0 if output["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())

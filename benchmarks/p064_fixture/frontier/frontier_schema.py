from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
import re
import sys
import unicodedata
from collections.abc import Mapping
from typing import Any

if __package__ in {None, ""}:
    _directory = os.path.dirname(__file__)
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
TOP_FIELDS = {"schema_version", "controller_id", "writer_cap", "packages", "plan_fingerprint"}
TOP_REQUIRED_FIELDS = TOP_FIELDS - {"plan_fingerprint"}
PACKAGE_FIELDS = {"package_id", "executor", "domain_id", "dependencies", "path_scopes", "acceptance_ids", "baseline_sol_weight", "predicted_executor_weight", "incremental_sol_weight", "expected_seconds", "critical_path", "status", "repair"}
REPAIR_FIELDS = {"attempts_used", "attempts_max", "remaining_cost_weight", "next_cost_weight", "marginal_net_substitution", "new_evidence"}
EXECUTORS = {"SOL", "LUNA"}
STATUSES = {"PENDING", "RUNNING", "HANDOFF", "ACCEPTED", "FAILED", "RECLAIMED"}
TERMINAL_DEPENDENCY_STATUSES = {"ACCEPTED", "RECLAIMED"}
WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
RESULT_FIELDS = {"schema_version", "status", "plan_fingerprint", "luna_envelope", "sol_ready_package_ids", "review_package_ids", "repair_package_ids", "blocked_package_reasons", "running_luna_package_ids", "tail_wait_allowed", "automatic_execution_allowed"}

class FrontierError(ValueError):
    pass

def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FrontierError(f"{field} must be a JSON object")
    return value

def _fields(value: Mapping[str, Any], allowed: set[str], required: set[str], field: str) -> None:
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
    if value < minimum or (maximum is not None and value > maximum):
        raise FrontierError(f"{field} is out of bounds")
    return value

def _finite(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrontierError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        raise FrontierError(f"{field} must be a finite number") from None
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise FrontierError(f"{field} must be non-negative")
    return number

def _identifier_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise FrontierError(f"{field} must be a JSON array")
    result = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise FrontierError(f"{field} contains duplicates")
    return sorted(result)

def _path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or re.match(r"[A-Za-z]:", value):
        raise FrontierError(f"{field} must be a normalized relative POSIX path")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise FrontierError(f"{field} contains a control character")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or posixpath.normpath(value) != value:
        raise FrontierError(f"{field} must be a normalized relative POSIX path")
    for part in parts:
        if part.rstrip(" .").split(".", 1)[0].rstrip(" ").upper() in WINDOWS_DEVICE_NAMES:
            raise FrontierError(f"{field} contains a Windows device name")
    return value

def _path_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise FrontierError(f"{field} must be a JSON array")
    result = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise FrontierError(f"{field} contains duplicate paths")
    return sorted(result)

def _repair(value: Any, field: str) -> dict[str, Any]:
    source = _object(value, field)
    _fields(source, REPAIR_FIELDS, REPAIR_FIELDS, field)
    used = _integer(source["attempts_used"], f"{field}.attempts_used", minimum=0)
    maximum = _integer(source["attempts_max"], f"{field}.attempts_max", minimum=0)
    if used > maximum:
        raise FrontierError(f"{field}.attempts_used must not exceed attempts_max")
    if type(source["new_evidence"]) is not bool:
        raise FrontierError(f"{field}.new_evidence must be a boolean")
    return {"attempts_used": used, "attempts_max": maximum, "remaining_cost_weight": _finite(source["remaining_cost_weight"], f"{field}.remaining_cost_weight"), "next_cost_weight": _finite(source["next_cost_weight"], f"{field}.next_cost_weight"), "marginal_net_substitution": _finite(source["marginal_net_substitution"], f"{field}.marginal_net_substitution"), "new_evidence": source["new_evidence"]}

def _package(value: Any, index: int) -> dict[str, Any]:
    field = f"packages[{index}]"
    source = _object(value, field)
    _fields(source, PACKAGE_FIELDS | {"net_substitution"}, PACKAGE_FIELDS, field)
    executor = source["executor"]
    if not isinstance(executor, str) or executor not in EXECUTORS:
        raise FrontierError(f"{field}.executor is invalid")
    status = source["status"]
    if not isinstance(status, str) or status not in STATUSES:
        raise FrontierError(f"{field}.status is invalid")
    if type(source["critical_path"]) is not bool:
        raise FrontierError(f"{field}.critical_path must be a boolean")
    if status == "FAILED":
        if source["repair"] is None:
            raise FrontierError(f"{field}.repair is required")
        repair = _repair(source["repair"], f"{field}.repair")
    else:
        if source["repair"] is not None:
            raise FrontierError(f"{field}.repair must be null")
        repair = None
    normalized = {"package_id": _identifier(source["package_id"], f"{field}.package_id"), "executor": executor, "domain_id": _identifier(source["domain_id"], f"{field}.domain_id"), "dependencies": _identifier_list(source["dependencies"], f"{field}.dependencies"), "path_scopes": _path_list(source["path_scopes"], f"{field}.path_scopes"), "acceptance_ids": _identifier_list(source["acceptance_ids"], f"{field}.acceptance_ids"), "baseline_sol_weight": _finite(source["baseline_sol_weight"], f"{field}.baseline_sol_weight", positive=True), "predicted_executor_weight": _finite(source["predicted_executor_weight"], f"{field}.predicted_executor_weight"), "incremental_sol_weight": _finite(source["incremental_sol_weight"], f"{field}.incremental_sol_weight"), "expected_seconds": _finite(source["expected_seconds"], f"{field}.expected_seconds", positive=True), "critical_path": source["critical_path"], "status": status, "repair": repair}
    net = normalized["baseline_sol_weight"] - normalized["predicted_executor_weight"] - normalized["incremental_sol_weight"]
    if not math.isfinite(net):
        raise FrontierError(f"{field} net substitution must remain finite")
    if "net_substitution" in source and source["net_substitution"] != net:
        raise FrontierError(f"{field}.net_substitution is incorrect")
    normalized["net_substitution"] = net
    return normalized

def _canonical_package(package: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in package.items() if key != "net_substitution"}

def _fingerprint(source: Mapping[str, Any]) -> str:
    canonical = {"schema_version": source["schema_version"], "controller_id": source["controller_id"], "writer_cap": source["writer_cap"], "packages": [_canonical_package(package) for package in source["packages"]]}
    try:
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise FrontierError("canonical plan must be finite JSON") from None
    return "sha256:" + hashlib.sha256(encoded).hexdigest()

def _validate(source: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    source = _object(source, "input")
    _fields(source, TOP_FIELDS, TOP_REQUIRED_FIELDS, "input")
    if type(source["schema_version"]) is not int or source["schema_version"] != SCHEMA_VERSION:
        raise FrontierError("schema_version must be integer 1")
    writer_cap = _integer(source["writer_cap"], "writer_cap", minimum=1, maximum=8)
    if not isinstance(source["packages"], list) or not source["packages"]:
        raise FrontierError("packages must be a non-empty JSON array")
    packages = sorted((_package(value, index) for index, value in enumerate(source["packages"])), key=lambda item: item["package_id"])
    ids = [package["package_id"] for package in packages]
    if len(ids) != len(set(ids)):
        raise FrontierError("package_id values must be globally unique")
    acceptance_ids = [item for package in packages for item in package["acceptance_ids"]]
    if len(acceptance_ids) != len(set(acceptance_ids)):
        raise FrontierError("acceptance_ids must be globally unique")
    known = set(ids)
    by_id = {package["package_id"]: package for package in packages}
    for package in packages:
        for dependency in package["dependencies"]:
            if dependency == package["package_id"]:
                raise FrontierError(f"package {package['package_id']} cannot depend on itself")
            if dependency not in known:
                raise FrontierError(f"package {package['package_id']} has unknown dependency: {dependency}")
    remaining = {package["package_id"]: set(package["dependencies"]) for package in packages}
    dependents = {package_id: [] for package_id in ids}
    for package_id, dependencies in remaining.items():
        for dependency in dependencies:
            dependents[dependency].append(package_id)
    ready = sorted(package_id for package_id, dependencies in remaining.items() if not dependencies)
    visited = 0
    while ready:
        package_id = ready.pop(0)
        visited += 1
        for dependent in dependents[package_id]:
            remaining[dependent].discard(package_id)
            if not remaining[dependent]:
                ready.append(dependent)
        ready.sort()
    if visited != len(packages):
        raise FrontierError("package dependencies must form a directed acyclic graph")
    scoped_paths: list[tuple[str, str]] = []
    for package in packages:
        for path in package["path_scopes"]:
            folded = path.casefold()
            for other_id, other_path in scoped_paths:
                if other_id != package["package_id"] and (folded == other_path or folded.startswith(other_path + "/") or other_path.startswith(folded + "/")):
                    raise FrontierError(f"path scopes overlap across packages: {other_id} and {package['package_id']}")
            scoped_paths.append((package["package_id"], folded))
    running_count = 0
    for package in packages:
        if package["status"] == "RUNNING":
            running_count += 1
            if package["executor"] != "LUNA":
                raise FrontierError("a RUNNING package must use executor LUNA")
        if package["status"] != "PENDING":
            unresolved = [dependency for dependency in package["dependencies"] if by_id[dependency]["status"] not in TERMINAL_DEPENDENCY_STATUSES]
            if unresolved:
                raise FrontierError(f"non-PENDING package {package['package_id']} has non-terminal dependencies")
    if running_count > writer_cap:
        raise FrontierError("RUNNING package count exceeds writer_cap")
    normalized = {"schema_version": 1, "controller_id": _identifier(source["controller_id"], "controller_id"), "writer_cap": writer_cap, "packages": packages}
    fingerprint = _fingerprint(normalized)
    if "plan_fingerprint" in source:
        supplied = source["plan_fingerprint"]
        if not isinstance(supplied, str) or not FINGERPRINT.fullmatch(supplied) or supplied != fingerprint:
            raise FrontierError("plan_fingerprint does not match the normalized plan")
    return normalized, fingerprint

def normalize_plan(source: Mapping[str, Any]) -> dict[str, Any]:
    normalized, fingerprint = _validate(source)
    return json.loads(json.dumps({"schema_version": 1, "controller_id": normalized["controller_id"], "writer_cap": normalized["writer_cap"], "packages": normalized["packages"], "plan_fingerprint": fingerprint}, ensure_ascii=False, allow_nan=False))

def canonical_plan(source: Mapping[str, Any]) -> dict[str, Any]:
    normalized, fingerprint = _validate(source)
    return json.loads(json.dumps({"schema_version": 1, "controller_id": normalized["controller_id"], "writer_cap": normalized["writer_cap"], "packages": [_canonical_package(package) for package in normalized["packages"]], "plan_fingerprint": fingerprint}, ensure_ascii=False, allow_nan=False))

def plan_fingerprint(source: Mapping[str, Any]) -> str:
    return _validate(source)[1]

__all__ = ["SCHEMA_VERSION", "IDENTIFIER", "FINGERPRINT", "TOP_FIELDS", "TOP_REQUIRED_FIELDS", "PACKAGE_FIELDS", "REPAIR_FIELDS", "EXECUTORS", "STATUSES", "TERMINAL_DEPENDENCY_STATUSES", "RESULT_FIELDS", "FrontierError", "normalize_plan", "canonical_plan", "plan_fingerprint"]

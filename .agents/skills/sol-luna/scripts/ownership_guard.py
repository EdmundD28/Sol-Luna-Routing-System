#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Validate non-overlapping package ownership and observed changed paths."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping


SCHEMA_VERSION = 1
PACKAGE_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")


class OwnershipError(ValueError):
    """The ownership plan or observed changes violate the contract."""


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OwnershipError(f"{field} must be a JSON object")
    return value


def require_package_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not PACKAGE_ID.fullmatch(value):
        raise OwnershipError(f"{field} must be a non-sensitive hyphen-case identifier")
    return value


def normalize_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise OwnershipError(f"{field} must be a non-empty single-line path")
    raw = value.strip().replace("\\", "/").rstrip("/")
    if not raw or PurePosixPath(raw).is_absolute() or PureWindowsPath(value).is_absolute():
        raise OwnershipError(f"{field} must be repository-relative")
    parts = PurePosixPath(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise OwnershipError(f"{field} contains an unsafe path segment")
    return "/".join(parts)


def path_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise OwnershipError(f"{field} must be {'a' if allow_empty else 'a non-empty'} JSON array")
    normalized = [normalize_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(normalized) != len(set(normalized)):
        raise OwnershipError(f"{field} contains duplicate paths")
    return normalized


def overlaps(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def contains(scope: list[str], path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in scope)


def check_plan(source: Mapping[str, Any]) -> dict[str, Any]:
    source = require_object(source, "plan")
    if source.get("schema_version") != SCHEMA_VERSION:
        raise OwnershipError("unsupported ownership plan schema_version")
    packages = source.get("packages")
    if not isinstance(packages, list) or not packages:
        raise OwnershipError("packages must be a non-empty JSON array")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(packages):
        package = require_object(raw, f"packages[{index}]")
        unsupported = set(package) - {"package_id", "write_scope"}
        if unsupported:
            raise OwnershipError(f"packages[{index}] has unsupported fields: {sorted(unsupported)}")
        package_id = require_package_id(package.get("package_id"), f"packages[{index}].package_id")
        if package_id in seen_ids:
            raise OwnershipError(f"duplicate package_id: {package_id}")
        seen_ids.add(package_id)
        normalized.append(
            {
                "package_id": package_id,
                "write_scope": path_list(package.get("write_scope"), f"packages[{index}].write_scope"),
            }
        )
    conflicts: list[dict[str, str]] = []
    for left_index, left in enumerate(normalized):
        for right in normalized[left_index + 1 :]:
            for left_path in left["write_scope"]:
                for right_path in right["write_scope"]:
                    if overlaps(left_path, right_path):
                        conflicts.append(
                            {
                                "left_package": left["package_id"],
                                "left_path": left_path,
                                "right_package": right["package_id"],
                                "right_path": right_path,
                            }
                        )
    return {
        "status": "PASS" if not conflicts else "FAIL",
        "packages": normalized,
        "conflicts": conflicts,
        "parallel_writes_allowed": not conflicts,
    }


def check_changes(source: Mapping[str, Any]) -> dict[str, Any]:
    source = require_object(source, "changes")
    if source.get("schema_version") != SCHEMA_VERSION:
        raise OwnershipError("unsupported changes schema_version")
    package_id = require_package_id(source.get("package_id"), "package_id")
    owned = path_list(source.get("owned_paths"), "owned_paths")
    changed = path_list(source.get("changed_paths", []), "changed_paths", allow_empty=True)
    frozen = bool(source.get("handoff_frozen", False))
    repair = bool(source.get("repair_authorized", False))
    violations = [path for path in changed if not contains(owned, path)]
    if frozen and changed and not repair:
        violations.extend(path for path in changed if path not in violations)
    return {
        "package_id": package_id,
        "status": "PASS" if not violations else "FAIL",
        "changed_paths": changed,
        "scope_violations": sorted(violations),
        "handoff_frozen": frozen,
        "repair_authorized": repair,
        "acceptance_allowed": not violations,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Validate Sol-Luna ownership boundaries.")
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("check-plan", "check-changes"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        with open(args.input, encoding="utf-8") as handle:
            source = json.load(handle)
        output = check_plan(source) if args.command == "check-plan" else check_changes(source)
    except (OSError, json.JSONDecodeError, OwnershipError) as exc:
        print(f"ownership guard error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if output["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())

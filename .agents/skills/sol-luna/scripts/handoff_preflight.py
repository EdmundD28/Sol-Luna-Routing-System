#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Pure validation and evidence projection for one frozen worker handoff.

This module deliberately has no command, filesystem, or network side effects.
It validates a candidate-bound handoff record and derives the blockers Sol must
inspect before beginning review.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REVIEW_RISKS = {"low", "medium", "high", "critical"}
STATUSES = {"PASSED", "FAILED"}
RISK_STATUSES = {"OPEN", "MITIGATED"}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10)
}

TOP_LEVEL_FIELDS = {
    "schema_version",
    "package_id",
    "executor_id",
    "candidate_digest",
    "review_risk",
    "repair_rounds",
    "allowed_path_scopes",
    "required_acceptance_ids",
    "required_probe_categories",
    "changed_paths",
    "acceptance_results",
    "probe_results",
    "risks",
    "manifest_fingerprint",
}
REQUIRED_TOP_LEVEL_FIELDS = TOP_LEVEL_FIELDS - {"manifest_fingerprint"}
ACCEPTANCE_FIELDS = {
    "acceptance_id",
    "status",
    "command_digest",
    "result_digest",
    "candidate_digest",
}
PROBE_FIELDS = {
    "probe_id",
    "category",
    "status",
    "evidence_digest",
    "candidate_digest",
}
RISK_FIELDS = {
    "risk_id",
    "severity",
    "status",
    "evidence_digest",
    "candidate_digest",
}


class PreflightError(ValueError):
    """The preflight input is malformed or violates schema 1."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreflightError(f"{field} must be a JSON object")
    return value


def _fields(
    value: Mapping[str, Any],
    allowed: set[str],
    required: set[str],
    field: str,
) -> None:
    keys = set(value)
    if any(not isinstance(key, str) for key in keys):
        raise PreflightError(f"{field} keys must be strings")
    unknown = keys - allowed
    missing = required - keys
    if unknown:
        raise PreflightError(f"{field} has unsupported fields: {sorted(unknown)}")
    if missing:
        raise PreflightError(f"{field} is missing required fields: {sorted(missing)}")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise PreflightError(f"{field} must be a lowercase ASCII identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise PreflightError(f"{field} must be a lowercase sha256 digest")
    return value


def _enum(value: Any, choices: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise PreflightError(f"{field} has an unsupported value")
    return value


def _path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PreflightError(f"{field} must be a normalized relative POSIX path")
    if "\\" in value or PurePosixPath(value).is_absolute():
        raise PreflightError(f"{field} must be a relative POSIX path")
    windows = PureWindowsPath(value)
    if windows.drive or windows.root:
        raise PreflightError(f"{field} must not be an absolute or drive path")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise PreflightError(f"{field} contains a control character")

    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PreflightError(f"{field} contains an unsafe path segment")
    for part in parts:
        device_base = re.split(r"[.:]", part.rstrip(" ."), maxsplit=1)[0].rstrip(" .").casefold()
        if device_base in WINDOWS_RESERVED:
            raise PreflightError(f"{field} contains a reserved Windows device name")
    normalized = "/".join(PurePosixPath(value).parts)
    if normalized != value:
        raise PreflightError(f"{field} must use normalized POSIX spelling")
    return normalized


def _paths(value: Any, field: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        adjective = "non-empty " if not allow_empty else ""
        raise PreflightError(f"{field} must be a {adjective}array")
    result = [_path(item, f"{field}[{index}]") for index, item in enumerate(value)]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise PreflightError(f"{field} contains duplicate paths")
    return sorted(result)


def _identifiers(value: Any, field: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        adjective = "non-empty " if not allow_empty else ""
        raise PreflightError(f"{field} must be a {adjective}array")
    result = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise PreflightError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _contains(scope: str, path: str) -> bool:
    left = scope.casefold()
    right = path.casefold()
    return right == left or right.startswith(left + "/")


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


def _acceptance(
    raw: Any,
    index: int,
    required_ids: set[str],
) -> dict[str, Any]:
    item = _object(raw, f"acceptance_results[{index}]")
    _fields(item, ACCEPTANCE_FIELDS, ACCEPTANCE_FIELDS, f"acceptance_results[{index}]")
    acceptance_id = _identifier(item["acceptance_id"], f"acceptance_results[{index}].acceptance_id")
    if acceptance_id not in required_ids:
        raise PreflightError(f"acceptance_results[{index}].acceptance_id is not required")
    status = _enum(item["status"], STATUSES, f"acceptance_results[{index}].status")
    command_digest = _digest(item["command_digest"], f"acceptance_results[{index}].command_digest")
    result_digest = _digest(item["result_digest"], f"acceptance_results[{index}].result_digest")
    observed_candidate = _digest(
        item["candidate_digest"], f"acceptance_results[{index}].candidate_digest"
    )
    return {
        "acceptance_id": acceptance_id,
        "status": status,
        "command_digest": command_digest,
        "result_digest": result_digest,
        "candidate_digest": observed_candidate,
    }


def _probe(raw: Any, index: int, required_categories: set[str]) -> dict[str, Any]:
    item = _object(raw, f"probe_results[{index}]")
    _fields(item, PROBE_FIELDS, PROBE_FIELDS, f"probe_results[{index}]")
    probe_id = _identifier(item["probe_id"], f"probe_results[{index}].probe_id")
    category = _identifier(item["category"], f"probe_results[{index}].category")
    if category not in required_categories:
        raise PreflightError(f"probe_results[{index}].category is not required")
    status = _enum(item["status"], STATUSES, f"probe_results[{index}].status")
    evidence_digest = _digest(item["evidence_digest"], f"probe_results[{index}].evidence_digest")
    candidate_digest = _digest(item["candidate_digest"], f"probe_results[{index}].candidate_digest")
    return {
        "probe_id": probe_id,
        "category": category,
        "status": status,
        "evidence_digest": evidence_digest,
        "candidate_digest": candidate_digest,
    }


def _risk(raw: Any, index: int, candidate_digest: str) -> dict[str, Any]:
    item = _object(raw, f"risks[{index}]")
    _fields(item, RISK_FIELDS, RISK_FIELDS, f"risks[{index}]")
    risk_id = _identifier(item["risk_id"], f"risks[{index}].risk_id")
    severity = _enum(item["severity"], REVIEW_RISKS, f"risks[{index}].severity")
    status = _enum(item["status"], RISK_STATUSES, f"risks[{index}].status")
    evidence_digest = item["evidence_digest"]
    if status == "OPEN":
        if evidence_digest is not None:
            raise PreflightError(f"risks[{index}].evidence_digest must be null for an open risk")
    else:
        evidence_digest = _digest(evidence_digest, f"risks[{index}].evidence_digest")
    observed_candidate = _digest(item["candidate_digest"], f"risks[{index}].candidate_digest")
    if status == "MITIGATED" and observed_candidate != candidate_digest:
        raise PreflightError(f"risks[{index}] mitigated evidence is stale")
    return {
        "risk_id": risk_id,
        "severity": severity,
        "status": status,
        "evidence_digest": evidence_digest,
        "candidate_digest": observed_candidate,
    }


def template() -> dict[str, Any]:
    """Return a fresh, complete, READY schema-1 input template."""
    zero = "sha256:" + "0" * 64
    one = "sha256:" + "1" * 64
    two = "sha256:" + "2" * 64
    three = "sha256:" + "3" * 64
    categories = [
        "schema",
        "types",
        "boundaries",
        "capacity",
        "derived-values",
        "immutability",
        "error-channel",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": "core-package",
        "executor_id": "luna-writer",
        "candidate_digest": zero,
        "review_risk": "medium",
        "repair_rounds": 0,
        "allowed_path_scopes": ["src/core"],
        "required_acceptance_ids": ["accept-core"],
        "required_probe_categories": categories,
        "changed_paths": ["src/core/main.py"],
        "acceptance_results": [
            {
                "acceptance_id": "accept-core",
                "status": "PASSED",
                "command_digest": one,
                "result_digest": two,
                "candidate_digest": zero,
            }
        ],
        "probe_results": [
            {
                "probe_id": f"probe-{category}",
                "category": category,
                "status": "PASSED",
                "evidence_digest": three,
                "candidate_digest": zero,
            }
            for category in categories
        ],
        "risks": [],
    }


def evaluate(source: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project one candidate-bound handoff without mutation."""
    source_object = _object(source, "source")
    _fields(source_object, TOP_LEVEL_FIELDS, REQUIRED_TOP_LEVEL_FIELDS, "source")

    schema_version = source_object["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != SCHEMA_VERSION:
        raise PreflightError("schema_version must be integer 1")
    package_id = _identifier(source_object["package_id"], "package_id")
    executor_id = _identifier(source_object["executor_id"], "executor_id")
    candidate_digest = _digest(source_object["candidate_digest"], "candidate_digest")
    review_risk = _enum(source_object["review_risk"], REVIEW_RISKS, "review_risk")
    repair_rounds = source_object["repair_rounds"]
    if isinstance(repair_rounds, bool) or not isinstance(repair_rounds, int) or not 0 <= repair_rounds <= 3:
        raise PreflightError("repair_rounds must be an integer from 0 through 3")

    allowed_scopes = _paths(source_object["allowed_path_scopes"], "allowed_path_scopes", allow_empty=False)
    required_acceptance = _identifiers(
        source_object["required_acceptance_ids"], "required_acceptance_ids", allow_empty=False
    )
    required_categories = _identifiers(
        source_object["required_probe_categories"], "required_probe_categories", allow_empty=True
    )
    changed_paths = _paths(source_object["changed_paths"], "changed_paths", allow_empty=True)

    raw_acceptances = source_object["acceptance_results"]
    if not isinstance(raw_acceptances, list):
        raise PreflightError("acceptance_results must be an array")
    acceptances = [
        _acceptance(item, index, set(required_acceptance))
        for index, item in enumerate(raw_acceptances)
    ]
    acceptance_ids = [item["acceptance_id"] for item in acceptances]
    if len(acceptance_ids) != len(set(acceptance_ids)):
        raise PreflightError("acceptance_results contains duplicate acceptance IDs")
    acceptances.sort(key=lambda item: item["acceptance_id"])

    raw_probes = source_object["probe_results"]
    if not isinstance(raw_probes, list):
        raise PreflightError("probe_results must be an array")
    probes = [_probe(item, index, set(required_categories)) for index, item in enumerate(raw_probes)]
    probe_ids = [item["probe_id"] for item in probes]
    probe_categories = [item["category"] for item in probes]
    if len(probe_ids) != len(set(probe_ids)):
        raise PreflightError("probe_results contains duplicate probe IDs")
    if len(probe_categories) != len(set(probe_categories)):
        raise PreflightError("probe_results contains duplicate categories")
    probes.sort(key=lambda item: item["probe_id"])

    raw_risks = source_object["risks"]
    if not isinstance(raw_risks, list):
        raise PreflightError("risks must be an array")
    risks = [_risk(item, index, candidate_digest) for index, item in enumerate(raw_risks)]
    risk_ids = [item["risk_id"] for item in risks]
    if len(risk_ids) != len(set(risk_ids)):
        raise PreflightError("risks contains duplicate risk IDs")
    risks.sort(key=lambda item: item["risk_id"])

    canonical_input: dict[str, Any] = {
        "schema_version": schema_version,
        "package_id": package_id,
        "executor_id": executor_id,
        "candidate_digest": candidate_digest,
        "review_risk": review_risk,
        "repair_rounds": repair_rounds,
        "allowed_path_scopes": allowed_scopes,
        "required_acceptance_ids": required_acceptance,
        "required_probe_categories": required_categories,
        "changed_paths": changed_paths,
        "acceptance_results": acceptances,
        "probe_results": probes,
        "risks": risks,
    }
    manifest_fingerprint = _fingerprint(canonical_input)
    if "manifest_fingerprint" in source_object:
        supplied_fingerprint = _digest(source_object["manifest_fingerprint"], "manifest_fingerprint")
        if supplied_fingerprint != manifest_fingerprint:
            raise PreflightError("manifest_fingerprint does not match validated input")

    acceptance_id_set = set(acceptance_ids)
    probe_category_set = set(probe_categories)
    missing_acceptance_ids = sorted(
        acceptance_id for acceptance_id in required_acceptance if acceptance_id not in acceptance_id_set
    )
    failed_acceptance_ids = sorted(
        item["acceptance_id"] for item in acceptances if item["status"] == "FAILED"
    )
    missing_probe_categories = sorted(
        category for category in required_categories if category not in probe_category_set
    )
    failed_probe_ids = sorted(item["probe_id"] for item in probes if item["status"] == "FAILED")
    stale_evidence_ids = sorted(
        [f"acceptance:{item['acceptance_id']}" for item in acceptances if item["candidate_digest"] != candidate_digest]
        + [f"probe:{item['probe_id']}" for item in probes if item["candidate_digest"] != candidate_digest]
    )
    changed_path_violations = sorted(
        path for path in changed_paths if not any(_contains(scope, path) for scope in allowed_scopes)
    )
    open_risk_ids = sorted(item["risk_id"] for item in risks if item["status"] == "OPEN")

    blockers = (
        missing_acceptance_ids,
        failed_acceptance_ids,
        missing_probe_categories,
        failed_probe_ids,
        stale_evidence_ids,
        changed_path_violations,
        open_risk_ids,
    )
    status = "READY" if all(not blocker for blocker in blockers) else "HOLD"
    declared_severities = {item["severity"] for item in risks}
    if (
        status == "HOLD"
        or repair_rounds != 0
        or review_risk in {"high", "critical"}
        or declared_severities & {"high", "critical"}
    ):
        review_depth = "DEEP"
    elif review_risk == "medium" or "medium" in declared_severities:
        review_depth = "STANDARD"
    else:
        review_depth = "TARGETED"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "package_id": package_id,
        "executor_id": executor_id,
        "candidate_digest": candidate_digest,
        "manifest_fingerprint": manifest_fingerprint,
        "missing_acceptance_ids": missing_acceptance_ids,
        "failed_acceptance_ids": failed_acceptance_ids,
        "missing_probe_categories": missing_probe_categories,
        "failed_probe_ids": failed_probe_ids,
        "stale_evidence_ids": stale_evidence_ids,
        "changed_path_violations": changed_path_violations,
        "open_risk_ids": open_risk_ids,
        "review_depth": review_depth,
        "automatic_acceptance_allowed": False,
    }


__all__ = ["PreflightError", "evaluate", "template"]

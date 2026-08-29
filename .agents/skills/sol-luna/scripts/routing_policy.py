#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Evaluate predictive Sol-Luna routing, review depth, and bounded rework."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping


POLICY_SCHEMA_VERSION = 1
LEGACY_SINGLE_SCHEMA_VERSION = 1
LEGACY_PACKAGES_SCHEMA_VERSION = 2
SCHEMA_VERSION = 3
PACKAGES_SCHEMA_VERSION = 4
LEGACY_REQUEST_SCHEMAS = {LEGACY_SINGLE_SCHEMA_VERSION, LEGACY_PACKAGES_SCHEMA_VERSION}
SINGLE_REQUEST_SCHEMAS = {LEGACY_SINGLE_SCHEMA_VERSION, SCHEMA_VERSION}
PACKAGE_REQUEST_SCHEMAS = {LEGACY_PACKAGES_SCHEMA_VERSION, PACKAGES_SCHEMA_VERSION}
V5_REQUEST_SCHEMA_VERSION = 5
V6_REQUEST_SCHEMA_VERSION = 6
V7_REQUEST_SCHEMA_VERSION = 7
PACKAGE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
# The routing policy consumes the versioned feedback document emitted by the
# evidence ledger.  Keep this explicit: accepting an unknown feedback schema
# would silently turn stale or incompatible evidence into routing authority.
EVIDENCE_LEDGER_SCHEMA_VERSION = 5
EVIDENCE_FEEDBACK_SOURCE = f"evidence-ledger-feedback-v{EVIDENCE_LEDGER_SCHEMA_VERSION}"
DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "references" / "routing-policy.v1.json"


class PolicyError(ValueError):
    """The routing input or policy violates the executable contract."""


def strict_json_loads(source: str) -> Any:
    def pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PolicyError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(source, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(PolicyError(f"non-finite JSON constant: {value}")))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PolicyError(f"invalid JSON: {exc}") from exc


class _ExternallyBoundEvidence(dict[str, Any]):
    """Private marker for advisory ledger evidence without provider proof."""


class _ExternallyBoundQualityEvidence(dict[str, dict[str, Any]]):
    """Private marker for quality evidence loaded outside the route request."""


def finite_number(value: Any, field: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PolicyError(f"{field} must be a finite number")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        upper = f" and at most {maximum}" if maximum is not None else ""
        raise PolicyError(f"{field} must be at least {minimum}{upper}")
    return result


def integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PolicyError(f"{field} must be an integer of at least {minimum}")
    return value


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PolicyError(f"{field} must be a JSON object")
    return value


def reject_unknown_fields(source: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(source) - allowed
    if unknown:
        raise PolicyError(f"{field} has unknown fields: {sorted(unknown)}")


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise PolicyError(f"{field} must be a non-empty single-line string")
    return value.strip()


def require_digest(value: Any, field: str) -> str:
    digest = require_string(value, field)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PolicyError(f"{field} must be a lower-case SHA-256 digest")
    return digest


QUALITY_EVIDENCE_FIELDS = {
    "evidence_id", "task_family", "effort", "allocation_shape_fingerprint",
    "acceptance_suite_digest", "observations", "first_pass_accepted",
    "final_defect_runs", "source_kind", "evidence_digest",
}
QUALITY_EVIDENCE_SOURCES = {
    "candidate-preflight",
    "controlled-routing-campaign",
    "independent-evaluation",
    "matched-history",
}
REASONING_PROFILE_FIELDS = {
    "architecture_settled",
    "deterministic_acceptance",
    "semantic_coupling",
    "cross_module_invariants",
    "multi_interface_contract",
    "adversarial_edge_cases",
    "platform_sensitive_io",
    "strict_serialization",
}
COMPLEXITY_SIGNAL_FIELDS = (
    "cross_module_invariants",
    "multi_interface_contract",
    "adversarial_edge_cases",
    "platform_sensitive_io",
    "strict_serialization",
)


def reasoning_effort_floor(
    value: Any,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    profile = require_object(value, "reasoning_profile")
    reject_unknown_fields(profile, REASONING_PROFILE_FIELDS, "reasoning_profile")
    missing = REASONING_PROFILE_FIELDS - set(profile)
    if missing:
        raise PolicyError(f"reasoning_profile missing fields: {sorted(missing)}")
    normalized: dict[str, bool | str] = {}
    for field in REASONING_PROFILE_FIELDS - {"semantic_coupling"}:
        item = profile[field]
        if type(item) is not bool:
            raise PolicyError(f"reasoning_profile.{field} must be a boolean")
        normalized[field] = item
    semantic = require_string(
        profile["semantic_coupling"],
        "reasoning_profile.semantic_coupling",
    ).lower()
    if semantic not in {"low", "medium", "high"}:
        raise PolicyError("reasoning_profile.semantic_coupling must be low, medium, or high")
    normalized["semantic_coupling"] = semantic
    signal_reasons = [field for field in COMPLEXITY_SIGNAL_FIELDS if normalized[field]]
    signal_count = len(signal_reasons) + (1 if semantic == "high" else 0)
    reasons = list(signal_reasons)
    if semantic != "low":
        reasons.append(f"semantic_coupling_{semantic}")
    if not normalized["architecture_settled"]:
        reasons.append("architecture_unsettled")
    if not normalized["deterministic_acceptance"]:
        reasons.append("acceptance_nondeterministic")
    if not normalized["architecture_settled"] and signal_count >= 4:
        minimum = "xhigh"
    elif semantic == "high" or signal_count >= 2:
        minimum = "high"
    elif semantic == "medium" or signal_count == 1 or not normalized["architecture_settled"] or not normalized["deterministic_acceptance"]:
        minimum = "medium"
    else:
        minimum = "low"
    if minimum not in policy["effort_order"]:
        raise PolicyError("reasoning effort floor is unsupported by policy")
    return {
        "minimum_effort": minimum,
        "complexity_signal_count": signal_count,
        "reasons": sorted(reasons),
    }


def _quality_evidence_digest(source: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in source.items() if key != "evidence_digest"}
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def quality_evidence_index(
    value: Any,
    *,
    task_family: str,
    acceptance_suite_digest: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise PolicyError("quality_evidence must be a non-empty JSON array")
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value):
        prefix = f"quality_evidence[{index}]"
        item = require_object(raw, prefix)
        reject_unknown_fields(item, QUALITY_EVIDENCE_FIELDS, prefix)
        missing = QUALITY_EVIDENCE_FIELDS - set(item)
        if missing:
            raise PolicyError(f"{prefix} missing fields: {sorted(missing)}")
        evidence_id = require_string(item["evidence_id"], f"{prefix}.evidence_id")
        if not PACKAGE_ID.fullmatch(evidence_id) or evidence_id in result:
            raise PolicyError(f"{prefix}.evidence_id must be unique stable hyphen-case")
        if require_string(item["task_family"], f"{prefix}.task_family") != task_family:
            raise PolicyError(f"{prefix}.task_family does not match request")
        effort = require_string(item["effort"], f"{prefix}.effort").lower()
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise PolicyError(f"{prefix}.effort is unsupported")
        shape = require_digest(item["allocation_shape_fingerprint"], f"{prefix}.allocation_shape_fingerprint")
        suite = require_digest(item["acceptance_suite_digest"], f"{prefix}.acceptance_suite_digest")
        if suite != acceptance_suite_digest:
            raise PolicyError(f"{prefix}.acceptance_suite_digest does not match request")
        observations = integer(item["observations"], f"{prefix}.observations", minimum=1)
        accepted = integer(item["first_pass_accepted"], f"{prefix}.first_pass_accepted")
        defects = integer(item["final_defect_runs"], f"{prefix}.final_defect_runs")
        if accepted > observations or defects > observations:
            raise PolicyError(f"{prefix} counts exceed observations")
        source_kind = require_string(item["source_kind"], f"{prefix}.source_kind")
        if source_kind not in QUALITY_EVIDENCE_SOURCES:
            raise PolicyError(f"{prefix}.source_kind is unsupported")
        evidence_digest = require_digest(item["evidence_digest"], f"{prefix}.evidence_digest")
        if evidence_digest != _quality_evidence_digest(item):
            raise PolicyError(f"{prefix}.evidence_digest does not match content")
        result[evidence_id] = {
            "evidence_id": evidence_id,
            "task_family": task_family,
            "effort": effort,
            "allocation_shape_fingerprint": shape,
            "acceptance_suite_digest": suite,
            "observations": observations,
            "first_pass_probability": accepted / observations,
            "final_defect_probability": defects / observations,
            "source_kind": source_kind,
            "evidence_digest": evidence_digest,
        }
    return result


def load_quality_evidence_index(
    path: Path,
    *,
    task_family: str,
    acceptance_suite_digest: str,
) -> _ExternallyBoundQualityEvidence:
    try:
        document = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyError(f"cannot load quality evidence index: {exc}") from exc
    source = require_object(document, "quality evidence index")
    reject_unknown_fields(source, {"schema_version", "evidence"}, "quality evidence index")
    if type(source.get("schema_version")) is not int or source["schema_version"] != 1:
        raise PolicyError("unsupported quality evidence index schema_version")
    return _ExternallyBoundQualityEvidence(
        quality_evidence_index(
            source.get("evidence"),
            task_family=task_family,
            acceptance_suite_digest=acceptance_suite_digest,
        )
    )


def canonical_json(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def display_round(value: Any) -> Any:
    """Round numeric presentation values without changing routing decisions."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [display_round(item) for item in value]
    if isinstance(value, Mapping):
        return {key: display_round(item) for key, item in value.items()}
    return value


def validate_policy_mapping(source: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(source)
    require_object(policy, "policy")
    if type(policy.get("schema_version")) is not int or policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise PolicyError("unsupported routing policy schema_version")
    efforts = policy.get("effort_order")
    if efforts != ["low", "medium", "high", "xhigh", "max"]:
        raise PolicyError("effort_order must be low, medium, high, xhigh, max")
    aliases = require_object(policy.get("effort_aliases"), "effort_aliases")
    if aliases.get("light") != "low":
        raise PolicyError("the light compatibility alias must normalize to low")
    finite_number(
        policy.get("minimum_expected_credit_savings_fraction"),
        "minimum_expected_credit_savings_fraction",
        maximum=1.0,
    )
    finite_number(policy.get("minimum_first_pass_probability"), "minimum_first_pass_probability", maximum=1.0)
    finite_number(
        policy.get("minimum_expected_elapsed_savings_fraction"),
        "minimum_expected_elapsed_savings_fraction",
        maximum=1.0,
    )
    finite_number(
        policy.get("maximum_coordination_credit_share"),
        "maximum_coordination_credit_share",
        maximum=1.0,
    )
    integer(policy.get("maximum_initial_writers"), "maximum_initial_writers", minimum=1)
    integer(policy.get("maximum_active_luna_writers"), "maximum_active_luna_writers", minimum=1)
    finite_number(policy.get("maximum_duplicate_work_fraction"), "maximum_duplicate_work_fraction", maximum=1.0)
    if policy.get("repair_precedes_new_luna_dispatch") is not True:
        raise PolicyError("repair_precedes_new_luna_dispatch must be true")
    if policy.get("high_effort_critical_path_requires_lower_effort_quality_evidence") is not True:
        raise PolicyError(
            "high_effort_critical_path_requires_lower_effort_quality_evidence must be true"
        )
    integer(policy.get("parallel_review_minimum_pairs"), "parallel_review_minimum_pairs", minimum=1)
    budget = require_object(policy.get("rework_budget"), "rework_budget")
    focused_repairs = integer(budget.get("focused_repairs"), "rework_budget.focused_repairs", minimum=1)
    if focused_repairs > 3:
        raise PolicyError("the policy permits at most three focused repairs")
    if integer(budget.get("effort_escalations"), "rework_budget.effort_escalations") != 1:
        raise PolicyError("the policy permits exactly one effort escalation")
    return dict(policy)


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot load routing policy: {exc}") from exc
    return validate_policy_mapping(require_object(policy, "policy"))


def policy_fingerprint(policy: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(policy)).hexdigest()


def normalize_effort(value: Any, policy: Mapping[str, Any]) -> str:
    effort = require_string(value, "effort").lower()
    effort = str(require_object(policy["effort_aliases"], "effort_aliases").get(effort, effort))
    if effort not in policy["effort_order"]:
        raise PolicyError(f"unsupported Luna effort: {effort}")
    return effort


def estimate(source: Mapping[str, Any], prefix: str, *, allow_metadata: bool = False) -> dict[str, float]:
    allowed = {
        "first_pass_probability",
        "final_defect_probability",
        "execution_credits",
        "execution_seconds",
        "recovery_credits_if_failed",
        "recovery_seconds_if_failed",
    }
    if allow_metadata:
        allowed.update({"effort", "failure_impact", "effort_basis"})
    reject_unknown_fields(
        source,
        allowed,
        prefix,
    )
    return {
        "first_pass_probability": finite_number(
            source.get("first_pass_probability"), f"{prefix}.first_pass_probability", maximum=1.0
        ),
        "final_defect_probability": finite_number(
            source.get("final_defect_probability"), f"{prefix}.final_defect_probability", maximum=1.0
        ),
        "execution_credits": finite_number(source.get("execution_credits"), f"{prefix}.execution_credits"),
        "execution_seconds": finite_number(source.get("execution_seconds"), f"{prefix}.execution_seconds"),
    }


def coordination_totals(
    source: Mapping[str, Any], *, multiwriter: bool, require_retained_execution: bool
) -> dict[str, Any]:
    """Validate all Sol-side cost plus serial overhead and retained execution."""
    required = ("sol_planning", "sol_review", "integration")
    if multiwriter:
        required += ("queue", "merge_contention")
    allowed = set(required) | {"sol_retained_execution"}
    reject_unknown_fields(source, allowed, "coordination")
    if require_retained_execution and "sol_retained_execution" not in source:
        raise PolicyError("coordination.sol_retained_execution is required by the current routing schema")
    phases: dict[str, dict[str, float]] = {}
    present = (*required, *(("sol_retained_execution",) if "sol_retained_execution" in source else ()))
    for phase in present:
        value = require_object(source.get(phase), f"coordination.{phase}")
        reject_unknown_fields(value, {"credits", "seconds"}, f"coordination.{phase}")
        phases[phase] = {
            "credits": finite_number(value.get("credits"), f"coordination.{phase}.credits"),
            "seconds": finite_number(value.get("seconds"), f"coordination.{phase}.seconds"),
        }
    retained = phases.get("sol_retained_execution", {"credits": 0.0, "seconds": 0.0})
    overhead_phases = [phase for name, phase in phases.items() if name != "sol_retained_execution"]
    return {
        "credits": sum(item["credits"] for item in phases.values()),
        "overhead_credits": sum(item["credits"] for item in overhead_phases),
        "serial_seconds": sum(item["seconds"] for item in overhead_phases),
        "retained_execution_seconds": retained["seconds"],
        "phases": phases,
    }


def _package_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise PolicyError(f"{field} must be a non-empty repository-relative path")
    if value != value.strip():
        raise PolicyError(f"{field} must not have leading or trailing whitespace")
    raw = value.replace("\\", "/").rstrip("/")
    if not raw or ":" in raw or PurePosixPath(raw).is_absolute() or PureWindowsPath(value).is_absolute():
        raise PolicyError(f"{field} must be repository-relative")
    parts = PurePosixPath(raw).parts
    if any(
        part in {"", ".", ".."}
        or part.endswith((".", " "))
        or any(ord(character) < 32 for character in part)
        or part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES
        for part in parts
    ):
        raise PolicyError(f"{field} contains an unsafe path segment")
    return "/".join(parts).casefold()


def _paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _interval_union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _package_probability(value: Any, field: str) -> float:
    return finite_number(value, field, maximum=1.0)


def package_schedule(
    candidate: Mapping[str, Any], *, requested_writers: int, prefix: str
) -> dict[str, Any]:
    """Validate a package DAG and return conservative cost/schedule metrics."""
    requested_writers = integer(requested_writers, f"{prefix}.requested_writers", minimum=1)
    packages_source = candidate.get("packages")
    if not isinstance(packages_source, list) or not packages_source:
        raise PolicyError(f"{prefix}.packages must be a non-empty JSON array")
    packages: dict[str, dict[str, Any]] = {}
    ownership: list[tuple[str, str]] = []
    required = {
        "package_id",
        "depends_on",
        "writable_paths",
        "execution_credits",
        "execution_seconds",
        "first_pass_probability",
        "repair_probability",
        "repair_credits",
        "repair_seconds",
        "terminal_failure_probability",
        "terminal_recovery_credits",
        "terminal_recovery_seconds",
        "final_defect_probability",
    }
    for index, raw in enumerate(packages_source):
        package = require_object(raw, f"{prefix}.packages[{index}]")
        missing = required - set(package)
        if missing:
            raise PolicyError(f"{prefix}.packages[{index}] missing fields: {sorted(missing)}")
        unknown = set(package) - required
        if unknown:
            raise PolicyError(f"{prefix}.packages[{index}] has unknown fields: {sorted(unknown)}")
        package_id = require_string(package.get("package_id"), f"{prefix}.packages[{index}].package_id")
        if not PACKAGE_ID.fullmatch(package_id):
            raise PolicyError(f"{prefix}.packages[{index}].package_id must be a stable hyphen-case identifier")
        if package_id in packages:
            raise PolicyError(f"duplicate package_id: {package_id}")
        depends = package.get("depends_on")
        if not isinstance(depends, list) or any(not isinstance(item, str) or not item.strip() for item in depends):
            raise PolicyError(f"{prefix}.packages[{index}].depends_on must be a JSON array of identifiers")
        if len(depends) != len(set(depends)):
            raise PolicyError(f"{prefix}.packages[{index}].depends_on contains duplicates")
        paths = package.get("writable_paths")
        if not isinstance(paths, list) or not paths:
            raise PolicyError(f"{prefix}.packages[{index}].writable_paths must be a non-empty JSON array")
        normalized_paths = [_package_path(item, f"{prefix}.packages[{index}].writable_paths[{path_index}]") for path_index, item in enumerate(paths)]
        if len(normalized_paths) != len(set(normalized_paths)):
            raise PolicyError(f"{prefix}.packages[{index}].writable_paths contains duplicates")
        for path in normalized_paths:
            for other_id, other_path in ownership:
                if _paths_overlap(path, other_path):
                    raise PolicyError(f"writable ownership overlaps between {package_id} and {other_id}")
            ownership.append((package_id, path))
        first_pass = _package_probability(package.get("first_pass_probability"), f"{prefix}.packages[{index}].first_pass_probability")
        repair_probability = _package_probability(package.get("repair_probability"), f"{prefix}.packages[{index}].repair_probability")
        terminal_probability = _package_probability(package.get("terminal_failure_probability"), f"{prefix}.packages[{index}].terminal_failure_probability")
        if not math.isclose(first_pass + repair_probability + terminal_probability, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise PolicyError(f"{prefix}.packages[{index}] result probabilities must sum to 1")
        execution_credits = finite_number(package.get("execution_credits"), f"{prefix}.packages[{index}].execution_credits")
        execution_seconds = finite_number(package.get("execution_seconds"), f"{prefix}.packages[{index}].execution_seconds")
        repair_credits = finite_number(package.get("repair_credits"), f"{prefix}.packages[{index}].repair_credits")
        repair_seconds = finite_number(package.get("repair_seconds"), f"{prefix}.packages[{index}].repair_seconds")
        terminal_credits = finite_number(package.get("terminal_recovery_credits"), f"{prefix}.packages[{index}].terminal_recovery_credits")
        terminal_seconds = finite_number(package.get("terminal_recovery_seconds"), f"{prefix}.packages[{index}].terminal_recovery_seconds")
        final_defect = _package_probability(package.get("final_defect_probability"), f"{prefix}.packages[{index}].final_defect_probability")
        packages[package_id] = {
            "package_id": package_id,
            "depends_on": list(depends),
            "execution_credits": execution_credits,
            "execution_seconds": execution_seconds,
            "expected_credits": execution_credits + repair_probability * repair_credits + terminal_probability * terminal_credits,
            "expected_recovery_seconds": repair_probability * repair_seconds + terminal_probability * terminal_seconds,
            "expected_recovery_credits": repair_probability * repair_credits + terminal_probability * terminal_credits,
            "first_pass_probability": first_pass,
            "terminal_failure_probability": terminal_probability,
            "final_defect_probability": final_defect,
        }
    for package in packages.values():
        unknown = set(package["depends_on"]) - set(packages)
        if unknown:
            raise PolicyError(f"{prefix}.{package['package_id']} has unknown dependencies: {sorted(unknown)}")

    indegree = {package_id: len(package["depends_on"]) for package_id, package in packages.items()}
    ready = sorted(package_id for package_id, degree in indegree.items() if degree == 0)
    initial_ready_count = len(ready)
    workers = max(1, min(requested_writers, len(packages)))
    # Schedule package execution makespan; expected repair and terminal
    # recovery seconds are accumulated separately and added by the route gate.
    serial_seconds = sum(package["execution_seconds"] for package in packages.values())
    finish: dict[str, float] = {}
    active: list[tuple[float, int, str]] = []
    completed: set[str] = set()
    now = 0.0
    while len(completed) < len(packages):
        # At each event, only dependencies-complete packages may enter the
        # queue.  Stable package-id ordering makes ties deterministic.
        available = sorted(
            package_id
            for package_id, package in packages.items()
            if package_id not in completed
            and package_id not in {item[2] for item in active}
            and all(dependency in completed for dependency in package["depends_on"])
        )
        available.sort(key=lambda package_id: (-packages[package_id]["execution_seconds"], package_id))
        while available and len(active) < workers:
            package_id = available.pop(0)
            package = packages[package_id]
            end = now + package["execution_seconds"]
            active.append((end, len(active), package_id))
            active.sort(key=lambda item: (item[0], item[2]))
        if not active:
            raise PolicyError(f"{prefix}.packages contains a dependency cycle")
        next_end = active[0][0]
        now = next_end
        finished_now = [item for item in active if item[0] == next_end]
        active = [item for item in active if item[0] != next_end]
        for _, _, package_id in sorted(finished_now, key=lambda item: item[2]):
            finish[package_id] = next_end
            completed.add(package_id)
    scheduled_seconds = max(finish.values(), default=0.0)
    return {
        "package_count": len(packages),
        "effective_writers": workers,
        "initial_ready_packages": initial_ready_count,
        "serial_package_seconds": serial_seconds,
        "scheduled_package_seconds": scheduled_seconds,
        "expected_package_credits": sum(package["expected_credits"] for package in packages.values()),
        "expected_recovery_credits": sum(package["expected_recovery_credits"] for package in packages.values()),
        "expected_recovery_seconds": sum(package["expected_recovery_seconds"] for package in packages.values()),
        "first_pass_probability": max(0.0, 1.0 - sum(1.0 - package["first_pass_probability"] for package in packages.values())),
        "final_defect_probability": min(
            1.0,
            sum(
                package["final_defect_probability"] + package["terminal_failure_probability"]
                for package in packages.values()
            ),
        ),
    }


def package_schedule_v5(
    candidate: Mapping[str, Any], *, requested_writers: int, prefix: str,
    baseline_reference: Mapping[str, Any] | None = None,
    acceptance_contract_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and schedule the v5 complete Sol/Luna partition.

    v5 is deliberately separate from the v3/v4 package contract: a package is
    owned by exactly one executor, and Sol retained execution is derived from
    the SOL lane rather than supplied as coordination metadata.
    """
    requested_writers = integer(requested_writers, f"{prefix}.requested_writers", minimum=1)
    raw_packages = candidate.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise PolicyError(f"{prefix}.packages must be a non-empty JSON array")
    required = {
        "executor", "package_id", "depends_on", "writable_paths", "critical_path", "acceptance_ids",
        "baseline_sol_credits", "baseline_sol_seconds", "execution_credits",
        "execution_seconds", "first_pass_probability", "repair_probability",
        "repair_credits", "repair_seconds", "terminal_failure_probability",
        "terminal_recovery_credits", "terminal_recovery_seconds", "final_defect_probability",
    }
    packages: dict[str, dict[str, Any]] = {}
    ownership: list[tuple[str, str]] = []
    baseline: dict[str, Any] = {}
    assigned_acceptance: list[str] = []
    for index, raw in enumerate(raw_packages):
        item = require_object(raw, f"{prefix}.packages[{index}]")
        missing = required - set(item)
        if missing:
            raise PolicyError(f"{prefix}.packages[{index}] missing fields: {sorted(missing)}")
        unknown = set(item) - required
        if unknown:
            raise PolicyError(f"{prefix}.packages[{index}] has unknown fields: {sorted(unknown)}")
        package_id = require_string(item["package_id"], f"{prefix}.packages[{index}].package_id")
        if not PACKAGE_ID.fullmatch(package_id) or package_id in packages:
            raise PolicyError(f"{prefix}.packages[{index}].package_id must be unique stable hyphen-case")
        executor = require_string(item["executor"], f"{prefix}.packages[{index}].executor").upper()
        if executor not in {"SOL", "LUNA"}:
            raise PolicyError(f"{prefix}.packages[{index}].executor must be SOL or LUNA")
        depends = item["depends_on"]
        if not isinstance(depends, list) or any(not isinstance(dep, str) or not dep.strip() for dep in depends):
            raise PolicyError(f"{prefix}.packages[{index}].depends_on must be a JSON array of identifiers")
        if len(depends) != len(set(depends)):
            raise PolicyError(f"{prefix}.packages[{index}].depends_on contains duplicates")
        paths = item["writable_paths"]
        if not isinstance(paths, list) or not paths:
            raise PolicyError(f"{prefix}.packages[{index}].writable_paths must be a non-empty JSON array")
        normalized = [_package_path(path, f"{prefix}.packages[{index}].writable_paths[{n}]") for n, path in enumerate(paths)]
        if len(normalized) != len(set(normalized)):
            raise PolicyError(f"{prefix}.packages[{index}].writable_paths contains duplicates")
        for path in normalized:
            if any(_paths_overlap(path, other_path) for _, other_path in ownership):
                raise PolicyError(f"writable ownership overlaps at {prefix}.packages[{index}]")
            ownership.append((package_id, path))
        critical = item["critical_path"]
        if not isinstance(critical, bool):
            raise PolicyError(f"{prefix}.packages[{index}].critical_path must be boolean")
        acceptance_ids = item["acceptance_ids"]
        if not isinstance(acceptance_ids, list) or not acceptance_ids or any(type(value) is not str or not value.strip() for value in acceptance_ids):
            raise PolicyError(f"{prefix}.packages[{index}].acceptance_ids must be a non-empty string array")
        if len(acceptance_ids) != len(set(acceptance_ids)):
            raise PolicyError(f"{prefix}.packages[{index}].acceptance_ids contains duplicates")
        assigned_acceptance.extend(acceptance_ids)
        base_credits = finite_number(item["baseline_sol_credits"], f"{prefix}.packages[{index}].baseline_sol_credits")
        base_seconds = finite_number(item["baseline_sol_seconds"], f"{prefix}.packages[{index}].baseline_sol_seconds")
        if executor == "SOL" and critical and (base_credits <= 0 or base_seconds <= 0):
            raise PolicyError("SOL critical-path packages require positive baseline credits and seconds")
        signature = {"package_id": package_id, "baseline_sol_credits": base_credits, "baseline_sol_seconds": base_seconds, "depends_on": list(depends), "writable_paths": normalized, "critical_path": critical, "acceptance_ids": list(acceptance_ids)}
        baseline[package_id] = signature
        first = _package_probability(item["first_pass_probability"], f"{prefix}.packages[{index}].first_pass_probability")
        repair = _package_probability(item["repair_probability"], f"{prefix}.packages[{index}].repair_probability")
        terminal = _package_probability(item["terminal_failure_probability"], f"{prefix}.packages[{index}].terminal_failure_probability")
        if not math.isclose(first + repair + terminal, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise PolicyError(f"{prefix}.packages[{index}] result probabilities must sum to 1")
        execution_credits = finite_number(item["execution_credits"], f"{prefix}.packages[{index}].execution_credits")
        execution_seconds = finite_number(item["execution_seconds"], f"{prefix}.packages[{index}].execution_seconds")
        repair_credits = finite_number(item["repair_credits"], f"{prefix}.packages[{index}].repair_credits")
        repair_seconds = finite_number(item["repair_seconds"], f"{prefix}.packages[{index}].repair_seconds")
        terminal_credits = finite_number(item["terminal_recovery_credits"], f"{prefix}.packages[{index}].terminal_recovery_credits")
        terminal_seconds = finite_number(item["terminal_recovery_seconds"], f"{prefix}.packages[{index}].terminal_recovery_seconds")
        packages[package_id] = {
            "package_id": package_id, "executor": executor, "depends_on": list(depends),
            "critical_path": critical, "acceptance_ids": list(acceptance_ids), "execution_credits": execution_credits,
            "execution_seconds": execution_seconds, "baseline_sol_credits": base_credits,
            "baseline_sol_seconds": base_seconds, "first_pass_probability": first,
            "repair_probability": repair, "repair_credits": repair_credits,
            "repair_seconds": repair_seconds, "terminal_failure_probability": terminal,
            "terminal_recovery_credits": terminal_credits, "terminal_recovery_seconds": terminal_seconds,
            "final_defect_probability": _package_probability(item["final_defect_probability"], f"{prefix}.packages[{index}].final_defect_probability"),
        }
    if acceptance_contract_ids is not None:
        if len(assigned_acceptance) != len(acceptance_contract_ids) or sorted(assigned_acceptance) != sorted(acceptance_contract_ids):
            raise PolicyError("each acceptance_contract_id must be assigned exactly once per allocation")
    if baseline_reference is not None and baseline != dict(baseline_reference):
        raise PolicyError("all v5 candidates must use the same complete baseline map")
    for item in packages.values():
        if set(item["depends_on"]) - set(packages):
            raise PolicyError(f"{prefix}.{item['package_id']} has unknown dependencies")
    if not any(item["executor"] == "LUNA" for item in packages.values()):
        raise PolicyError(f"{prefix} must contain at least one LUNA package")
    sol_baseline_credits = sum(value["baseline_sol_credits"] for value in baseline.values())
    sol_baseline_seconds = sum(value["baseline_sol_seconds"] for value in baseline.values())
    finish: dict[str, float] = {}
    intervals: dict[str, tuple[float, float]] = {}
    completed: set[str] = set()
    active: list[tuple[float, str]] = []
    now = 0.0
    while len(completed) < len(packages):
        available = sorted(
            item["package_id"] for item in packages.values()
            if item["package_id"] not in completed
            and item["package_id"] not in {active_item[1] for active_item in active}
            and all(dep in completed for dep in item["depends_on"])
        )
        sol_busy = any(packages[pid]["executor"] == "SOL" for _, pid in active)
        luna_busy = sum(packages[pid]["executor"] == "LUNA" for _, pid in active)
        for package_id in available:
            item = packages[package_id]
            if item["executor"] == "SOL" and sol_busy:
                continue
            if item["executor"] == "LUNA" and luna_busy >= requested_writers:
                continue
            end = now + item["execution_seconds"]
            active.append((end, package_id))
            if item["executor"] == "SOL": sol_busy = True
            else: luna_busy += 1
        if not active:
            raise PolicyError(f"{prefix}.packages contains a dependency cycle")
        next_end = min(end for end, _ in active)
        now = next_end
        finished = [(end, pid) for end, pid in active if end == next_end]
        active = [(end, pid) for end, pid in active if end != next_end]
        for end, package_id in sorted(finished, key=lambda pair: pair[1]):
            finish[package_id] = end
            intervals[package_id] = (end - packages[package_id]["execution_seconds"], end)
            completed.add(package_id)
    sol_intervals = [intervals[pid] for pid, item in packages.items() if item["executor"] == "SOL"]
    luna_intervals = [intervals[pid] for pid, item in packages.items() if item["executor"] == "LUNA"]
    luna_union = _interval_union(luna_intervals)
    overlap = sum(max(0.0, min(s1, l1) - max(s0, l0)) for s0, s1 in sol_intervals for l0, l1 in luna_union)
    raw_queue = candidate.get("sol_controller_queue")
    normalized_queue = None
    if raw_queue is not None:
        queue_fields = {
            "ready_packages", "review_items", "integration_items", "dispatch_items",
            "acceptance_items",
        }
        queue = require_object(raw_queue, f"{prefix}.sol_controller_queue")
        if set(queue) != queue_fields:
            raise PolicyError(
                f"{prefix}.sol_controller_queue must contain exactly {sorted(queue_fields)}"
            )
        normalized_queue = {
            field: integer(queue[field], f"{prefix}.sol_controller_queue.{field}", minimum=0)
            for field in sorted(queue_fields)
        }
    if overlap > 0:
        controller_mode = "COMPLEMENTARY_PARALLEL"
    elif sol_intervals:
        controller_mode = "SEQUENTIAL_HANDOFF"
    else:
        if normalized_queue is None:
            raise PolicyError(f"{prefix}.sol_controller_queue is required for an all-Luna allocation")
        controller_mode = (
            "WAIT_ALLOWED" if not any(normalized_queue.values()) else "CONTROLLER_QUEUE_PENDING"
        )
    expected_recovery_credits = sum(item["repair_probability"] * item["repair_credits"] + item["terminal_failure_probability"] * item["terminal_recovery_credits"] for item in packages.values())
    expected_recovery_seconds = sum(item["repair_probability"] * item["repair_seconds"] + item["terminal_failure_probability"] * item["terminal_recovery_seconds"] for item in packages.values())
    depended_on = {dependency for item in packages.values() for dependency in item["depends_on"]}
    luna_package_ids = sorted(item["package_id"] for item in packages.values() if item["executor"] == "LUNA")
    luna_leaf_package_ids = sorted(package_id for package_id in luna_package_ids if package_id not in depended_on)
    luna_critical_path_package_ids = sorted(
        item["package_id"] for item in packages.values()
        if item["executor"] == "LUNA" and item["critical_path"]
    )
    allocation_shape_fingerprint = "sha256:" + hashlib.sha256(
        canonical_json(
            {
                "packages": [
                    {
                        "package_id": item["package_id"],
                        "executor": item["executor"],
                        "depends_on": sorted(item["depends_on"]),
                        "critical_path": item["critical_path"],
                        "writable_paths": sorted(baseline[item["package_id"]]["writable_paths"]),
                        "acceptance_ids": sorted(item["acceptance_ids"]),
                    }
                    for item in sorted(packages.values(), key=lambda package: package["package_id"])
                ]
            }
        )
    ).hexdigest()
    return {
        "package_count": len(packages), "effective_writers": min(requested_writers, sum(item["executor"] == "LUNA" for item in packages.values())),
        "scheduled_package_seconds": max(finish.values(), default=0.0),
        "serial_package_seconds": sum(item["execution_seconds"] for item in packages.values()),
        "expected_package_credits": sum(item["execution_credits"] + item["repair_probability"] * item["repair_credits"] + item["terminal_failure_probability"] * item["terminal_recovery_credits"] for item in packages.values()),
        "expected_recovery_credits": expected_recovery_credits, "expected_recovery_seconds": expected_recovery_seconds,
        "first_pass_probability": max(0.0, 1.0 - sum(1.0 - item["first_pass_probability"] for item in packages.values())),
        "final_defect_probability": min(1.0, sum(item["final_defect_probability"] + item["terminal_failure_probability"] for item in packages.values())),
        "baseline_map": baseline, "baseline_sol_credits": sol_baseline_credits, "baseline_sol_seconds": sol_baseline_seconds,
        "controller_mode": controller_mode,
        "sol_controller_queue": normalized_queue,
        "sol_luna_overlap_seconds": overlap,
        "sol_critical_path_overlap_seconds": sum(max(0.0, min(s1, l1) - max(s0, l0)) for pid, (s0, s1) in intervals.items() if packages[pid]["executor"] == "SOL" and packages[pid]["critical_path"] for l0, l1 in luna_union),
        "luna_package_ids": luna_package_ids,
        "luna_leaf_package_ids": luna_leaf_package_ids,
        "luna_leaf_package_count": len(luna_leaf_package_ids),
        "luna_critical_path_package_ids": luna_critical_path_package_ids,
        "luna_critical_path_package_count": len(luna_critical_path_package_ids),
        "allocation_shape_fingerprint": allocation_shape_fingerprint,
    }


def allowed_writers(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    verified_parallel_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    requested = integer(request.get("requested_writers", 1), "requested_writers", minimum=1)
    initial_cap = int(policy["maximum_initial_writers"])
    if verified_parallel_evidence is not None and not isinstance(verified_parallel_evidence, _ExternallyBoundEvidence):
        evidence = {}
    else:
        evidence = require_object(verified_parallel_evidence or {}, "verified_parallel_evidence")
    evidence_ok = (
        evidence.get("source") == EVIDENCE_FEEDBACK_SOURCE
        and evidence.get("policy_change_eligible") is True
        and evidence.get("policy_fingerprint_matches") is True
        and integer(evidence.get("qualified_pairs", 0), "parallel_evidence.qualified_pairs")
        >= int(policy["parallel_review_minimum_pairs"])
        and finite_number(
            evidence.get("elapsed_improvement_fraction", 0.0),
            "parallel_evidence.elapsed_improvement_fraction",
        )
        > 0
        and finite_number(
            evidence.get("credit_regression_fraction", 0.0),
            "parallel_evidence.credit_regression_fraction",
        )
        == 0
        and finite_number(
            evidence.get("failure_rate_regression", 0.0),
            "parallel_evidence.failure_rate_regression",
        )
        == 0
    )
    # Local JSON evidence is advisory only.  Without a cryptographically
    # trusted provider verifier, it must never raise the executable cap.
    cap = initial_cap
    return {
        "requested": requested,
        "allowed": min(requested, cap),
        "effective": min(requested, cap),
        "cap": cap,
        "expanded_from_evidence": False,
        "evidence_source": evidence.get("source", "none"),
        "human_review_recommendation": evidence_ok,
        "evidence_note": (
            "externally-bound evidence is advisory; provider authentication is unverified"
            if evidence_ok
            else "no qualifying externally-bound evidence; initial cap applies"
        ),
        "reason": (
            "matched evidence is available for human review but cannot expand the executable cap"
            if evidence_ok
            else "no qualifying non-regressive matched evidence; initial cap applies"
        ),
    }


def evaluate_route(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    verified_parallel_evidence: Mapping[str, Any] | None = None,
    verified_quality_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = validate_policy_mapping(require_object(policy, "policy"))
    schema_version = request.get("schema_version")
    if type(schema_version) is not int or schema_version not in SINGLE_REQUEST_SCHEMAS | PACKAGE_REQUEST_SCHEMAS | {V5_REQUEST_SCHEMA_VERSION, V6_REQUEST_SCHEMA_VERSION, V7_REQUEST_SCHEMA_VERSION}:
        raise PolicyError("unsupported routing request schema_version")
    reject_unknown_fields(
        request,
        {
            "schema_version",
            "task_family",
            "quality_floor",
            "minimum_credit_savings_fraction",
            "latency_limit_seconds",
            "requested_writers",
            "sol_only",
            "coordination",
            "luna_candidates",
            "acceptance_contract_ids",
            "acceptance_suite_digest",
            "reasoning_profile",
        },
        "request",
    )
    task_family = require_string(request.get("task_family"), "task_family")
    quality_floor = finite_number(
        request.get("quality_floor", policy["minimum_first_pass_probability"]),
        "quality_floor",
        maximum=1.0,
    )
    savings_floor = finite_number(
        request.get("minimum_credit_savings_fraction", policy["minimum_expected_credit_savings_fraction"]),
        "minimum_credit_savings_fraction",
        maximum=1.0,
    )
    policy_quality_floor = float(policy["minimum_first_pass_probability"])
    policy_savings_floor = float(policy["minimum_expected_credit_savings_fraction"])
    if quality_floor < policy_quality_floor:
        raise PolicyError("quality_floor may not be lower than the policy minimum")
    if savings_floor < policy_savings_floor:
        raise PolicyError("minimum_credit_savings_fraction may not be lower than the policy minimum")
    latency_limit = request.get("latency_limit_seconds")
    if latency_limit is not None:
        latency_limit = finite_number(latency_limit, "latency_limit_seconds")

    sol_source = require_object(request.get("sol_only"), "sol_only")
    if "recovery_credits_if_failed" not in sol_source or "recovery_seconds_if_failed" not in sol_source:
        raise PolicyError("sol_only recovery credits and seconds are required")
    sol = estimate(sol_source, "sol_only")
    sol_recovery_credits = finite_number(sol_source.get("recovery_credits_if_failed", 0), "sol_only.recovery_credits_if_failed")
    sol_recovery_seconds = finite_number(sol_source.get("recovery_seconds_if_failed", 0), "sol_only.recovery_seconds_if_failed")
    sol_expected_credits = sol["execution_credits"] + (1 - sol["first_pass_probability"]) * sol_recovery_credits
    sol_expected_seconds = sol["execution_seconds"] + (1 - sol["first_pass_probability"]) * sol_recovery_seconds

    requested_writers = integer(request.get("requested_writers", 1), "requested_writers", minimum=1)
    quality_evidence_mode = schema_version in {V6_REQUEST_SCHEMA_VERSION, V7_REQUEST_SCHEMA_VERSION}
    reasoning_floor_mode = schema_version == V7_REQUEST_SCHEMA_VERSION
    v5_mode = schema_version in {V5_REQUEST_SCHEMA_VERSION, V6_REQUEST_SCHEMA_VERSION, V7_REQUEST_SCHEMA_VERSION}
    package_mode = schema_version in PACKAGE_REQUEST_SCHEMAS or v5_mode
    legacy_schema = schema_version in LEGACY_REQUEST_SCHEMAS
    if schema_version in SINGLE_REQUEST_SCHEMAS and requested_writers > 1:
        raise PolicyError("a package routing schema is required for multiwriter inputs")
    if package_mode and not v5_mode and requested_writers < 2:
        raise PolicyError("package routing schemas require requested_writers greater than 1")
    if v5_mode and requested_writers < 1:
        raise PolicyError("v5 requires requested_writers greater than 0")
    if v5_mode:
        contract_ids = request.get("acceptance_contract_ids")
        if not isinstance(contract_ids, list) or not contract_ids or any(type(value) is not str or not value.strip() for value in contract_ids) or len(contract_ids) != len(set(contract_ids)):
            raise PolicyError("acceptance_contract_ids must be a non-empty unique string array")
    evidence_index: Mapping[str, Any] = {}
    if quality_evidence_mode:
        acceptance_suite_digest = require_digest(
            request.get("acceptance_suite_digest"), "acceptance_suite_digest"
        )
        if not isinstance(verified_quality_evidence, _ExternallyBoundQualityEvidence):
            raise PolicyError("quality-evidence routing requires an externally loaded quality evidence index")
        evidence_index = require_object(
            verified_quality_evidence,
            "verified_quality_evidence",
        )
    elif "acceptance_suite_digest" in request or verified_quality_evidence is not None:
        raise PolicyError("quality evidence requires routing schema 6 or 7")
    reasoning_floor = (
        reasoning_effort_floor(request.get("reasoning_profile"), policy)
        if reasoning_floor_mode
        else None
    )
    if not reasoning_floor_mode and "reasoning_profile" in request:
        raise PolicyError("reasoning_profile requires routing schema 7")
    writer_limit = allowed_writers(request, policy, verified_parallel_evidence)
    effective_writers = int(writer_limit["allowed"])
    coordination_source = require_object(request.get("coordination"), "coordination")
    if v5_mode:
        coordination = coordination_totals(coordination_source, multiwriter=True, require_retained_execution=False)
        if "sol_retained_execution" in coordination_source:
            raise PolicyError("coordination.sol_retained_execution is not accepted by schema v5")
    else:
        coordination = coordination_totals(
            coordination_source,
            multiwriter=requested_writers > 1,
            require_retained_execution=not legacy_schema,
        )
    candidates_source = request.get("luna_candidates")
    if not isinstance(candidates_source, list) or not candidates_source:
        raise PolicyError("luna_candidates must be a non-empty JSON array")
    seen: set[str] = set()
    baseline_reference = None
    allocation_ids: set[str] = set()
    evaluated: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates_source):
        candidate = require_object(raw, f"luna_candidates[{index}]")
        allowed_candidate_fields = (
            {
                "effort", "failure_impact", "effort_basis", "allocation_id", "packages",
                "sol_controller_queue", "quality_evidence_id",
            }
            if quality_evidence_mode else
            {
                "effort", "failure_impact", "effort_basis", "allocation_id", "packages",
                "sol_controller_queue",
            }
            if v5_mode else
            {"effort", "failure_impact", "effort_basis", "packages"}
            if package_mode
            else {
                "effort",
                "first_pass_probability",
                "final_defect_probability",
                "execution_credits",
                "execution_seconds",
                "recovery_credits_if_failed",
                "recovery_seconds_if_failed",
                "failure_impact",
                "effort_basis",
            }
        )
        unknown_candidate_fields = set(candidate) - allowed_candidate_fields
        if unknown_candidate_fields:
            raise PolicyError(
                f"luna_candidates[{index}] has unknown fields: {sorted(unknown_candidate_fields)}"
            )
        effort = normalize_effort(candidate.get("effort"), policy)
        quality_evidence_id = None
        quality_evidence = None
        if quality_evidence_mode:
            quality_evidence_id = require_string(
                candidate.get("quality_evidence_id"),
                f"luna_candidates[{index}].quality_evidence_id",
            )
            quality_evidence = evidence_index.get(quality_evidence_id)
            if quality_evidence is None:
                raise PolicyError(
                    f"luna_candidates[{index}].quality_evidence_id is unknown"
                )
            if quality_evidence["task_family"] != task_family:
                raise PolicyError("quality evidence task_family does not match request")
            if quality_evidence["acceptance_suite_digest"] != acceptance_suite_digest:
                raise PolicyError("quality evidence acceptance_suite_digest does not match request")
        if v5_mode:
            allocation_id = require_string(candidate.get("allocation_id"), f"luna_candidates[{index}].allocation_id")
            if not PACKAGE_ID.fullmatch(allocation_id):
                raise PolicyError(f"luna_candidates[{index}].allocation_id must be a stable hyphen-case identifier")
            if allocation_id in allocation_ids:
                raise PolicyError(f"duplicate allocation_id: {allocation_id}")
            allocation_ids.add(allocation_id)
        else:
            allocation_id = None
        effort_basis = candidate.get("effort_basis")
        if not legacy_schema and effort in {"high", "xhigh", "max"}:
            effort_basis = require_string(
                effort_basis,
                f"luna_candidates[{index}].effort_basis",
            )
        elif effort_basis is not None:
            effort_basis = require_string(
                effort_basis,
                f"luna_candidates[{index}].effort_basis",
            )
        if effort in seen and not v5_mode:
            raise PolicyError(f"duplicate Luna effort candidate: {effort}")
        seen.add(effort)
        if package_mode:
            packages_source = candidate.get("packages")
            if not isinstance(packages_source, list):
                raise PolicyError(
                    f"luna_candidates[{index}].packages must be a non-empty JSON array"
                )
            if v5_mode:
                active_cap = int(policy.get("maximum_active_luna_writers", 1))
                schedule = package_schedule_v5(candidate, requested_writers=min(requested_writers, active_cap), prefix=f"luna_candidates[{index}]", baseline_reference=baseline_reference, acceptance_contract_ids=contract_ids)
                baseline_reference = schedule["baseline_map"] if baseline_reference is None else baseline_reference
                if not math.isclose(schedule["baseline_sol_credits"], sol["execution_credits"], abs_tol=1e-9) or not math.isclose(schedule["baseline_sol_seconds"], sol["execution_seconds"], abs_tol=1e-9):
                    raise PolicyError("v5 baseline map must exactly match sol_only execution credits and seconds")
            else:
                schedule = package_schedule(candidate, requested_writers=effective_writers, prefix=f"luna_candidates[{index}]")
            first_pass_probability = schedule["first_pass_probability"]
            final_defect_probability = schedule["final_defect_probability"]
            package_seconds = schedule["scheduled_package_seconds"]
            serial_package_seconds = schedule["serial_package_seconds"]
            package_credits = schedule["expected_package_credits"]
            expected_recovery_seconds = schedule["expected_recovery_seconds"]
            expected_recovery_credits = schedule["expected_recovery_credits"]
            candidate_effective_writers = schedule["effective_writers"]
            sol_luna_overlap_seconds = schedule.get("sol_luna_overlap_seconds", 0.0)
            sol_critical_path_overlap_seconds = schedule.get("sol_critical_path_overlap_seconds", 0.0)
            controller_mode = schedule.get("controller_mode")
        else:
            values = estimate(candidate, f"luna_candidates[{index}]", allow_metadata=True)
            recovery_credits = finite_number(
                candidate.get("recovery_credits_if_failed"), f"luna_candidates[{index}].recovery_credits_if_failed"
            )
            recovery_seconds = finite_number(
                candidate.get("recovery_seconds_if_failed"), f"luna_candidates[{index}].recovery_seconds_if_failed"
            )
            first_pass_probability = values["first_pass_probability"]
            final_defect_probability = values["final_defect_probability"]
            package_seconds = values["execution_seconds"]
            serial_package_seconds = values["execution_seconds"]
            package_credits = values["execution_credits"] + (1 - first_pass_probability) * recovery_credits
            expected_recovery_seconds = (1 - first_pass_probability) * recovery_seconds
            expected_recovery_credits = (1 - first_pass_probability) * recovery_credits
            candidate_effective_writers = 1
            sol_luna_overlap_seconds = 0.0
            sol_critical_path_overlap_seconds = 0.0
            controller_mode = None
        expected_credits = coordination["credits"] + package_credits
        if v5_mode:
            scheduled_seconds = coordination["serial_seconds"] + package_seconds + expected_recovery_seconds
        else:
            scheduled_seconds = coordination["serial_seconds"] + max(coordination["retained_execution_seconds"], package_seconds) + expected_recovery_seconds
        expected_seconds = scheduled_seconds
        credit_savings = 1 - expected_credits / sol_expected_credits if sol_expected_credits else 0.0
        elapsed_savings = 1 - scheduled_seconds / sol_expected_seconds if sol_expected_seconds else 0.0
        # Measure orchestration burden against the work it is intended to
        # replace.  Using the candidate's own total as the denominator creates
        # a perverse incentive: making Luna cheaper can increase the reported
        # coordination share and reject the most economical allocation.
        coordination_share = (
            coordination["overhead_credits"] / sol_expected_credits
            if sol_expected_credits else 0.0
        )
        rejection_reasons: list[str] = []
        if reasoning_floor is not None:
            effort_rank = {item: position for position, item in enumerate(policy["effort_order"])}
            if effort_rank[effort] < effort_rank[reasoning_floor["minimum_effort"]]:
                rejection_reasons.append("effort_below_reasoning_floor")
        if quality_evidence_mode:
            assert quality_evidence is not None
            if quality_evidence["effort"] != effort:
                rejection_reasons.append("quality_evidence_effort_mismatch")
            if quality_evidence["allocation_shape_fingerprint"] != schedule["allocation_shape_fingerprint"]:
                rejection_reasons.append("quality_evidence_allocation_shape_mismatch")
            if first_pass_probability > quality_evidence["first_pass_probability"] + 1e-12:
                rejection_reasons.append("quality_evidence_first_pass_overstated")
            if final_defect_probability + 1e-12 < quality_evidence["final_defect_probability"]:
                rejection_reasons.append("quality_evidence_final_defect_understated")
        if legacy_schema:
            rejection_reasons.append("legacy_routing_schema_requires_refresh")
        if package_mode and requested_writers > effective_writers:
            rejection_reasons.append("requested_parallelism_exceeds_executable_cap")
        if first_pass_probability < quality_floor:
            rejection_reasons.append("first_pass_probability_below_floor")
        if final_defect_probability > sol["final_defect_probability"]:
            rejection_reasons.append("predicted_defect_rate_regresses")
        if credit_savings < savings_floor:
            rejection_reasons.append("expected_credit_savings_below_floor")
        # Time is a hard requirement, but equality is not an improvement.  The
        # policy value remains explicit for compatibility/documentation while
        # the strict comparison prevents a zero-savings tie from routing.
        if scheduled_seconds >= sol_expected_seconds or elapsed_savings <= float(
            policy["minimum_expected_elapsed_savings_fraction"]
        ):
            rejection_reasons.append("expected_elapsed_time_regresses")
        if coordination_share >= float(policy["maximum_coordination_credit_share"]):
            rejection_reasons.append("coordination_credit_share_too_high")
        if candidate_effective_writers > 1 and package_seconds >= serial_package_seconds:
            rejection_reasons.append("no_parallel_package_speedup")
        if v5_mode:
            if controller_mode == "CONTROLLER_QUEUE_PENDING":
                rejection_reasons.append("unallocated_sol_controller_work")
            if schedule.get("duplicate_work_fraction", 0.0) > float(policy.get("maximum_duplicate_work_fraction", 0.0)):
                rejection_reasons.append("duplicate_work_fraction_exceeds_policy")
        if latency_limit is not None and expected_seconds > latency_limit:
            rejection_reasons.append("latency_limit_exceeded")
        impact = require_string(candidate.get("failure_impact", "low"), f"luna_candidates[{index}].failure_impact")
        if impact not in {"low", "medium", "high", "critical"}:
            raise PolicyError("failure_impact must be low, medium, high, or critical")
        if impact in {"high", "critical"} and first_pass_probability < max(quality_floor, 0.9):
            rejection_reasons.append("high_failure_impact_requires_0.9_first_pass_probability")
        evaluated.append(
            {
                "effort": effort,
                "effort_basis": effort_basis,
                "quality_evidence_id": quality_evidence_id,
                "quality_evidence_source": quality_evidence["source_kind"] if quality_evidence else None,
                "eligible": not rejection_reasons,
                "expected_accepted_credits": expected_credits,
                "expected_accepted_seconds": expected_seconds,
                "expected_credit_savings_fraction": credit_savings,
                "expected_elapsed_savings_fraction": elapsed_savings,
                "coordination_credit_share": coordination_share,
                "expected_recovery_credits": round(expected_recovery_credits, 6),
                "expected_recovery_seconds": round(expected_recovery_seconds, 6),
                "first_pass_probability": first_pass_probability,
                "final_defect_probability": final_defect_probability,
                "serial_package_seconds": serial_package_seconds,
                "scheduled_package_seconds": package_seconds,
                "effective_writers": candidate_effective_writers,
                "package_expected_seconds": package_seconds + expected_recovery_seconds,
                "failure_impact": impact,
                "allocation_id": allocation_id,
                "delegated_baseline_credit_fraction": (sum(v["baseline_sol_credits"] for k, v in schedule.get("baseline_map", {}).items() if next((p for p in candidate.get("packages", []) if p.get("package_id") == k), {}).get("executor") == "LUNA") / sol["execution_credits"] if v5_mode and sol["execution_credits"] else 0.0),
                "delegated_package_count": (sum(1 for p in candidate.get("packages", []) if p.get("executor") == "LUNA") if v5_mode else None),
                "sol_retained_package_count": (sum(1 for p in candidate.get("packages", []) if p.get("executor") == "SOL") if v5_mode else None),
                "controller_mode": controller_mode,
                "sol_luna_overlap_seconds": sol_luna_overlap_seconds,
                "sol_critical_path_overlap_seconds": sol_critical_path_overlap_seconds,
                "luna_package_ids": schedule.get("luna_package_ids", []) if v5_mode else None,
                "luna_leaf_package_ids": schedule.get("luna_leaf_package_ids", []) if v5_mode else None,
                "luna_leaf_package_count": schedule.get("luna_leaf_package_count", 0) if v5_mode else None,
                "luna_critical_path_package_ids": schedule.get("luna_critical_path_package_ids", []) if v5_mode else None,
                "luna_critical_path_package_count": schedule.get("luna_critical_path_package_count", 0) if v5_mode else None,
                "allocation_shape_fingerprint": schedule.get("allocation_shape_fingerprint") if v5_mode else None,
                "duplicate_work_fraction": 0.0,
                "rejection_reasons": rejection_reasons,
            }
        )

    effort_rank = {effort: index for index, effort in enumerate(policy["effort_order"])}
    if v5_mode and policy["high_effort_critical_path_requires_lower_effort_quality_evidence"]:
        quality_reasons = {
            "first_pass_probability_below_floor",
            "predicted_defect_rate_regresses",
            "high_failure_impact_requires_0.9_first_pass_probability",
            "quality_evidence_effort_mismatch",
            "quality_evidence_allocation_shape_mismatch",
            "quality_evidence_first_pass_overstated",
            "quality_evidence_final_defect_understated",
            "effort_below_reasoning_floor",
        }
        for candidate in evaluated:
            if candidate["effort"] not in {"high", "xhigh", "max"}:
                continue
            if candidate["luna_critical_path_package_count"] == 0:
                continue
            candidate_rank = effort_rank[candidate["effort"]]
            lower_comparators = [
                other for other in evaluated
                if other is not candidate
                and effort_rank[other["effort"]] < candidate_rank
                and other["allocation_shape_fingerprint"] == candidate["allocation_shape_fingerprint"]
            ]
            lower_quality_failed = bool(lower_comparators) and all(
                quality_reasons.intersection(other["rejection_reasons"])
                for other in lower_comparators
            )
            if not lower_quality_failed:
                candidate["rejection_reasons"].append(
                    "high_effort_critical_path_requires_lower_effort_quality_evidence"
                )
                candidate["eligible"] = False

    eligible = [candidate for candidate in evaluated if candidate["eligible"]]
    selected = min(
        eligible,
        key=lambda item: (
            item["expected_accepted_credits"],
            item["expected_accepted_seconds"],
            effort_rank[item["effort"]],
            item.get("allocation_id") or "",
        ),
        default=None,
    )
    route = "SOL_LUNA" if selected else "SOL_ONLY"
    actual_effective_writers = selected["effective_writers"] if selected else None
    return {
        "schema_version": schema_version,
        "policy_version": policy["policy_version"],
        "policy_fingerprint": policy_fingerprint(policy),
        "task_family": task_family,
        "route": route,
        "selected_luna_effort": selected["effort"] if selected else None,
        "selection_basis": (
            "lowest expected accepted credits among candidates satisfying quality, defect, savings, and latency gates"
            if selected
            else "no Luna candidate satisfied every delivery gate"
        ),
        "quality_floor": quality_floor,
        "reasoning_effort_floor": reasoning_floor,
        "minimum_credit_savings_fraction": savings_floor,
        "sol_only": {
            "expected_accepted_credits": sol_expected_credits,
            "expected_accepted_seconds": sol_expected_seconds,
            "first_pass_probability": sol["first_pass_probability"],
            "final_defect_probability": sol["final_defect_probability"],
        },
        "coordination": coordination,
        "writer_limit": writer_limit,
        "requested_writers": requested_writers,
         "effective_writers": actual_effective_writers,
        "candidates": evaluated,
         "selected_metrics": (
            {
                field: selected[field]
                for field in (
                    "serial_package_seconds",
                    "scheduled_package_seconds",
                    "expected_accepted_credits",
                    "expected_accepted_seconds",
                    "expected_credit_savings_fraction",
                    "expected_elapsed_savings_fraction",
                     "coordination_credit_share",
                    "effective_writers",
                    "allocation_id",
                    "delegated_baseline_credit_fraction",
                    "delegated_package_count",
                    "sol_retained_package_count",
                    "controller_mode",
                    "sol_luna_overlap_seconds",
                    "sol_critical_path_overlap_seconds",
                    "luna_leaf_package_ids",
                    "luna_leaf_package_count",
                    "luna_critical_path_package_ids",
                    "luna_critical_path_package_count",
                    "allocation_shape_fingerprint",
                    "duplicate_work_fraction",
                    "quality_evidence_id",
                    "quality_evidence_source",
                )
            }
            if selected
            else None
        ),
        "automatic_execution_allowed": False,
    }


def review_depth(source: Mapping[str, Any]) -> dict[str, Any]:
    risk = require_string(source.get("risk_level", "medium"), "risk_level").lower()
    if risk not in {"low", "medium", "high", "critical"}:
        raise PolicyError("risk_level must be low, medium, high, or critical")
    flags = {
        name: bool(source.get(name, False))
        for name in (
            "shared_interface",
            "security_or_safety_sensitive",
            "scope_discrepancy",
            "verification_failed",
            "acceptance_nondeterministic",
        )
    }
    repairs = integer(source.get("repair_rounds", 0), "repair_rounds")
    deep_reasons = [name for name, enabled in flags.items() if enabled]
    if risk in {"high", "critical"}:
        deep_reasons.append("high_risk_level")
    if repairs:
        deep_reasons.append("package_was_repaired")
    if deep_reasons:
        depth = "DEEP"
    elif risk == "low" and bool(source.get("authoritative_checks_passed", False)):
        depth = "TARGETED"
    else:
        depth = "STANDARD"
    return {
        "review_depth": depth,
        "reasons": sorted(set(deep_reasons)) or ["risk-proportional default"],
        "minimum_actions": {
            "TARGETED": ["inspect changed paths and compact diff", "verify authoritative targeted checks"],
            "STANDARD": ["inspect full package diff", "rerun integration-relevant checks"],
            "DEEP": ["inspect full diff and affected call paths", "run adversarial and regression checks"],
        }[depth],
    }


def rework_decision(source: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    current_effort = normalize_effort(source.get("current_effort"), policy)
    if bool(source.get("requires_new_authority", False)):
        return {"action": "BLOCKED", "reason": "repair requires new authority or a user-owned decision"}
    new_evidence = bool(source.get("new_evidence", False))
    repairs = integer(source.get("focused_repairs_used", 0), "focused_repairs_used")
    escalations = integer(source.get("effort_escalations_used", 0), "effort_escalations_used")
    strict_closure = any(
        name in source
        for name in (
            "failure_evidence_ref", "target_action_ids", "marginal_net_substitution",
            "repair_cost_weight", "repair_cost_weight_used", "repair_cost_weight_limit",
        )
    )
    repair_limit = int(policy["rework_budget"]["focused_repairs"]) if strict_closure else 1
    if strict_closure:
        evidence_ref = source.get("failure_evidence_ref")
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise PolicyError("failure_evidence_ref must be a non-empty string in strict closure mode")
        target_action_ids = source.get("target_action_ids")
        if (
            not isinstance(target_action_ids, list)
            or not target_action_ids
            or any(not isinstance(item, str) or not item.strip() for item in target_action_ids)
            or len(set(target_action_ids)) != len(target_action_ids)
        ):
            raise PolicyError("target_action_ids must be a non-empty unique string array in strict closure mode")
        marginal = finite_number(source.get("marginal_net_substitution"), "marginal_net_substitution", minimum=-1.0)
        repair_cost = finite_number(source.get("repair_cost_weight"), "repair_cost_weight")
        repair_cost_used = finite_number(source.get("repair_cost_weight_used", 0), "repair_cost_weight_used")
        repair_cost_limit = finite_number(source.get("repair_cost_weight_limit"), "repair_cost_weight_limit")
        if repair_cost_limit <= 0:
            raise PolicyError("repair_cost_weight_limit must be positive")
        if repair_cost <= 0:
            raise PolicyError("repair_cost_weight must be positive")
        if not new_evidence:
            return {"action": "REPAIR_LOCKED", "reason": "strict closure repair requires new failure evidence"}
        if marginal <= 0:
            return {"action": "SOL_RECLAIM", "reason": "focused repair has no positive marginal net substitution"}
        if repair_cost_used + repair_cost > repair_cost_limit:
            return {"action": "REPAIR_LOCKED", "reason": "frozen repair cost budget is exhausted"}
    if repairs < repair_limit and new_evidence:
        result = {
            "action": "FOCUSED_REPAIR",
            "reason": "an evidence-backed repair remains within the frozen limit",
            "remaining_focused_repairs": repair_limit - repairs - 1,
        }
        if strict_closure:
            result.update({
                "failure_evidence_ref": evidence_ref,
                "target_action_ids": target_action_ids,
                "marginal_net_substitution": marginal,
                "remaining_repair_cost_weight": repair_cost_limit - repair_cost_used - repair_cost,
            })
        return result
    if strict_closure and repairs >= repair_limit:
        return {"action": "REPAIR_LOCKED", "reason": "focused repair attempt limit is exhausted"}
    if bool(source.get("can_repartition", False)):
        return {"action": "REPARTITION", "reason": "repair budget is exhausted or unsupported; reduce coupling"}
    efforts = list(policy["effort_order"])
    position = efforts.index(current_effort)
    if escalations < int(policy["rework_budget"]["effort_escalations"]) and position + 1 < len(efforts):
        return {
            "action": "ESCALATE_ONCE",
            "next_effort": efforts[position + 1],
            "reason": "one evidence-backed effort escalation remains",
        }
    return {"action": "SOL_RECLAIM", "reason": "repair and escalation budget exhausted"}


def template() -> dict[str, Any]:
    source = {
        "schema_version": V7_REQUEST_SCHEMA_VERSION,
        "task_family": "bounded-feature",
        "quality_floor": 0.8,
        "minimum_credit_savings_fraction": 0.50,
        "latency_limit_seconds": None,
        "requested_writers": 1,
        "acceptance_contract_ids": ["accept-core", "accept-analysis", "accept-tests"],
        "reasoning_profile": {
            "architecture_settled": True,
            "deterministic_acceptance": True,
            "semantic_coupling": "low",
            "cross_module_invariants": False,
            "multi_interface_contract": False,
            "adversarial_edge_cases": False,
            "platform_sensitive_io": False,
            "strict_serialization": False,
        },
        "sol_only": {
            "first_pass_probability": 1.0,
            "final_defect_probability": 0.02,
            "execution_credits": 100,
            "execution_seconds": 900,
            "recovery_credits_if_failed": 0,
            "recovery_seconds_if_failed": 0,
        },
        "coordination": {
            "sol_planning": {"credits": 5, "seconds": 90},
            "sol_review": {"credits": 5, "seconds": 120},
            "integration": {"credits": 3, "seconds": 60},
            "queue": {"credits": 1, "seconds": 10},
            "merge_contention": {"credits": 1, "seconds": 10},
        },
        "luna_candidates": [
            {
                "effort": "medium",
                "allocation_id": "allocation-default",
                "quality_evidence_id": "evidence-medium-default",
                "failure_impact": "low",
                "packages": [
                    {
                        "executor": "SOL",
                        "package_id": "sol-core",
                        "depends_on": [],
                        "writable_paths": ["src/sol-core.py"],
                        "critical_path": True,
                        "acceptance_ids": ["accept-core"],
                        "baseline_sol_credits": 50,
                        "baseline_sol_seconds": 450,
                        "execution_credits": 20,
                        "execution_seconds": 450,
                        "first_pass_probability": 1.0,
                        "repair_probability": 0.0,
                        "repair_credits": 0,
                        "repair_seconds": 0,
                        "terminal_failure_probability": 0.0,
                        "terminal_recovery_credits": 0,
                        "terminal_recovery_seconds": 0,
                        "final_defect_probability": 0.0,
                    },
                    {
                        "executor": "LUNA",
                        "package_id": "luna-analysis",
                        "depends_on": [],
                        "writable_paths": ["src/luna-analysis.py"],
                        "critical_path": False,
                        "acceptance_ids": ["accept-analysis"],
                        "baseline_sol_credits": 25,
                        "baseline_sol_seconds": 250,
                        "execution_credits": 8,
                        "execution_seconds": 250,
                        "first_pass_probability": 1.0,
                        "repair_probability": 0.0,
                        "repair_credits": 0,
                        "repair_seconds": 0,
                        "terminal_failure_probability": 0.0,
                        "terminal_recovery_credits": 0,
                        "terminal_recovery_seconds": 0,
                        "final_defect_probability": 0.0,
                    },
                    {
                        "executor": "LUNA",
                        "package_id": "luna-tests",
                        "depends_on": [],
                        "writable_paths": ["tests/luna-tests.py"],
                        "critical_path": False,
                        "acceptance_ids": ["accept-tests"],
                        "baseline_sol_credits": 25,
                        "baseline_sol_seconds": 200,
                        "execution_credits": 7,
                        "execution_seconds": 200,
                        "first_pass_probability": 1.0,
                        "repair_probability": 0.0,
                        "repair_credits": 0,
                        "repair_seconds": 0,
                        "terminal_failure_probability": 0.0,
                        "terminal_recovery_credits": 0,
                        "terminal_recovery_seconds": 0,
                        "final_defect_probability": 0.0,
                    },
                ],
            },
        ],
    }
    acceptance_suite_digest = "sha256:" + hashlib.sha256(
        canonical_json(source["acceptance_contract_ids"])
    ).hexdigest()
    source["acceptance_suite_digest"] = acceptance_suite_digest
    return source


def quality_evidence_template() -> dict[str, Any]:
    source = template()
    candidate = source["luna_candidates"][0]
    allocation_shape_fingerprint = package_schedule_v5(
        candidate,
        requested_writers=1,
        prefix="quality_evidence_template.luna_candidates[0]",
        acceptance_contract_ids=source["acceptance_contract_ids"],
    )["allocation_shape_fingerprint"]
    acceptance_suite_digest = source["acceptance_suite_digest"]
    evidence = {
        "evidence_id": "evidence-medium-default",
        "task_family": source["task_family"],
        "effort": "medium",
        "allocation_shape_fingerprint": allocation_shape_fingerprint,
        "acceptance_suite_digest": acceptance_suite_digest,
        "observations": 1,
        "first_pass_accepted": 0,
        "final_defect_runs": 1,
        "source_kind": "candidate-preflight",
    }
    evidence["evidence_digest"] = _quality_evidence_digest(evidence)
    return {"schema_version": 1, "evidence": [evidence]}


def verified_parallel_evidence_from_ledger(
    ledger_path: Path,
    task_family: str,
    policy: Mapping[str, Any],
    *,
    verified_credit_receipts: Mapping[str, Any] | Path | None = None,
) -> dict[str, Any]:
    script = Path(__file__).with_name("evidence_ledger.py")
    spec = importlib.util.spec_from_file_location("sol_luna_evidence_ledger", script)
    if not spec or not spec.loader:
        raise PolicyError("cannot load evidence ledger validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        if isinstance(verified_credit_receipts, Path):
            verified_credit_receipts = module.load_verified_credit_receipts(verified_credit_receipts)
        elif verified_credit_receipts is not None:
            # Validate caller-supplied objects with the ledger's own strict
            # schema checker before passing them into feedback aggregation.
            if not isinstance(verified_credit_receipts, Mapping):
                raise PolicyError("verified credit receipts must be a JSON object or path")
            module._validate_verified_receipt_index(verified_credit_receipts)
        feedback = module.task_family_feedback(
            module.load_records(ledger_path),
            task_family=task_family,
            minimum_pairs=int(policy["parallel_review_minimum_pairs"]),
            minimum_credit_savings_fraction=float(policy["minimum_expected_credit_savings_fraction"]),
            minimum_first_pass_acceptance_rate=float(policy["minimum_first_pass_probability"]),
            verified_credit_receipts=verified_credit_receipts,
        )
    except (OSError, ValueError) as exc:
        raise PolicyError(f"cannot verify parallel evidence: {exc}") from exc
    if feedback.get("schema_version") != EVIDENCE_LEDGER_SCHEMA_VERSION:
        raise PolicyError("unsupported evidence ledger feedback schema_version")
    strongest = feedback.get("strongest_cohort") or {}
    cohort = strongest.get("cohort") or {}
    sol_elapsed = float(strongest.get("median_sol_elapsed_seconds") or 0)
    luna_elapsed = float(strongest.get("median_luna_elapsed_seconds") or 0)
    reduction = float(strongest.get("median_paired_reduction_fraction") or 0)
    acceptance = strongest.get("independent_acceptance_rate") or {}
    defects = strongest.get("final_defect_rate") or {}
    policy_matches = cohort.get("policy") == policy_fingerprint(policy)
    return _ExternallyBoundEvidence({
        "source": EVIDENCE_FEEDBACK_SOURCE,
        "policy_change_eligible": bool(strongest.get("policy_change_eligible")),
        "policy_fingerprint_matches": policy_matches,
        "qualified_pairs": int(strongest.get("qualified_matched_pairs") or 0),
        "elapsed_improvement_fraction": max(0.0, (sol_elapsed - luna_elapsed) / sol_elapsed)
        if sol_elapsed
        else 0.0,
        "credit_regression_fraction": max(0.0, -reduction),
        "failure_rate_regression": max(
            0.0,
            float(acceptance.get("SOL_ONLY", 0)) - float(acceptance.get("SOL_LUNA", 0)),
            float(defects.get("SOL_LUNA", 0)) - float(defects.get("SOL_ONLY", 0)),
        ),
        "feedback_posture": feedback.get("posture"),
    })


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Evaluate versioned Sol-Luna routing economics.")
    result.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("template")
    sub.add_parser("quality-evidence-template")
    sub.add_parser("fingerprint")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--input", required=True, type=Path)
    evaluate.add_argument("--ledger", type=Path)
    evaluate.add_argument("--verified-credit-receipts", type=Path)
    evaluate.add_argument("--quality-evidence-index", type=Path)
    for name in ("review", "rework"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "evaluate" and args.verified_credit_receipts and not args.ledger:
            raise PolicyError("--verified-credit-receipts requires --ledger")
        policy = load_policy(args.policy)
        if args.command == "template":
            output = template()
        elif args.command == "quality-evidence-template":
            output = quality_evidence_template()
        elif args.command == "fingerprint":
            output = {
                "policy_version": policy["policy_version"],
                "policy_fingerprint": policy_fingerprint(policy),
            }
        else:
            source = strict_json_loads(args.input.read_text(encoding="utf-8"))
            source = require_object(source, "input")
            if args.command == "evaluate":
                verified_quality = (
                    load_quality_evidence_index(
                        args.quality_evidence_index,
                        task_family=require_string(source.get("task_family"), "task_family"),
                        acceptance_suite_digest=require_digest(
                            source.get("acceptance_suite_digest"),
                            "acceptance_suite_digest",
                        ),
                    )
                    if args.quality_evidence_index
                    else None
                )
                verified_evidence = (
                    verified_parallel_evidence_from_ledger(
                        args.ledger,
                        require_string(source.get("task_family"), "task_family"),
                        policy,
                        verified_credit_receipts=args.verified_credit_receipts,
                    )
                    if args.ledger
                    else None
                )
                output = evaluate_route(
                    source,
                    policy,
                    verified_parallel_evidence=verified_evidence,
                    verified_quality_evidence=verified_quality,
                )
            elif args.command == "review":
                output = review_depth(source)
            else:
                output = rework_decision(source, policy)
    except (OSError, json.JSONDecodeError, PolicyError) as exc:
        print(f"routing policy error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(display_round(output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

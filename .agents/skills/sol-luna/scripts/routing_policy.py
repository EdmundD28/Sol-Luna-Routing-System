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


class _ExternallyBoundEvidence(dict[str, Any]):
    """Private marker for advisory ledger evidence without provider proof."""


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


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot load routing policy: {exc}") from exc
    require_object(policy, "policy")
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
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
    integer(policy.get("parallel_review_minimum_pairs"), "parallel_review_minimum_pairs", minimum=1)
    budget = require_object(policy.get("rework_budget"), "rework_budget")
    if integer(budget.get("focused_repairs"), "rework_budget.focused_repairs") != 1:
        raise PolicyError("the policy permits exactly one focused repair")
    if integer(budget.get("effort_escalations"), "rework_budget.effort_escalations") != 1:
        raise PolicyError("the policy permits exactly one effort escalation")
    return dict(policy)


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
) -> dict[str, Any]:
    schema_version = request.get("schema_version")
    if schema_version not in SINGLE_REQUEST_SCHEMAS | PACKAGE_REQUEST_SCHEMAS:
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
    package_mode = schema_version in PACKAGE_REQUEST_SCHEMAS
    legacy_schema = schema_version in LEGACY_REQUEST_SCHEMAS
    if schema_version in SINGLE_REQUEST_SCHEMAS and requested_writers > 1:
        raise PolicyError("a package routing schema is required for multiwriter inputs")
    if package_mode and requested_writers < 2:
        raise PolicyError("package routing schemas require requested_writers greater than 1")
    writer_limit = allowed_writers(request, policy, verified_parallel_evidence)
    effective_writers = int(writer_limit["allowed"])
    coordination_source = require_object(request.get("coordination"), "coordination")
    coordination = coordination_totals(
        coordination_source,
        multiwriter=requested_writers > 1,
        require_retained_execution=not legacy_schema,
    )
    candidates_source = request.get("luna_candidates")
    if not isinstance(candidates_source, list) or not candidates_source:
        raise PolicyError("luna_candidates must be a non-empty JSON array")
    seen: set[str] = set()
    evaluated: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates_source):
        candidate = require_object(raw, f"luna_candidates[{index}]")
        allowed_candidate_fields = (
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
        if effort in seen:
            raise PolicyError(f"duplicate Luna effort candidate: {effort}")
        seen.add(effort)
        if package_mode:
            packages_source = candidate.get("packages")
            if not isinstance(packages_source, list):
                raise PolicyError(
                    f"luna_candidates[{index}].packages must be a non-empty JSON array"
                )
            schedule = package_schedule(candidate, requested_writers=effective_writers, prefix=f"luna_candidates[{index}]")
            first_pass_probability = schedule["first_pass_probability"]
            final_defect_probability = schedule["final_defect_probability"]
            package_seconds = schedule["scheduled_package_seconds"]
            serial_package_seconds = schedule["serial_package_seconds"]
            package_credits = schedule["expected_package_credits"]
            expected_recovery_seconds = schedule["expected_recovery_seconds"]
            expected_recovery_credits = schedule["expected_recovery_credits"]
            candidate_effective_writers = schedule["effective_writers"]
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
        expected_credits = coordination["credits"] + package_credits
        scheduled_seconds = (
            coordination["serial_seconds"]
            + max(coordination["retained_execution_seconds"], package_seconds)
            + expected_recovery_seconds
        )
        expected_seconds = scheduled_seconds
        credit_savings = 1 - expected_credits / sol_expected_credits if sol_expected_credits else 0.0
        elapsed_savings = 1 - scheduled_seconds / sol_expected_seconds if sol_expected_seconds else 0.0
        coordination_share = coordination["overhead_credits"] / expected_credits if expected_credits else 0.0
        rejection_reasons: list[str] = []
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
                "rejection_reasons": rejection_reasons,
            }
        )

    effort_rank = {effort: index for index, effort in enumerate(policy["effort_order"])}
    eligible = [candidate for candidate in evaluated if candidate["eligible"]]
    selected = min(
        eligible,
        key=lambda item: (
            item["expected_accepted_credits"],
            item["expected_accepted_seconds"],
            effort_rank[item["effort"]],
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
    if repairs < int(policy["rework_budget"]["focused_repairs"]) and new_evidence:
        return {"action": "FOCUSED_REPAIR", "reason": "one evidence-backed repair remains"}
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
    return {
        "schema_version": SCHEMA_VERSION,
        "task_family": "bounded-feature",
        "quality_floor": 0.8,
        "minimum_credit_savings_fraction": 0.50,
        "latency_limit_seconds": None,
        "requested_writers": 1,
        "sol_only": {
            "first_pass_probability": 0.9,
            "final_defect_probability": 0.02,
            "execution_credits": 100,
            "execution_seconds": 900,
            "recovery_credits_if_failed": 30,
            "recovery_seconds_if_failed": 300,
        },
        "coordination": {
            "sol_planning": {"credits": 5, "seconds": 90},
            "sol_retained_execution": {"credits": 10, "seconds": 300},
            "sol_review": {"credits": 5, "seconds": 120},
            "integration": {"credits": 3, "seconds": 60},
        },
        "luna_candidates": [
            {
                "effort": "medium",
                "first_pass_probability": 0.78,
                "final_defect_probability": 0.02,
                "execution_credits": 15,
                "execution_seconds": 480,
                "recovery_credits_if_failed": 25,
                "recovery_seconds_if_failed": 420,
                "failure_impact": "low",
            },
            {
                "effort": "xhigh",
                "effort_basis": "the Medium estimate is below the required first-pass quality floor",
                "first_pass_probability": 0.92,
                "final_defect_probability": 0.01,
                "execution_credits": 20,
                "execution_seconds": 500,
                "recovery_credits_if_failed": 20,
                "recovery_seconds_if_failed": 300,
                "failure_impact": "low",
            },
        ],
    }


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
    sub.add_parser("fingerprint")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--input", required=True, type=Path)
    evaluate.add_argument("--ledger", type=Path)
    evaluate.add_argument("--verified-credit-receipts", type=Path)
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
        elif args.command == "fingerprint":
            output = {
                "policy_version": policy["policy_version"],
                "policy_fingerprint": policy_fingerprint(policy),
            }
        else:
            source = json.loads(args.input.read_text(encoding="utf-8"))
            source = require_object(source, "input")
            if args.command == "evaluate":
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

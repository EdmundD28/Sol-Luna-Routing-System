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
import sys
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "references" / "routing-policy.v1.json"


class PolicyError(ValueError):
    """The routing input or policy violates the executable contract."""


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


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise PolicyError(f"{field} must be a non-empty single-line string")
    return value.strip()


def canonical_json(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot load routing policy: {exc}") from exc
    require_object(policy, "policy")
    if policy.get("schema_version") != SCHEMA_VERSION:
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
    initial = integer(policy.get("maximum_initial_writers"), "maximum_initial_writers", minimum=1)
    expanded = integer(policy.get("maximum_evidence_backed_writers"), "maximum_evidence_backed_writers", minimum=initial)
    integer(policy.get("parallel_expansion_minimum_pairs"), "parallel_expansion_minimum_pairs", minimum=1)
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


def estimate(source: Mapping[str, Any], prefix: str) -> dict[str, float]:
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


def phase_totals(source: Mapping[str, Any]) -> dict[str, float]:
    allowed = ("sol_planning", "sol_review", "integration")
    credits = 0.0
    seconds = 0.0
    for phase in allowed:
        value = require_object(source.get(phase), f"coordination.{phase}")
        credits += finite_number(value.get("credits"), f"coordination.{phase}.credits")
        seconds += finite_number(value.get("seconds"), f"coordination.{phase}.seconds")
    return {"credits": credits, "seconds": seconds}


def allowed_writers(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    verified_parallel_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    requested = integer(request.get("requested_writers", 1), "requested_writers", minimum=1)
    initial_cap = int(policy["maximum_initial_writers"])
    expanded_cap = int(policy["maximum_evidence_backed_writers"])
    evidence = require_object(verified_parallel_evidence or {}, "verified_parallel_evidence")
    evidence_ok = (
        evidence.get("source") == "evidence-ledger-feedback-v3"
        and evidence.get("policy_change_eligible") is True
        and evidence.get("policy_fingerprint_matches") is True
        and integer(evidence.get("qualified_pairs", 0), "parallel_evidence.qualified_pairs")
        >= int(policy["parallel_expansion_minimum_pairs"])
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
    cap = expanded_cap if evidence_ok else initial_cap
    return {
        "requested": requested,
        "allowed": min(requested, cap),
        "cap": cap,
        "expanded_from_evidence": evidence_ok,
        "evidence_source": evidence.get("source", "none"),
        "reason": (
            "matched evidence permits expansion beyond the two-writer initial cap"
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
    if request.get("schema_version") != SCHEMA_VERSION:
        raise PolicyError("unsupported routing request schema_version")
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
    latency_limit = request.get("latency_limit_seconds")
    if latency_limit is not None:
        latency_limit = finite_number(latency_limit, "latency_limit_seconds")

    sol_source = require_object(request.get("sol_only"), "sol_only")
    sol = estimate(sol_source, "sol_only")
    sol_recovery_credits = finite_number(sol_source.get("recovery_credits_if_failed", 0), "sol_only.recovery_credits_if_failed")
    sol_recovery_seconds = finite_number(sol_source.get("recovery_seconds_if_failed", 0), "sol_only.recovery_seconds_if_failed")
    sol_expected_credits = sol["execution_credits"] + (1 - sol["first_pass_probability"]) * sol_recovery_credits
    sol_expected_seconds = sol["execution_seconds"] + (1 - sol["first_pass_probability"]) * sol_recovery_seconds

    coordination = phase_totals(require_object(request.get("coordination"), "coordination"))
    candidates_source = request.get("luna_candidates")
    if not isinstance(candidates_source, list) or not candidates_source:
        raise PolicyError("luna_candidates must be a non-empty JSON array")
    seen: set[str] = set()
    evaluated: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates_source):
        candidate = require_object(raw, f"luna_candidates[{index}]")
        effort = normalize_effort(candidate.get("effort"), policy)
        if effort in seen:
            raise PolicyError(f"duplicate Luna effort candidate: {effort}")
        seen.add(effort)
        values = estimate(candidate, f"luna_candidates[{index}]")
        recovery_credits = finite_number(
            candidate.get("recovery_credits_if_failed"), f"luna_candidates[{index}].recovery_credits_if_failed"
        )
        recovery_seconds = finite_number(
            candidate.get("recovery_seconds_if_failed"), f"luna_candidates[{index}].recovery_seconds_if_failed"
        )
        expected_credits = coordination["credits"] + values["execution_credits"] + (
            1 - values["first_pass_probability"]
        ) * recovery_credits
        expected_seconds = coordination["seconds"] + values["execution_seconds"] + (
            1 - values["first_pass_probability"]
        ) * recovery_seconds
        credit_savings = 1 - expected_credits / sol_expected_credits if sol_expected_credits else 0.0
        rejection_reasons: list[str] = []
        if values["first_pass_probability"] < quality_floor:
            rejection_reasons.append("first_pass_probability_below_floor")
        if values["final_defect_probability"] > sol["final_defect_probability"]:
            rejection_reasons.append("predicted_defect_rate_regresses")
        if credit_savings < savings_floor:
            rejection_reasons.append("expected_credit_savings_below_floor")
        if expected_seconds > sol_expected_seconds:
            rejection_reasons.append("expected_elapsed_time_regresses")
        if latency_limit is not None and expected_seconds > latency_limit:
            rejection_reasons.append("latency_limit_exceeded")
        impact = require_string(candidate.get("failure_impact", "low"), f"luna_candidates[{index}].failure_impact")
        if impact not in {"low", "medium", "high", "critical"}:
            raise PolicyError("failure_impact must be low, medium, high, or critical")
        if impact in {"high", "critical"} and values["first_pass_probability"] < max(quality_floor, 0.9):
            rejection_reasons.append("high_failure_impact_requires_0.9_first_pass_probability")
        evaluated.append(
            {
                "effort": effort,
                "eligible": not rejection_reasons,
                "expected_accepted_credits": round(expected_credits, 6),
                "expected_accepted_seconds": round(expected_seconds, 6),
                "expected_credit_savings_fraction": round(credit_savings, 6),
                "first_pass_probability": values["first_pass_probability"],
                "final_defect_probability": values["final_defect_probability"],
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
    return {
        "schema_version": SCHEMA_VERSION,
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
            "expected_accepted_credits": round(sol_expected_credits, 6),
            "expected_accepted_seconds": round(sol_expected_seconds, 6),
            "first_pass_probability": sol["first_pass_probability"],
            "final_defect_probability": sol["final_defect_probability"],
        },
        "coordination": coordination,
        "writer_limit": allowed_writers(request, policy, verified_parallel_evidence),
        "candidates": evaluated,
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
        "schema_version": 1,
        "task_family": "bounded-feature",
        "quality_floor": 0.8,
        "minimum_credit_savings_fraction": 0.15,
        "latency_limit_seconds": None,
        "requested_writers": 2,
        "sol_only": {
            "first_pass_probability": 0.9,
            "final_defect_probability": 0.02,
            "execution_credits": 100,
            "execution_seconds": 900,
            "recovery_credits_if_failed": 30,
            "recovery_seconds_if_failed": 300,
        },
        "coordination": {
            "sol_planning": {"credits": 8, "seconds": 90},
            "sol_review": {"credits": 10, "seconds": 120},
            "integration": {"credits": 5, "seconds": 60},
        },
        "luna_candidates": [
            {
                "effort": "medium",
                "first_pass_probability": 0.78,
                "final_defect_probability": 0.02,
                "execution_credits": 30,
                "execution_seconds": 480,
                "recovery_credits_if_failed": 45,
                "recovery_seconds_if_failed": 420,
                "failure_impact": "low",
            },
            {
                "effort": "xhigh",
                "first_pass_probability": 0.92,
                "final_defect_probability": 0.01,
                "execution_credits": 45,
                "execution_seconds": 500,
                "recovery_credits_if_failed": 35,
                "recovery_seconds_if_failed": 300,
                "failure_impact": "low",
            },
        ],
    }


def verified_parallel_evidence_from_ledger(
    ledger_path: Path, task_family: str, policy: Mapping[str, Any]
) -> dict[str, Any]:
    script = Path(__file__).with_name("evidence_ledger.py")
    spec = importlib.util.spec_from_file_location("sol_luna_evidence_ledger", script)
    if not spec or not spec.loader:
        raise PolicyError("cannot load evidence ledger validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        feedback = module.task_family_feedback(
            module.load_records(ledger_path),
            task_family=task_family,
            minimum_pairs=int(policy["parallel_expansion_minimum_pairs"]),
            minimum_credit_savings_fraction=float(policy["minimum_expected_credit_savings_fraction"]),
            minimum_first_pass_acceptance_rate=float(policy["minimum_first_pass_probability"]),
        )
    except (OSError, ValueError) as exc:
        raise PolicyError(f"cannot verify parallel evidence: {exc}") from exc
    strongest = feedback.get("strongest_cohort") or {}
    cohort = strongest.get("cohort") or {}
    sol_elapsed = float(strongest.get("median_sol_elapsed_seconds") or 0)
    luna_elapsed = float(strongest.get("median_luna_elapsed_seconds") or 0)
    reduction = float(strongest.get("median_paired_reduction_fraction") or 0)
    acceptance = strongest.get("independent_acceptance_rate") or {}
    defects = strongest.get("final_defect_rate") or {}
    policy_matches = cohort.get("policy") == policy_fingerprint(policy)
    return {
        "source": "evidence-ledger-feedback-v3",
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
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Evaluate versioned Sol-Luna routing economics.")
    result.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("template")
    sub.add_parser("fingerprint")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--input", required=True, type=Path)
    evaluate.add_argument("--ledger", type=Path)
    for name in ("review", "rework"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
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
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

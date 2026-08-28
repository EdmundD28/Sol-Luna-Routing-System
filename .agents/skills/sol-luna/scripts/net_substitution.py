#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Predict net Sol labor substitution for a bounded Luna package allocation.

This module is an estimator only.  It does not dispatch work and its credit
figures are routing weights, not authenticated plan-allowance readings.
Recovery is conservatively attributed to Sol unless an input explicitly marks
the repair or terminal recovery actor as ``LUNA``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Mapping

SCHEMA_VERSION = 1
# This is an advisory exhaustive optimizer.  Keep the frozen plan small enough
# that the subset enumeration and returned candidate ledger stay bounded.
MAX_PACKAGES = 10
IDENTIFIER = __import__("re").compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")

TOP_FIELDS = {
    "schema_version", "packages", "minimum_first_pass_probability",
    "maximum_final_defect_probability", "minimum_credit_savings_fraction",
    "minimum_sol_labor_reduction", "maximum_active_luna_writers",
}
PACKAGE_FIELDS = {
    "package_id", "depends_on", "domain_id", "baseline_sol_credits", "baseline_sol_seconds",
    "execution_credits", "execution_seconds", "first_pass_probability",
    "final_defect_probability", "repair_probability", "repair_credits", "repair_seconds",
    "terminal_failure_probability", "terminal_recovery_credits", "terminal_recovery_seconds",
    "sol_planning_credits", "sol_planning_seconds", "sol_coordination_credits",
    "sol_coordination_seconds", "sol_review_credits", "sol_review_seconds",
    "sol_integration_credits", "sol_integration_seconds", "sol_replay_probability",
    "new_context_credits", "new_context_seconds", "retained_context_credits",
    "retained_context_seconds",
    "repair_actor", "terminal_recovery_actor",
}
RECOVERY_ACTORS = {"LUNA", "SOL"}


class NetSubstitutionError(ValueError):
    """The estimator input is malformed or a derived value is unsafe."""


def _reject_constant(value: str) -> None:
    raise NetSubstitutionError(f"non-finite JSON constant is not allowed: {value}")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NetSubstitutionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise NetSubstitutionError(f"invalid JSON: {exc}") from exc


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NetSubstitutionError(f"{field} must be a JSON object")
    return value


def _fields(value: Mapping[str, Any], allowed: set[str], required: set[str], field: str) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise NetSubstitutionError(f"{field} has unknown fields: {sorted(unknown)}")
    if missing:
        raise NetSubstitutionError(f"{field} is missing required fields: {sorted(missing)}")


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise NetSubstitutionError(f"{field} must be a compact hyphen-case identifier")
    return value


def _finite(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NetSubstitutionError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise NetSubstitutionError(f"{field} must be a finite number") from None
    if not math.isfinite(result):
        raise NetSubstitutionError(f"{field} must be a finite number")
    if minimum is not None and result < minimum:
        raise NetSubstitutionError(f"{field} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise NetSubstitutionError(f"{field} must be at most {maximum}")
    return result


def _probability(value: Any, field: str) -> float:
    return _finite(value, field, minimum=0.0, maximum=1.0)


def _finite_sum(values: Any, field: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, TypeError, ValueError):
        raise NetSubstitutionError(f"{field} must remain finite") from None
    if not math.isfinite(result):
        raise NetSubstitutionError(f"{field} must remain finite")
    return result


def _product(left: float, right: float, field: str) -> float:
    try:
        result = left * right
    except (OverflowError, ValueError):
        raise NetSubstitutionError(f"{field} must remain finite") from None
    if not math.isfinite(result):
        raise NetSubstitutionError(f"{field} must remain finite")
    return result


def _fraction(numerator: float, denominator: float, field: str) -> float:
    if denominator <= 0:
        raise NetSubstitutionError(f"{field} has a non-positive denominator")
    result = numerator / denominator
    if not math.isfinite(result):
        raise NetSubstitutionError(f"{field} must remain finite")
    return result


def _package(raw: Any, index: int) -> dict[str, Any]:
    field = f"packages[{index}]"
    item = _object(raw, field)
    required_fields = PACKAGE_FIELDS - {"repair_actor", "terminal_recovery_actor"}
    _fields(item, PACKAGE_FIELDS, required_fields, field)
    package_id = _id(item["package_id"], f"{field}.package_id")
    domain_id = _id(item["domain_id"], f"{field}.domain_id")
    depends = item["depends_on"]
    if not isinstance(depends, list):
        raise NetSubstitutionError(f"{field}.depends_on must be a JSON array")
    dependencies = [_id(value, f"{field}.depends_on[{n}]") for n, value in enumerate(depends)]
    if len(dependencies) != len(set(dependencies)):
        raise NetSubstitutionError(f"{field}.depends_on contains duplicates")
    result: dict[str, Any] = {
        "package_id": package_id,
        "depends_on": sorted(dependencies),
        "domain_id": domain_id,
        "baseline_sol_credits": _finite(item["baseline_sol_credits"], f"{field}.baseline_sol_credits", minimum=0.0),
        "baseline_sol_seconds": _finite(item["baseline_sol_seconds"], f"{field}.baseline_sol_seconds", minimum=0.0),
    }
    if result["baseline_sol_credits"] <= 0 or result["baseline_sol_seconds"] <= 0:
        raise NetSubstitutionError(f"{field} baseline Sol credits and seconds must be positive")
    for name in PACKAGE_FIELDS - {"package_id", "depends_on", "domain_id", "baseline_sol_credits", "baseline_sol_seconds", "first_pass_probability", "final_defect_probability", "repair_probability", "terminal_failure_probability", "sol_replay_probability", "repair_actor", "terminal_recovery_actor"}:
        result[name] = _finite(item[name], f"{field}.{name}", minimum=0.0)
    for name in ("first_pass_probability", "final_defect_probability", "repair_probability", "terminal_failure_probability", "sol_replay_probability"):
        result[name] = _probability(item[name], f"{field}.{name}")
    for name in ("repair_actor", "terminal_recovery_actor"):
        actor = item.get(name, "SOL")
        if actor not in RECOVERY_ACTORS:
            raise NetSubstitutionError(f"{field}.{name} must be one of {sorted(RECOVERY_ACTORS)}")
        result[name] = actor
    return result


def _validate(source: Mapping[str, Any]) -> dict[str, Any]:
    _fields(source, TOP_FIELDS, TOP_FIELDS, "input")
    if type(source["schema_version"]) is not int or source["schema_version"] != SCHEMA_VERSION:
        raise NetSubstitutionError("schema_version must be integer 1")
    packages_source = source["packages"]
    if not isinstance(packages_source, list) or not packages_source:
        raise NetSubstitutionError("packages must be a non-empty JSON array")
    if len(packages_source) > MAX_PACKAGES:
        raise NetSubstitutionError(f"packages must contain at most {MAX_PACKAGES} items")
    packages = [_package(raw, index) for index, raw in enumerate(packages_source)]
    package_ids = [item["package_id"] for item in packages]
    if len(package_ids) != len(set(package_ids)):
        raise NetSubstitutionError("package_id values must be unique")
    by_id = {item["package_id"]: item for item in packages}
    for item in packages:
        missing = set(item["depends_on"]) - set(by_id)
        if missing:
            raise NetSubstitutionError(f"{item['package_id']} has unknown dependencies: {sorted(missing)}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(package_id: str) -> None:
        if package_id in visiting:
            raise NetSubstitutionError("packages contains a dependency cycle")
        if package_id in visited:
            return
        visiting.add(package_id)
        for dependency in by_id[package_id]["depends_on"]:
            visit(dependency)
        visiting.remove(package_id)
        visited.add(package_id)

    for package_id in sorted(by_id):
        visit(package_id)
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "packages": {item["package_id"]: item for item in sorted(packages, key=lambda value: value["package_id"])},
        "minimum_first_pass_probability": _probability(source["minimum_first_pass_probability"], "minimum_first_pass_probability"),
        "maximum_final_defect_probability": _probability(source["maximum_final_defect_probability"], "maximum_final_defect_probability"),
        "minimum_credit_savings_fraction": _probability(source["minimum_credit_savings_fraction"], "minimum_credit_savings_fraction"),
        "minimum_sol_labor_reduction": _probability(source["minimum_sol_labor_reduction"], "minimum_sol_labor_reduction"),
        "maximum_active_luna_writers": None,
    }
    writers = source["maximum_active_luna_writers"]
    if isinstance(writers, bool) or not isinstance(writers, int) or writers < 1:
        raise NetSubstitutionError("maximum_active_luna_writers must be a positive integer")
    if writers > min(MAX_PACKAGES, len(packages)):
        raise NetSubstitutionError(
            f"maximum_active_luna_writers must not exceed {min(MAX_PACKAGES, len(packages))}"
        )
    normalized["maximum_active_luna_writers"] = writers
    return normalized


def _safe_duration(parts: list[float], field: str) -> float:
    return _finite_sum(parts, field)


def _schedule(packages: Mapping[str, dict[str, Any]], luna_ids: set[str], requested_writers: int) -> dict[str, Any]:
    """Run deterministic two-lane list scheduling with stable Luna workers."""
    active: dict[tuple[str, int], tuple[float, str]] = {}
    worker_domains: list[str | None] = [None] * max(1, requested_writers)
    completed: set[str] = set()
    scheduled: set[str] = set()
    now = 0.0
    context_reuse = 0
    context_new = 0
    context_credits = 0.0
    context_seconds = 0.0
    package_finish: dict[str, float] = {}

    while len(completed) < len(packages):
        finished = sorted(
            ((end, actor, index, package_id) for (actor, index), (end, package_id) in active.items() if end <= now),
            key=lambda value: (value[0], value[1], value[2], value[3]),
        )
        for end, actor, index, package_id in finished:
            active.pop((actor, index), None)
            completed.add(package_id)
            package_finish[package_id] = end
        # A final completion is a valid terminal state.  Without this guard,
        # the loop falls through with no ready work and incorrectly reports a
        # scheduler deadlock after the last active task has been collected.
        if len(completed) == len(packages):
            break
        available_luna = [index for index in range(len(worker_domains)) if ("LUNA", index) not in active]
        available_sol = ("SOL", 0) not in active
        ready = sorted(
            package_id for package_id, item in packages.items()
            if package_id not in scheduled and set(item["depends_on"]).issubset(completed)
        )
        assigned = False
        for package_id in ready:
            item = packages[package_id]
            if package_id in luna_ids:
                if not available_luna:
                    continue
                same_domain = [index for index in available_luna if worker_domains[index] == item["domain_id"]]
                worker = min(same_domain or available_luna)
                available_luna.remove(worker)
                prior_domain = worker_domains[worker]
                if prior_domain == item["domain_id"]:
                    context_reuse += 1
                    load_credits = item["retained_context_credits"]
                    load_seconds = item["retained_context_seconds"]
                else:
                    context_new += 1
                    load_credits = item["new_context_credits"]
                    load_seconds = item["new_context_seconds"]
                worker_domains[worker] = item["domain_id"]
                context_credits = _finite_sum([context_credits, load_credits], "context credits")
                context_seconds = _finite_sum([context_seconds, load_seconds], "context seconds")
                duration = _safe_duration(
                    [
                        item["execution_seconds"], load_seconds,
                        _product(item["repair_probability"], item["repair_seconds"], f"{package_id} repair seconds"),
                        _product(item["terminal_failure_probability"], item["terminal_recovery_seconds"], f"{package_id} terminal seconds"),
                    ], f"{package_id} Luna duration"
                )
                end = _finite_sum([now, duration], f"{package_id} finish time")
                active[("LUNA", worker)] = (end, package_id)
            elif available_sol:
                available_sol = False
                end = _finite_sum([now, item["baseline_sol_seconds"]], f"{package_id} Sol finish time")
                active[("SOL", 0)] = (end, package_id)
            else:
                continue
            scheduled.add(package_id)
            assigned = True
        if assigned:
            continue
        if active:
            now = min(end for end, _ in active.values())
            continue
        raise NetSubstitutionError("scheduler could not make progress")
    return {
        "elapsed_seconds": now,
        "context_reuse_count": context_reuse,
        "context_new_count": context_new,
        "context_credits": context_credits,
        "context_seconds": context_seconds,
        "package_finish": package_finish,
    }


def _candidate(config: Mapping[str, Any], luna_ids: set[str], requested_writers: int) -> dict[str, Any]:
    packages = config["packages"]
    selected = [packages[package_id] for package_id in sorted(luna_ids)]
    baseline_credits = _finite_sum((item["baseline_sol_credits"] for item in packages.values()), "baseline Sol credits")
    baseline_seconds = _finite_sum((item["baseline_sol_seconds"] for item in packages.values()), "baseline Sol seconds")
    selected_baseline = _finite_sum((item["baseline_sol_credits"] for item in selected), "gross delegated baseline") if selected else 0.0
    selected_first_pass = max(0.0, 1.0 - _finite_sum((1.0 - item["first_pass_probability"] for item in selected), "first-pass aggregation")) if selected else 1.0
    selected_defect = min(1.0, _finite_sum((item["final_defect_probability"] for item in selected), "defect aggregation")) if selected else 0.0
    replay = _finite_sum((_product(item["sol_replay_probability"], item["baseline_sol_credits"], f"{item['package_id']} replay credits") for item in selected), "expected Sol replay") if selected else 0.0
    repairs = _finite_sum((_product(item["repair_probability"], item["repair_credits"], f"{item['package_id']} repair credits") for item in selected), "repair credits") if selected else 0.0
    terminal = _finite_sum((_product(item["terminal_failure_probability"], item["terminal_recovery_credits"], f"{item['package_id']} terminal recovery credits") for item in selected), "terminal recovery credits") if selected else 0.0
    overhead_credits = _finite_sum((
        item["sol_planning_credits"] + item["sol_coordination_credits"] + item["sol_review_credits"] + item["sol_integration_credits"]
        for item in selected
    ), "incremental Sol overhead") if selected else 0.0
    overhead_seconds = _finite_sum((
        item["sol_planning_seconds"] + item["sol_coordination_seconds"] + item["sol_review_seconds"] + item["sol_integration_seconds"]
        for item in selected
    ), "incremental Sol overhead seconds") if selected else 0.0
    schedule = _schedule(packages, luna_ids, requested_writers) if selected else {
        "elapsed_seconds": baseline_seconds, "context_reuse_count": 0, "context_new_count": 0,
        "context_credits": 0.0, "context_seconds": 0.0, "package_finish": {},
    }
    luna_execution = _finite_sum((item["execution_credits"] for item in selected), "Luna execution credits") if selected else 0.0
    accepted_baseline = _finite_sum((_product(item["baseline_sol_credits"], item["first_pass_probability"] * (1.0 - item["sol_replay_probability"]), f"{item['package_id']} accepted baseline") for item in selected), "expected accepted baseline") if selected else 0.0
    retained_sol = _finite_sum((item["baseline_sol_credits"] for item in packages.values() if item["package_id"] not in luna_ids), "retained Sol credits")
    recovery = _finite_sum([repairs, terminal], "expected recovery credits")
    sol_repair = _finite_sum((
        _product(item["repair_probability"], item["repair_credits"], f"{item['package_id']} repair credits")
        for item in selected if item["repair_actor"] == "SOL"
    ), "expected Sol repair credits") if selected else 0.0
    sol_terminal = _finite_sum((
        _product(item["terminal_failure_probability"], item["terminal_recovery_credits"], f"{item['package_id']} terminal recovery credits")
        for item in selected if item["terminal_recovery_actor"] == "SOL"
    ), "expected Sol terminal recovery credits") if selected else 0.0
    sol_recovery = _finite_sum([sol_repair, sol_terminal], "expected Sol recovery credits")
    expected_total = _finite_sum([retained_sol, luna_execution, schedule["context_credits"], overhead_credits, recovery, replay], "expected total credits")
    sol_labor = _finite_sum([retained_sol, overhead_credits, sol_recovery, replay], "expected Sol labor")
    net_savings = baseline_credits - expected_total
    labor_reduction = _fraction(baseline_credits - sol_labor, baseline_credits, "Sol labor reduction")
    credit_savings = _fraction(net_savings, baseline_credits, "credit savings")
    net_substitution = min(labor_reduction, credit_savings)
    selected_count = len(selected)
    reasons: list[str] = []
    if selected_first_pass < config["minimum_first_pass_probability"]:
        reasons.append("first_pass_probability_below_floor")
    if selected_defect > config["maximum_final_defect_probability"]:
        reasons.append("final_defect_probability_above_ceiling")
    if credit_savings < config["minimum_credit_savings_fraction"]:
        reasons.append("credit_savings_below_floor")
    if labor_reduction < config["minimum_sol_labor_reduction"]:
        reasons.append("sol_labor_reduction_below_floor")
    elapsed = _finite_sum([schedule["elapsed_seconds"], overhead_seconds], "expected elapsed seconds")
    if elapsed > baseline_seconds and not math.isclose(elapsed, baseline_seconds, rel_tol=1e-12, abs_tol=1e-12):
        reasons.append("elapsed_time_regresses")
    route = "SOL_LUNA" if selected else "SOL_ONLY"
    reuse_fraction = schedule["context_reuse_count"] / selected_count if selected_count else 0.0
    return {
        "route": route,
        "luna_package_ids": sorted(luna_ids),
        "active_writers": requested_writers,
        "effective_active_writers": min(requested_writers, selected_count) if selected_count else 0,
        "gross_delegated_baseline": selected_baseline,
        "expected_accepted_baseline": accepted_baseline,
        "expected_sol_replay": replay,
        "incremental_sol_overhead": overhead_credits,
        "expected_context_credits": schedule["context_credits"],
        "expected_context_seconds": schedule["context_seconds"],
        "expected_total_credits": expected_total,
        "net_route_savings": net_savings,
        "expected_sol_labor": sol_labor,
        "expected_sol_labor_reduction": labor_reduction,
        "expected_credit_savings_fraction": credit_savings,
        "structural_net_substitution": credit_savings,
        "expected_net_substitution": net_substitution,
        "expected_first_pass_probability": selected_first_pass,
        "expected_final_defect_probability": selected_defect,
        "elapsed_seconds": elapsed,
        "context_reuse_count": schedule["context_reuse_count"],
        "context_new_count": schedule["context_new_count"],
        "context_reuse_fraction": reuse_fraction,
        "eligible": not reasons,
        "ineligible_reasons": reasons,
    }


def evaluate(source: Mapping[str, Any]) -> dict[str, Any]:
    config = _validate(_object(source, "input"))
    packages = config["packages"]
    package_ids = sorted(packages)
    candidates: list[dict[str, Any]] = [_candidate(config, set(), 0)]
    for mask in range(1, 1 << len(package_ids)):
        luna_ids = {package_ids[index] for index in range(len(package_ids)) if mask & (1 << index)}
        for writers in range(1, config["maximum_active_luna_writers"] + 1):
            candidates.append(_candidate(config, luna_ids, writers))
    eligible = [item for item in candidates if item["eligible"] and item["route"] == "SOL_LUNA"]
    selected = max(
        eligible,
        key=lambda item: (
            item["expected_net_substitution"], item["net_route_savings"],
            item["expected_sol_labor_reduction"],
            -item["elapsed_seconds"], -item["active_writers"],
            tuple(reversed(item["luna_package_ids"])),
        ),
        default=None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "EVALUATED",
        "route": selected["route"] if selected else "SOL_ONLY",
        "selected_candidate": selected,
        "baseline_sol_credits_total": _finite_sum((item["baseline_sol_credits"] for item in packages.values()), "baseline Sol credits"),
        "baseline_sol_seconds_total": _finite_sum((item["baseline_sol_seconds"] for item in packages.values()), "baseline Sol seconds"),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "automatic_execution_allowed": False,
    }


def template() -> dict[str, Any]:
    def package(package_id: str, depends_on: list[str], domain_id: str, baseline: float, execution: float) -> dict[str, Any]:
        result: dict[str, Any] = {
            "package_id": package_id, "depends_on": depends_on, "domain_id": domain_id,
            "baseline_sol_credits": baseline, "baseline_sol_seconds": baseline * 10,
            "execution_credits": execution, "execution_seconds": baseline * 8,
            "first_pass_probability": 0.98, "final_defect_probability": 0.01,
            "repair_probability": 0.02, "repair_credits": 4, "repair_seconds": 30,
            "terminal_failure_probability": 0.0, "terminal_recovery_credits": 0, "terminal_recovery_seconds": 0,
            "sol_planning_credits": 1, "sol_planning_seconds": 10,
            "sol_coordination_credits": 1, "sol_coordination_seconds": 10,
            "sol_review_credits": 2, "sol_review_seconds": 20,
            "sol_integration_credits": 1, "sol_integration_seconds": 10,
            "sol_replay_probability": 0.01,
            "new_context_credits": 2, "new_context_seconds": 20,
            "retained_context_credits": 0.5, "retained_context_seconds": 5,
        }
        return result
    return {
        "schema_version": SCHEMA_VERSION,
        "packages": [package("core", [], "python", 60, 12), package("tests", ["core"], "python", 40, 8)],
        "minimum_first_pass_probability": 0.8,
        "maximum_final_defect_probability": 0.05,
        "minimum_credit_savings_fraction": 0.2,
        "minimum_sol_labor_reduction": 0.2,
        "maximum_active_luna_writers": 2,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Estimate net Sol labor substitution.")
    sub = result.add_subparsers(dest="command", required=True)
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--input", required=True)
    sub.add_parser("template")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "template":
            output = template()
        else:
            with open(args.input, encoding="utf-8") as handle:
                output = evaluate(strict_json_loads(handle.read()))
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, UnicodeError, NetSubstitutionError) as exc:
        print(f"net substitution error: {' '.join(str(exc).splitlines())}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

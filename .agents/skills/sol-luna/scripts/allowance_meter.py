#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Assess matched Codex plan-limit readings without relabelling tokens as allowance."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
LABEL = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
ROUTES = {"SOL_ONLY", "SOL_LUNA"}
LIMIT_KINDS = {"five_hour", "weekly"}
RECORD_FIELDS = {
    "schema_version",
    "pair_id",
    "task_family",
    "route",
    "route_revision",
    "arm_position",
    "batch_size",
    "independent_acceptance",
    "defects",
    "elapsed_seconds",
    "contamination_status",
    "source",
    "evidence_digest",
    "benchmark_contract_digest",
    "usage_scope_digest",
    "limits",
}
LIMIT_FIELDS = {
    "window_id",
    "before_observed_at",
    "after_observed_at",
    "window_reset_at",
    "before_remaining_percent",
    "after_remaining_percent",
    "reading_uncertainty_percentage_points",
}


class AllowanceError(ValueError):
    """A plan-limit observation is invalid or incomparable."""


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AllowanceError(f"{field} must be a JSON object")
    return value


def require_label(value: Any, field: str) -> str:
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise AllowanceError(f"{field} must be a non-sensitive hyphen-case label")
    return value


def require_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise AllowanceError(f"{field} must be a compact identifier")
    return value


def require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise AllowanceError(f"{field} must be a sha256 digest")
    return value


def require_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or value != value.strip():
        raise AllowanceError(f"{field} must be an ISO-8601 timestamp with an offset")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AllowanceError(f"{field} must be an ISO-8601 timestamp with an offset") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise AllowanceError(f"{field} must include a UTC offset")
    return result


def finite_number(value: Any, field: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise AllowanceError(f"{field} must be a finite number")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        bound = f" between {minimum} and {maximum}" if maximum is not None else f" at least {minimum}"
        raise AllowanceError(f"{field} must be{bound}")
    return result


def validate_limit(value: Any, field: str) -> dict[str, Any]:
    source = require_object(value, field)
    unsupported = set(source) - LIMIT_FIELDS
    missing = LIMIT_FIELDS - set(source)
    if unsupported:
        raise AllowanceError(f"{field} has unsupported fields: {sorted(unsupported)}")
    if missing:
        raise AllowanceError(f"{field} is missing fields: {sorted(missing)}")
    before = finite_number(source["before_remaining_percent"], f"{field}.before_remaining_percent", maximum=100)
    after = finite_number(source["after_remaining_percent"], f"{field}.after_remaining_percent", maximum=100)
    uncertainty = finite_number(
        source["reading_uncertainty_percentage_points"],
        f"{field}.reading_uncertainty_percentage_points",
        maximum=10,
    )
    if after > before:
        raise AllowanceError(f"{field} remaining allowance increased; a reset or inconsistent reading occurred")
    before_at = require_timestamp(source["before_observed_at"], f"{field}.before_observed_at")
    after_at = require_timestamp(source["after_observed_at"], f"{field}.after_observed_at")
    reset_at = require_timestamp(source["window_reset_at"], f"{field}.window_reset_at")
    if not before_at < after_at:
        raise AllowanceError(f"{field} observations must be strictly ordered")
    if after_at >= reset_at:
        raise AllowanceError(f"{field} after observation crosses or reaches the reset boundary")
    return {
        "window_id": require_label(source["window_id"], f"{field}.window_id"),
        "before_observed_at": before_at.isoformat(),
        "after_observed_at": after_at.isoformat(),
        "window_reset_at": reset_at.isoformat(),
        "before_remaining_percent": before,
        "after_remaining_percent": after,
        "reading_uncertainty_percentage_points": uncertainty,
    }


def validate_record(value: Any) -> dict[str, Any]:
    source = require_object(value, "record")
    unsupported = set(source) - RECORD_FIELDS
    missing = RECORD_FIELDS - set(source)
    if unsupported:
        raise AllowanceError(f"record has unsupported fields: {sorted(unsupported)}")
    if missing:
        raise AllowanceError(f"record is missing fields: {sorted(missing)}")
    if source["schema_version"] != SCHEMA_VERSION:
        raise AllowanceError("unsupported schema_version")
    route = source["route"]
    if route not in ROUTES:
        raise AllowanceError("route must be SOL_ONLY or SOL_LUNA")
    arm_position = source["arm_position"]
    if isinstance(arm_position, bool) or not isinstance(arm_position, int) or arm_position not in {1, 2}:
        raise AllowanceError("arm_position must be 1 or 2")
    batch_size = source["batch_size"]
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise AllowanceError("batch_size must be a positive integer")
    acceptance = source["independent_acceptance"]
    if acceptance not in {"PASSED", "FAILED"}:
        raise AllowanceError("independent_acceptance must be PASSED or FAILED")
    defects = source["defects"]
    if isinstance(defects, bool) or not isinstance(defects, int) or defects < 0:
        raise AllowanceError("defects must be a non-negative integer")
    if source["contamination_status"] != "NO_OTHER_SHARED_USAGE_OBSERVED":
        raise AllowanceError("contamination_status must confirm no other shared usage was observed")
    if source["source"] != "chatgpt-usage-dashboard-v1":
        raise AllowanceError("source must be chatgpt-usage-dashboard-v1")
    raw_limits = require_object(source["limits"], "limits")
    if set(raw_limits) != LIMIT_KINDS:
        raise AllowanceError("limits must contain exactly five_hour and weekly")
    return {
        "schema_version": SCHEMA_VERSION,
        "pair_id": require_label(source["pair_id"], "pair_id"),
        "task_family": require_label(source["task_family"], "task_family"),
        "route": route,
        "route_revision": require_identifier(source["route_revision"], "route_revision"),
        "arm_position": arm_position,
        "batch_size": batch_size,
        "independent_acceptance": acceptance,
        "defects": defects,
        "elapsed_seconds": finite_number(source["elapsed_seconds"], "elapsed_seconds"),
        "contamination_status": source["contamination_status"],
        "source": source["source"],
        "evidence_digest": require_digest(source["evidence_digest"], "evidence_digest"),
        "benchmark_contract_digest": require_digest(
            source["benchmark_contract_digest"], "benchmark_contract_digest"
        ),
        "usage_scope_digest": require_digest(source["usage_scope_digest"], "usage_scope_digest"),
        "limits": {kind: validate_limit(raw_limits[kind], f"limits.{kind}") for kind in sorted(LIMIT_KINDS)},
    }


def consumption_interval(limit: Mapping[str, Any]) -> dict[str, float]:
    displayed = float(limit["before_remaining_percent"]) - float(limit["after_remaining_percent"])
    uncertainty = 2 * float(limit["reading_uncertainty_percentage_points"])
    return {
        "displayed_consumption_percentage_points": displayed,
        "minimum_consumption_percentage_points": max(0.0, displayed - uncertainty),
        "maximum_consumption_percentage_points": min(100.0, displayed + uncertainty),
    }


def advantage_interval(sol: Mapping[str, float], luna: Mapping[str, float]) -> dict[str, Any]:
    sol_displayed = sol["displayed_consumption_percentage_points"]
    luna_displayed = luna["displayed_consumption_percentage_points"]
    sol_min = sol["minimum_consumption_percentage_points"]
    sol_max = sol["maximum_consumption_percentage_points"]
    luna_min = luna["minimum_consumption_percentage_points"]
    luna_max = luna["maximum_consumption_percentage_points"]
    return {
        "displayed_advantage_multiple": None if luna_displayed <= 0 else sol_displayed / luna_displayed,
        "conservative_advantage_multiple_lower_bound": None if luna_max <= 0 else sol_min / luna_max,
        "conservative_advantage_multiple_upper_bound": None if luna_min <= 0 else sol_max / luna_min,
        "upper_bound_unresolved": luna_min <= 0,
    }


def sum_intervals(items: list[Mapping[str, float]]) -> dict[str, float]:
    fields = (
        "displayed_consumption_percentage_points",
        "minimum_consumption_percentage_points",
        "maximum_consumption_percentage_points",
    )
    return {field: sum(float(item[field]) for item in items) for field in fields}


def assess(
    records: list[Mapping[str, Any]],
    *,
    minimum_advantage_multiple: float,
    minimum_pairs: int = 4,
) -> dict[str, Any]:
    floor = finite_number(minimum_advantage_multiple, "minimum_advantage_multiple", minimum=1)
    if isinstance(minimum_pairs, bool) or not isinstance(minimum_pairs, int) or minimum_pairs < 2:
        raise AllowanceError("minimum_pairs must be an integer of at least 2")
    normalized = [validate_record(record) for record in records]
    if len({record["benchmark_contract_digest"] for record in normalized}) > 1:
        raise AllowanceError("benchmark_contract_digest differs across campaign")
    if len({record["usage_scope_digest"] for record in normalized}) > 1:
        raise AllowanceError("usage_scope_digest differs across campaign")
    if len({record["task_family"] for record in normalized}) > 1:
        raise AllowanceError("task_family differs across campaign")
    if len({record["batch_size"] for record in normalized}) > 1:
        raise AllowanceError("batch_size differs across campaign")
    for route in ROUTES:
        if len({record["route_revision"] for record in normalized if record["route"] == route}) > 1:
            raise AllowanceError(f"{route} route_revision differs across campaign")
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for record in normalized:
        pair = grouped.setdefault(record["pair_id"], {})
        if record["route"] in pair:
            raise AllowanceError(f"duplicate {record['pair_id']}:{record['route']}")
        pair[record["route"]] = record
    results: list[dict[str, Any]] = []
    for pair_id in sorted(grouped):
        arms = grouped[pair_id]
        if set(arms) != ROUTES:
            raise AllowanceError(f"{pair_id} must contain exactly one arm for each route")
        sol = arms["SOL_ONLY"]
        luna = arms["SOL_LUNA"]
        for field in ("task_family", "batch_size", "benchmark_contract_digest", "usage_scope_digest"):
            if sol[field] != luna[field]:
                raise AllowanceError(f"{pair_id} {field} differs between arms")
        if {sol["arm_position"], luna["arm_position"]} != {1, 2}:
            raise AllowanceError(f"{pair_id} must contain arm positions 1 and 2")
        first = sol if sol["arm_position"] == 1 else luna
        second = luna if first is sol else sol
        intervals: dict[str, dict[str, Any]] = {}
        for kind in sorted(LIMIT_KINDS):
            sol_limit = sol["limits"][kind]
            luna_limit = luna["limits"][kind]
            if sol_limit["window_id"] != luna_limit["window_id"]:
                raise AllowanceError(f"{pair_id} {kind} window_id differs between arms")
            if sol_limit["window_reset_at"] != luna_limit["window_reset_at"]:
                raise AllowanceError(f"{pair_id} {kind} window_reset_at differs between arms")
            first_after = first["limits"][kind]["after_remaining_percent"]
            second_before = second["limits"][kind]["before_remaining_percent"]
            if first_after != second_before:
                raise AllowanceError(f"{pair_id} {kind} arm readings are not continuous")
            first_after_at = datetime.fromisoformat(first["limits"][kind]["after_observed_at"])
            second_before_at = datetime.fromisoformat(second["limits"][kind]["before_observed_at"])
            if first_after_at > second_before_at:
                raise AllowanceError(f"{pair_id} {kind} arm observation times overlap")
            sol_interval = consumption_interval(sol_limit)
            luna_interval = consumption_interval(luna_limit)
            intervals[kind] = {
                "sol_only": sol_interval,
                "sol_luna": luna_interval,
                "advantage": advantage_interval(sol_interval, luna_interval),
            }
        quality_passed = (
            sol["independent_acceptance"] == "PASSED"
            and luna["independent_acceptance"] == "PASSED"
            and luna["defects"] <= sol["defects"]
        )
        elapsed_improved = luna["elapsed_seconds"] < sol["elapsed_seconds"]
        five_hour_lower = intervals["five_hour"]["advantage"][
            "conservative_advantage_multiple_lower_bound"
        ]
        allowance_improved = five_hour_lower is not None and five_hour_lower >= floor
        reasons: list[str] = []
        if not quality_passed:
            reasons.append("quality_gate_failed")
        if five_hour_lower is None:
            reasons.append("allowance_resolution_too_coarse")
        elif not allowance_improved:
            reasons.append("conservative_allowance_advantage_below_floor")
        if not elapsed_improved:
            reasons.append("elapsed_not_strictly_faster")
        results.append(
            {
                "pair_id": pair_id,
                "quality_passed": quality_passed,
                "allowance_improved": allowance_improved,
                "elapsed_improved": elapsed_improved,
                "first_route": first["route"],
                "limits": intervals,
                "status": "PASS" if not reasons else "HOLD",
                "reasons": reasons,
            }
        )
    campaign_limits: dict[str, Any] = {}
    for kind in sorted(LIMIT_KINDS):
        sol_total = sum_intervals([item["limits"][kind]["sol_only"] for item in results])
        luna_total = sum_intervals([item["limits"][kind]["sol_luna"] for item in results])
        campaign_limits[kind] = {
            "sol_only": sol_total,
            "sol_luna": luna_total,
            "advantage": advantage_interval(sol_total, luna_total),
        }
    first_routes = [item["first_route"] for item in results]
    counterbalanced = (
        "SOL_ONLY" in first_routes
        and "SOL_LUNA" in first_routes
        and abs(first_routes.count("SOL_ONLY") - first_routes.count("SOL_LUNA")) <= 1
    )
    enough_pairs = len(results) >= minimum_pairs
    quality_passed = bool(results) and all(item["quality_passed"] for item in results)
    total_sol_elapsed = sum(
        record["elapsed_seconds"] for record in normalized if record["route"] == "SOL_ONLY"
    )
    total_luna_elapsed = sum(
        record["elapsed_seconds"] for record in normalized if record["route"] == "SOL_LUNA"
    )
    elapsed_improved = total_luna_elapsed < total_sol_elapsed
    primary_lower = campaign_limits["five_hour"]["advantage"][
        "conservative_advantage_multiple_lower_bound"
    ]
    allowance_improved = primary_lower is not None and primary_lower >= floor
    weekly_upper = campaign_limits["weekly"]["advantage"][
        "conservative_advantage_multiple_upper_bound"
    ]
    weekly_contradicts = weekly_upper is not None and weekly_upper < 1
    campaign_reasons: list[str] = []
    if not enough_pairs:
        campaign_reasons.append("insufficient_predeclared_pairs")
    if not counterbalanced:
        campaign_reasons.append("arm_order_not_counterbalanced")
    if not quality_passed:
        campaign_reasons.append("quality_gate_failed")
    if primary_lower is None:
        campaign_reasons.append("five_hour_resolution_too_coarse")
    elif not allowance_improved:
        campaign_reasons.append("five_hour_advantage_below_floor")
    if weekly_contradicts:
        campaign_reasons.append("weekly_meter_contradicts_direction")
    if not elapsed_improved:
        campaign_reasons.append("elapsed_not_strictly_faster")
    return {
        "schema_version": SCHEMA_VERSION,
        "measurement": "chatgpt_plan_limit_remaining_percentage_points",
        "primary_limit": "five_hour",
        "secondary_limit": "weekly",
        "minimum_advantage_multiple": floor,
        "minimum_pairs": minimum_pairs,
        "pairs": results,
        "campaign": {
            "pair_count": len(results),
            "counterbalanced": counterbalanced,
            "quality_passed": quality_passed,
            "allowance_improved": allowance_improved,
            "elapsed_improved": elapsed_improved,
            "elapsed_seconds": {"sol_only": total_sol_elapsed, "sol_luna": total_luna_elapsed},
            "limits": campaign_limits,
            "status": "PASS" if not campaign_reasons else "HOLD",
            "reasons": campaign_reasons,
        },
        "campaign_status": "PASS" if not campaign_reasons else "HOLD",
        "automatic_routing_allowed": False,
        "boundaries": [
            "Five-hour percentage-point consumption is the primary user-visible allowance measure.",
            "Weekly percentage-point consumption is a separate corroborating measure and is never added to the five-hour measure.",
            "Within one unchanged plan window, a route ratio on the same meter cancels the undisclosed window capacity.",
            "Dashboard percentages are account-plan observations, not purchased-credit receipts.",
            "The uncertainty interval covers display resolution but not unobserved concurrent shared usage.",
            "Raw diagnostic tokens, purchased-credit estimates, and API dollars are not substituted for plan-limit consumption.",
        ],
    }


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowanceError(f"cannot load JSON: {exc}") from exc


def template() -> dict[str, Any]:
    digest = "sha256:" + "0" * 64
    limit = {
        "window_id": "replace-with-window-id",
        "before_observed_at": "2026-08-28T00:10:00+10:00",
        "after_observed_at": "2026-08-28T00:20:00+10:00",
        "window_reset_at": "2026-08-28T02:52:00+10:00",
        "before_remaining_percent": 100,
        "after_remaining_percent": 90,
        "reading_uncertainty_percentage_points": 1,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "pair_id": "pair-001",
        "task_family": "bounded-feature",
        "route": "SOL_LUNA",
        "route_revision": "v0.1.1",
        "arm_position": 2,
        "batch_size": 1,
        "independent_acceptance": "PASSED",
        "defects": 0,
        "elapsed_seconds": 1,
        "contamination_status": "NO_OTHER_SHARED_USAGE_OBSERVED",
        "source": "chatgpt-usage-dashboard-v1",
        "evidence_digest": digest,
        "benchmark_contract_digest": digest,
        "usage_scope_digest": digest,
        "limits": {"five_hour": dict(limit), "weekly": dict(limit)},
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Assess matched ChatGPT/Codex plan-limit readings.")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("template")
    validate = sub.add_parser("validate")
    validate.add_argument("--input", required=True, type=Path)
    assess_command = sub.add_parser("assess")
    assess_command.add_argument("--input", required=True, type=Path, help="JSON array of matched records")
    assess_command.add_argument("--minimum-advantage-multiple", type=float, default=10.0)
    assess_command.add_argument("--minimum-pairs", type=int, default=4)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "template":
            output = template()
        elif args.command == "validate":
            output = validate_record(load_json(args.input))
        else:
            source = load_json(args.input)
            if not isinstance(source, list):
                raise AllowanceError("assessment input must be a JSON array")
            output = assess(
                source,
                minimum_advantage_multiple=args.minimum_advantage_multiple,
                minimum_pairs=args.minimum_pairs,
            )
    except AllowanceError as exc:
        print(f"allowance meter error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

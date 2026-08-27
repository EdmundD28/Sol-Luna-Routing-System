#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Freeze and assess matched Sol-only versus Sol-Luna evaluation campaigns."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

import evidence_ledger


SCHEMA_VERSION = 1
LABEL = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
PLAN_FIELDS = {"schema_version", "campaign_id", "task_family", "policy_version", "policy_fingerprint", "pairs"}
PAIR_FIELDS = {
    "pair_id",
    "starting_candidate_ref",
    "task_spec_digest",
    "acceptance_suite_id",
    "acceptance_suite_digest",
}


class EvalError(ValueError):
    """A matched-evaluation plan or result is not comparable."""


def require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvalError(f"{field} must be a JSON object")
    return value


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise EvalError(f"{field} must be a non-empty single-line string")
    return value.strip()


def require_label(value: Any, field: str) -> str:
    result = require_string(value, field)
    if not LABEL.fullmatch(result):
        raise EvalError(f"{field} must be a non-sensitive hyphen-case label")
    return result


def require_digest(value: Any, field: str) -> str:
    result = require_string(value, field)
    if not DIGEST.fullmatch(result):
        raise EvalError(f"{field} must be sha256 followed by 64 lowercase hexadecimal characters")
    return result


def plan_fingerprint(plan: Mapping[str, Any]) -> str:
    rendered = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(rendered).hexdigest()


def validate_plan(source: Mapping[str, Any]) -> dict[str, Any]:
    source = require_object(source, "plan")
    unsupported = set(source) - PLAN_FIELDS
    if unsupported:
        raise EvalError(f"unsupported plan fields: {sorted(unsupported)}")
    if source.get("schema_version") != SCHEMA_VERSION:
        raise EvalError("unsupported plan schema_version")
    result = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": require_label(source.get("campaign_id"), "campaign_id"),
        "task_family": require_label(source.get("task_family"), "task_family"),
        "policy_version": require_string(source.get("policy_version"), "policy_version"),
        "policy_fingerprint": require_digest(source.get("policy_fingerprint"), "policy_fingerprint"),
        "pairs": [],
    }
    pairs = source.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise EvalError("pairs must be a non-empty JSON array")
    seen: set[str] = set()
    for index, raw in enumerate(pairs):
        pair = require_object(raw, f"pairs[{index}]")
        unsupported_pair = set(pair) - PAIR_FIELDS
        if unsupported_pair:
            raise EvalError(f"pairs[{index}] has unsupported fields: {sorted(unsupported_pair)}")
        normalized = {
            "pair_id": require_label(pair.get("pair_id"), f"pairs[{index}].pair_id"),
            "starting_candidate_ref": require_string(
                pair.get("starting_candidate_ref"), f"pairs[{index}].starting_candidate_ref"
            ),
            "task_spec_digest": require_digest(pair.get("task_spec_digest"), f"pairs[{index}].task_spec_digest"),
            "acceptance_suite_id": require_label(
                pair.get("acceptance_suite_id"), f"pairs[{index}].acceptance_suite_id"
            ),
            "acceptance_suite_digest": require_digest(
                pair.get("acceptance_suite_digest"), f"pairs[{index}].acceptance_suite_digest"
            ),
        }
        if normalized["pair_id"] in seen:
            raise EvalError(f"duplicate pair_id: {normalized['pair_id']}")
        if len(normalized["starting_candidate_ref"]) > 128:
            raise EvalError("starting_candidate_ref must be at most 128 characters")
        seen.add(normalized["pair_id"])
        result["pairs"].append(normalized)
    return result


def load_plan(path: Path) -> dict[str, Any]:
    try:
        return validate_plan(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"cannot load evaluation plan: {exc}") from exc


def run_sheet(plan: Mapping[str, Any]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for pair_index, pair in enumerate(plan["pairs"]):
        route_order = ("SOL_ONLY", "SOL_LUNA") if pair_index % 2 == 0 else ("SOL_LUNA", "SOL_ONLY")
        for route in route_order:
            runs.append(
                {
                    "campaign_id": plan["campaign_id"],
                    "pair_id": pair["pair_id"],
                    "route": route,
                    "task_family": plan["task_family"],
                    "starting_candidate_ref": pair["starting_candidate_ref"],
                    "task_spec_digest": pair["task_spec_digest"],
                    "acceptance_suite_id": pair["acceptance_suite_id"],
                    "acceptance_suite_digest": pair["acceptance_suite_digest"],
                    "policy_version": plan["policy_version"],
                    "policy_fingerprint": plan["policy_fingerprint"],
                    "evaluation_mode": "MATCHED",
                    "execution_order": len(runs) + 1,
                    "required_isolation": (
                        "single formal checkout; verify a clean tree and restore starting_candidate_ref "
                        "before each arm; do not clone, copy, or create a worktree"
                    ),
                    "required_external_evidence_location": (
                        "store the campaign ledger and dashboard captures outside the repository"
                    ),
                    "required_allowance_measurement": (
                        "capture settled five-hour and weekly remaining percentages immediately before "
                        "and after each arm in the unchanged account windows"
                    ),
                    "required_acceptance": (
                        "after both tested agents return, run the same frozen independent suite outside "
                        "both route intervals and report referee cost separately"
                    ),
                    "required_runtime_identity": (
                        "host-observed gpt-5.6-sol"
                        if route == "SOL_ONLY"
                        else "host-observed gpt-5.6-sol coordinator and gpt-5.6-luna worker"
                    ),
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_fingerprint": plan_fingerprint(plan),
        "automatic_model_execution_allowed": False,
        "runs": runs,
    }


def assess(plan: Mapping[str, Any], records: list[Mapping[str, Any]], *, minimum_pairs: int) -> dict[str, Any]:
    expected = {pair["pair_id"]: pair for pair in plan["pairs"]}
    selected = [record for record in records if record.get("campaign_id") == plan["campaign_id"]]
    mismatches: list[str] = []
    observed_arms: set[tuple[str, str]] = set()
    for record in selected:
        pair_id = str(record.get("pair_id") or "")
        if pair_id not in expected:
            mismatches.append(f"unexpected pair_id {pair_id}")
            continue
        pair = expected[pair_id]
        comparisons = {
            "task_family": plan["task_family"],
            "policy_version": plan["policy_version"],
            "policy_fingerprint": plan["policy_fingerprint"],
            "starting_candidate_ref": pair["starting_candidate_ref"],
            "task_spec_digest": pair["task_spec_digest"],
            "acceptance_suite_id": pair["acceptance_suite_id"],
            "acceptance_suite_digest": pair["acceptance_suite_digest"],
            "evaluation_mode": "MATCHED",
        }
        for field, expected_value in comparisons.items():
            if record.get(field) != expected_value:
                mismatches.append(f"{pair_id}:{record.get('route')} {field} does not match frozen plan")
        route = str(record.get("route"))
        if record.get("observed_sol_model") != "gpt-5.6-sol":
            mismatches.append(f"{pair_id}:{route} observed_sol_model is not host-verified gpt-5.6-sol")
        if route == "SOL_LUNA" and record.get("observed_luna_model") != "gpt-5.6-luna":
            mismatches.append(f"{pair_id}:{route} observed_luna_model is not host-verified gpt-5.6-luna")
        if route == "SOL_ONLY" and record.get("observed_luna_model"):
            mismatches.append(f"{pair_id}:{route} unexpectedly reports a Luna runtime")
        if not record.get("runtime_identity_source"):
            mismatches.append(f"{pair_id}:{route} runtime_identity_source is missing")
        if route in evidence_ledger.ROUTES:
            observed_arms.add((pair_id, route))
    missing_arms = [
        f"{pair_id}:{route}"
        for pair_id in sorted(expected)
        for route in sorted(evidence_ledger.ROUTES)
        if (pair_id, route) not in observed_arms
    ]
    if mismatches:
        return {
            "status": "invalid_comparison",
            "plan_fingerprint": plan_fingerprint(plan),
            "mismatches": sorted(mismatches),
            "missing_arms": missing_arms,
            "automatic_routing_allowed": False,
        }
    status = evidence_ledger.evidence_status(
        selected,
        task_family=plan["task_family"],
        minimum_pairs=minimum_pairs,
    )
    return {
        "status": "incomplete_campaign" if missing_arms else status["status"],
        "plan_fingerprint": plan_fingerprint(plan),
        "missing_arms": missing_arms,
        "evidence": status,
        "automatic_routing_allowed": False,
    }


def template() -> dict[str, Any]:
    placeholder = "sha256:" + "0" * 64
    return {
        "schema_version": 1,
        "campaign_id": "bounded-feature-v1",
        "task_family": "bounded-feature",
        "policy_version": "1.2.0",
        "policy_fingerprint": placeholder,
        "pairs": [
            {
                "pair_id": "pair-001",
                "starting_candidate_ref": "git:replace-with-starting-commit",
                "task_spec_digest": placeholder,
                "acceptance_suite_id": "hidden-v1",
                "acceptance_suite_digest": placeholder,
            }
        ],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Prepare and assess a frozen matched Sol-Luna campaign.")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("template")
    for name in ("validate", "run-sheet"):
        command = sub.add_parser(name)
        command.add_argument("--plan", required=True, type=Path)
    assess_command = sub.add_parser("assess")
    assess_command.add_argument("--plan", required=True, type=Path)
    assess_command.add_argument("--ledger", required=True, type=Path)
    assess_command.add_argument("--minimum-pairs", type=int, default=evidence_ledger.MIN_MATCHED_PAIRS)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "template":
            document = template()
        else:
            plan = load_plan(args.plan)
            if args.command == "validate":
                document = {
                    "status": "valid",
                    "pairs": len(plan["pairs"]),
                    "plan_fingerprint": plan_fingerprint(plan),
                }
            elif args.command == "run-sheet":
                document = run_sheet(plan)
            else:
                document = assess(
                    plan,
                    evidence_ledger.load_records(args.ledger),
                    minimum_pairs=args.minimum_pairs,
                )
    except (OSError, json.JSONDecodeError, EvalError, evidence_ledger.LedgerError) as exc:
        print(f"matched evaluation error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

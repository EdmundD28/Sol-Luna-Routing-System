#!/usr/bin/env python3
"""Validate and summarize an opt-in, redacted Sol-Luna evidence ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
MIN_MATCHED_PAIRS = 5
ROUTES = {"SOL_ONLY", "SOL_LUNA"}
OUTCOMES = {"ACCEPTED", "FAILED", "BLOCKED", "CANCELLED_OR_OBSOLETE", "NOT_ASSESSED"}
INDEPENDENT_RESULTS = {"PASSED", "FAILED", "NOT_RUN"}
FAILURE_CLASSES = {
    "runtime",
    "ownership_or_scope",
    "permission_or_authority",
    "verification",
    "dependency_or_external",
    "model_identity",
}
CREDIT_KINDS = {"exact", "estimated", "displayed_allowance_delta"}
ALLOWED_FIELDS = {
    "schema_version",
    "recorded_at",
    "run_ref",
    "task_family",
    "pair_id",
    "route",
    "outcome",
    "independent_acceptance",
    "acceptance_suite_id",
    "final_candidate_ref",
    "first_pass_accepted",
    "repair_rounds",
    "defects",
    "failure_class",
    "blocker",
    "extra_repair_basis",
    "new_evidence_ref",
    "runtime_receipt_ref",
    "elapsed_seconds",
    "total_tokens",
    "token_source",
    "token_uncertainty",
    "credit_value",
    "credit_kind",
    "credit_source",
    "credit_uncertainty",
    "note",
}
REQUIRED_FIELDS = {
    "run_ref",
    "task_family",
    "route",
    "outcome",
    "independent_acceptance",
    "repair_rounds",
    "defects",
}
PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:\\|/Users/|/home/|\\\\[^\\]+\\)")
LABEL = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")


class LedgerError(ValueError):
    """The ledger or a record violates the evidence contract."""


def redacted_ref(value: str) -> str:
    if value.startswith("redacted:run:"):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"redacted:run:{digest}"


def require_string(record: Mapping[str, Any], field: str, *, required: bool = False) -> str:
    value = record.get(field)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise LedgerError(f"{field} must be a non-empty string" if required else f"{field} must be a string")
    if "\n" in value or "\r" in value:
        raise LedgerError(f"{field} must be single-line")
    return value.strip()


def require_label(record: Mapping[str, Any], field: str, *, required: bool = False) -> str:
    value = require_string(record, field, required=required)
    if value and not LABEL.fullmatch(value):
        raise LedgerError(f"{field} must be a non-sensitive hyphen-case label")
    return value


def non_negative_number(value: Any, field: str, *, integer: bool = False) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise LedgerError(f"{field} must be a finite non-negative number or null")
    if integer and not isinstance(value, int):
        raise LedgerError(f"{field} must be a non-negative integer or null")
    return value


def safe_summary(record: Mapping[str, Any], field: str, *, required: bool = False) -> str:
    value = require_string(record, field, required=required)
    if len(value) > 240:
        raise LedgerError(f"{field} must be at most 240 characters")
    if value and PRIVATE_PATH.search(value):
        raise LedgerError(f"{field} must not contain a private filesystem path")
    return value


def validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise LedgerError("recorded_at must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LedgerError("recorded_at must be an ISO-8601 string") from exc
    if parsed.tzinfo is None:
        raise LedgerError("recorded_at must include a timezone")
    return value


def validate_record(
    source: Mapping[str, Any], *, normalize_run_ref: bool = False, now: datetime | None = None
) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise LedgerError("record must be a JSON object")
    unsupported = set(source) - ALLOWED_FIELDS
    if unsupported:
        raise LedgerError(f"unsupported record fields: {sorted(unsupported)}")
    missing = REQUIRED_FIELDS - set(source)
    if missing:
        raise LedgerError(f"record missing fields: {sorted(missing)}")

    record = dict(source)
    schema_version = record.get("schema_version", SCHEMA_VERSION)
    if schema_version != SCHEMA_VERSION:
        raise LedgerError(f"unsupported schema_version: {schema_version}")
    record["schema_version"] = SCHEMA_VERSION

    run_ref = require_string(record, "run_ref", required=True)
    if PRIVATE_PATH.search(run_ref):
        run_ref = redacted_ref(run_ref)
    elif normalize_run_ref:
        run_ref = redacted_ref(run_ref)
    record["run_ref"] = run_ref
    record["task_family"] = require_label(record, "task_family", required=True)
    pair_id = require_label(record, "pair_id")
    if pair_id:
        record["pair_id"] = pair_id

    route = record.get("route")
    if route not in ROUTES:
        raise LedgerError(f"route must be one of {sorted(ROUTES)}")
    outcome = record.get("outcome")
    if outcome not in OUTCOMES:
        raise LedgerError(f"outcome must be one of {sorted(OUTCOMES)}")
    independent = record.get("independent_acceptance")
    if independent not in INDEPENDENT_RESULTS:
        raise LedgerError(f"independent_acceptance must be one of {sorted(INDEPENDENT_RESULTS)}")

    repairs = non_negative_number(record.get("repair_rounds"), "repair_rounds", integer=True)
    defects = non_negative_number(record.get("defects"), "defects", integer=True)
    if repairs is None or defects is None:
        raise LedgerError("repair_rounds and defects may not be null")
    if repairs > 1:
        record["extra_repair_basis"] = safe_summary(record, "extra_repair_basis", required=True)
        record["new_evidence_ref"] = require_string(record, "new_evidence_ref", required=True)

    failure_class = require_string(record, "failure_class")
    if failure_class and failure_class not in FAILURE_CLASSES:
        raise LedgerError(f"failure_class must be one of {sorted(FAILURE_CLASSES)}")
    if outcome in {"FAILED", "BLOCKED"} and not failure_class:
        raise LedgerError(f"{outcome} records require failure_class")
    if outcome == "BLOCKED":
        record["blocker"] = safe_summary(record, "blocker", required=True)

    suite = require_label(record, "acceptance_suite_id")
    candidate = require_string(record, "final_candidate_ref")
    if candidate and (len(candidate) > 128 or PRIVATE_PATH.search(candidate)):
        raise LedgerError("final_candidate_ref must be a short non-path identifier")
    if outcome == "ACCEPTED":
        if independent != "PASSED":
            raise LedgerError("ACCEPTED requires independent_acceptance PASSED")
        if not suite or not candidate:
            raise LedgerError("ACCEPTED requires acceptance_suite_id and final_candidate_ref")
    if suite:
        record["acceptance_suite_id"] = suite
    if "first_pass_accepted" in record and not isinstance(record["first_pass_accepted"], bool):
        raise LedgerError("first_pass_accepted must be boolean")

    non_negative_number(record.get("elapsed_seconds"), "elapsed_seconds")
    total_tokens = non_negative_number(record.get("total_tokens"), "total_tokens", integer=True)
    if total_tokens is not None:
        record["token_source"] = safe_summary(record, "token_source", required=True)
        record["token_uncertainty"] = safe_summary(record, "token_uncertainty", required=True)
    credit_value = non_negative_number(record.get("credit_value"), "credit_value")
    if credit_value is not None:
        if record.get("credit_kind") not in CREDIT_KINDS:
            raise LedgerError(f"credit_kind must be one of {sorted(CREDIT_KINDS)}")
        record["credit_source"] = safe_summary(record, "credit_source", required=True)
        record["credit_uncertainty"] = safe_summary(record, "credit_uncertainty", required=True)

    for field in ("runtime_receipt_ref", "new_evidence_ref"):
        if field in record:
            value = require_string(record, field)
            if value and (len(value) > 128 or PRIVATE_PATH.search(value)):
                raise LedgerError(f"{field} must be a short non-path identifier")
    if "note" in record:
        record["note"] = safe_summary(record, "note")

    if "recorded_at" in record:
        record["recorded_at"] = validate_timestamp(record["recorded_at"])
    else:
        timestamp = now or datetime.now(timezone.utc)
        record["recorded_at"] = timestamp.astimezone(timezone.utc).isoformat()
    return record


def append_record(path: Path, source: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    record = validate_record(source, normalize_run_ref=True, now=now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            source = json.loads(line)
            records.append(validate_record(source))
        except (json.JSONDecodeError, LedgerError) as exc:
            raise LedgerError(f"invalid ledger line {line_number}: {exc}") from exc
    return records


def comparable_metric(left: Mapping[str, Any], right: Mapping[str, Any]) -> str | None:
    if (
        left.get("total_tokens") is not None
        and right.get("total_tokens") is not None
        and left.get("token_source") == right.get("token_source")
    ):
        return "total_tokens"
    if (
        left.get("credit_value") is not None
        and right.get("credit_value") is not None
        and left.get("credit_kind") == right.get("credit_kind")
        and left.get("credit_source") == right.get("credit_source")
    ):
        return "credit_value"
    return None


def clean_accepted(record: Mapping[str, Any]) -> bool:
    return (
        record.get("outcome") == "ACCEPTED"
        and record.get("independent_acceptance") == "PASSED"
        and record.get("defects") == 0
        and bool(record.get("acceptance_suite_id"))
        and bool(record.get("final_candidate_ref"))
    )


def median(values: list[float | int]) -> float | None:
    return round(float(statistics.median(values)), 6) if values else None


def evidence_status(
    records: list[Mapping[str, Any]], *, task_family: str, minimum_pairs: int = MIN_MATCHED_PAIRS
) -> dict[str, Any]:
    if minimum_pairs < MIN_MATCHED_PAIRS:
        raise LedgerError(f"minimum_pairs cannot be lower than {MIN_MATCHED_PAIRS}")
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("task_family") == task_family and record.get("pair_id"):
            grouped[str(record["pair_id"])].append(record)

    qualified: list[dict[str, Any]] = []
    rejected_reasons: dict[str, int] = defaultdict(int)
    for pair_id, items in sorted(grouped.items()):
        if len(items) != 2:
            rejected_reasons["pair_does_not_contain_exactly_two_runs"] += 1
            continue
        by_route = {str(item.get("route")): item for item in items}
        if set(by_route) != ROUTES:
            rejected_reasons["pair_does_not_cover_both_routes"] += 1
            continue
        left = by_route["SOL_ONLY"]
        right = by_route["SOL_LUNA"]
        if not clean_accepted(left) or not clean_accepted(right):
            rejected_reasons["pair_is_not_clean_and_independently_accepted"] += 1
            continue
        if left.get("acceptance_suite_id") != right.get("acceptance_suite_id"):
            rejected_reasons["acceptance_suite_mismatch"] += 1
            continue
        metric = comparable_metric(left, right)
        if not metric:
            rejected_reasons["no_comparable_cost_measurement"] += 1
            continue
        qualified.append({"pair_id": pair_id, "metric": metric, "routes": by_route})

    summaries: dict[str, dict[str, Any]] = {}
    for route in sorted(ROUTES):
        route_records = [pair["routes"][route] for pair in qualified]
        summaries[route] = {
            "runs": len(route_records),
            "median_elapsed_seconds": median(
                [float(item["elapsed_seconds"]) for item in route_records if item.get("elapsed_seconds") is not None]
            ),
            "median_total_tokens": median(
                [int(item["total_tokens"]) for item in route_records if item.get("total_tokens") is not None]
            ),
            "median_credit_value": median(
                [float(item["credit_value"]) for item in route_records if item.get("credit_value") is not None]
            ),
            "median_repair_rounds": median([int(item["repair_rounds"]) for item in route_records]),
        }

    count = len(qualified)
    status = "eligible_for_human_review" if count >= minimum_pairs else "insufficient_evidence"
    return {
        "schema_version": SCHEMA_VERSION,
        "task_family": task_family,
        "status": status,
        "automatic_routing_allowed": False,
        "qualified_matched_pairs": count,
        "minimum_required": minimum_pairs,
        "rejected_pair_reasons": dict(sorted(rejected_reasons.items())),
        "route_summaries": summaries,
        "next_action": (
            "Review the matched evidence manually; this tool never changes routing."
            if status == "eligible_for_human_review"
            else "Collect more clean matched accepted pairs before reviewing a routing-policy change."
        ),
    }


def template() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_ref": "replace-with-local-run-id; it will be hashed",
        "task_family": "bounded-feature",
        "pair_id": "pair-001",
        "route": "SOL_ONLY",
        "outcome": "NOT_ASSESSED",
        "independent_acceptance": "NOT_RUN",
        "acceptance_suite_id": "",
        "final_candidate_ref": "",
        "first_pass_accepted": False,
        "repair_rounds": 0,
        "defects": 0,
        "elapsed_seconds": None,
        "total_tokens": None,
        "token_source": "",
        "token_uncertainty": "",
        "credit_value": None,
        "credit_kind": "estimated",
        "credit_source": "",
        "credit_uncertainty": "",
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage an explicit, redacted Sol-Luna evidence ledger.")
    sub = result.add_subparsers(dest="command", required=True)

    sub.add_parser("template", help="Print a fill-in record template.")
    append = sub.add_parser("append", help="Validate one JSON record and append it as redacted JSONL.")
    append.add_argument("--ledger", required=True, type=Path)
    append.add_argument("--record", required=True, type=Path)

    validate = sub.add_parser("validate", help="Validate every record in an existing ledger.")
    validate.add_argument("--ledger", required=True, type=Path)

    status = sub.add_parser("status", help="Assess whether matched evidence is ready for human review.")
    status.add_argument("--ledger", required=True, type=Path)
    status.add_argument("--task-family", required=True)
    status.add_argument("--minimum-pairs", type=int, default=MIN_MATCHED_PAIRS)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "template":
            document = template()
        elif args.command == "append":
            source = json.loads(args.record.read_text(encoding="utf-8"))
            document = append_record(args.ledger, source)
        elif args.command == "validate":
            records = load_records(args.ledger)
            document = {"schema_version": SCHEMA_VERSION, "status": "valid", "records": len(records)}
        else:
            task_family = str(args.task_family)
            if not LABEL.fullmatch(task_family):
                raise LedgerError("task_family must be a non-sensitive hyphen-case label")
            document = evidence_status(
                load_records(args.ledger),
                task_family=task_family,
                minimum_pairs=args.minimum_pairs,
            )
    except (OSError, json.JSONDecodeError, LedgerError) as exc:
        print(f"evidence ledger error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

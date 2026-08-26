#!/usr/bin/env python3
"""Validate, atomically persist, and cohort Sol-Luna delivery evidence."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import statistics
import sys
import tempfile
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


SCHEMA_VERSION = 3
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
PHASES = {"sol_planning", "sol_execution", "luna_execution", "sol_review", "repair", "integration"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
REVIEW_DEPTHS = {"TARGETED", "STANDARD", "DEEP", "NOT_APPLICABLE"}
ALLOWED_FIELDS = {
    "schema_version",
    "record_id",
    "recorded_at",
    "run_ref",
    "campaign_id",
    "task_family",
    "pair_id",
    "route",
    "outcome",
    "independent_acceptance",
    "acceptance_suite_id",
    "acceptance_suite_digest",
    "task_spec_digest",
    "starting_candidate_ref",
    "final_candidate_ref",
    "policy_version",
    "policy_fingerprint",
    "luna_effort",
    "writer_count",
    "review_depth",
    "evaluation_mode",
    "first_pass_accepted",
    "repair_rounds",
    "defects",
    "failure_class",
    "blocker",
    "extra_repair_basis",
    "new_evidence_ref",
    "runtime_receipt_ref",
    "observed_sol_model",
    "observed_luna_model",
    "runtime_identity_source",
    "runtime_identity_uncertainty",
    "elapsed_seconds",
    "total_tokens",
    "token_source",
    "token_uncertainty",
    "credit_value",
    "credit_kind",
    "credit_source",
    "credit_uncertainty",
    "phase_elapsed_seconds",
    "phase_tokens",
    "phase_credits",
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
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


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


def require_digest(record: Mapping[str, Any], field: str, *, required: bool = False) -> str:
    value = require_string(record, field, required=required)
    if value and not DIGEST.fullmatch(value):
        raise LedgerError(f"{field} must be sha256 followed by 64 lowercase hexadecimal characters")
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


def validate_phase_map(value: Any, field: str, *, integer: bool = False) -> dict[str, float | int]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LedgerError(f"{field} must be a JSON object")
    unsupported = set(value) - PHASES
    if unsupported:
        raise LedgerError(f"{field} has unsupported phases: {sorted(unsupported)}")
    normalized: dict[str, float | int] = {}
    for phase, amount in value.items():
        checked = non_negative_number(amount, f"{field}.{phase}", integer=integer)
        if checked is None:
            raise LedgerError(f"{field}.{phase} may not be null")
        normalized[str(phase)] = checked
    return normalized


def record_id(record: Mapping[str, Any]) -> str:
    identity = {
        "run_ref": record.get("run_ref"),
        "route": record.get("route"),
        "pair_id": record.get("pair_id"),
        "final_candidate_ref": record.get("final_candidate_ref"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"record:{digest}"


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
    incoming_schema = source.get("schema_version", SCHEMA_VERSION)
    if incoming_schema not in {1, 2, SCHEMA_VERSION}:
        raise LedgerError(f"unsupported schema_version: {incoming_schema}")

    record = dict(source)
    record["schema_version"] = SCHEMA_VERSION
    run_ref = require_string(record, "run_ref", required=True)
    if PRIVATE_PATH.search(run_ref) or normalize_run_ref:
        run_ref = redacted_ref(run_ref)
    record["run_ref"] = run_ref
    record["task_family"] = require_label(record, "task_family", required=True)
    campaign_id = require_label(record, "campaign_id")
    if campaign_id:
        record["campaign_id"] = campaign_id
    pair_id = require_label(record, "pair_id")
    if pair_id:
        record["pair_id"] = pair_id

    if record.get("route") not in ROUTES:
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
    if outcome == "FAILED" and independent != "FAILED":
        raise LedgerError("FAILED requires independent_acceptance FAILED")
    if suite:
        record["acceptance_suite_id"] = suite
    for field in ("acceptance_suite_digest", "task_spec_digest", "policy_fingerprint"):
        digest = require_digest(record, field)
        if digest:
            record[field] = digest
    for field in ("policy_version", "starting_candidate_ref"):
        value = require_string(record, field)
        if value and (len(value) > 128 or PRIVATE_PATH.search(value)):
            raise LedgerError(f"{field} must be a short non-path identifier")

    mode = require_string(record, "evaluation_mode")
    if mode and mode not in {"ROUTINE", "MATCHED"}:
        raise LedgerError("evaluation_mode must be ROUTINE or MATCHED")
    if mode == "MATCHED":
        for field in (
            "pair_id",
            "campaign_id",
            "acceptance_suite_digest",
            "task_spec_digest",
            "starting_candidate_ref",
            "policy_version",
            "policy_fingerprint",
        ):
            if not record.get(field):
                raise LedgerError(f"MATCHED records require {field}")
        if "first_pass_accepted" not in record:
            raise LedgerError("MATCHED records require first_pass_accepted")
        if record.get("elapsed_seconds") is None:
            raise LedgerError("MATCHED records require elapsed_seconds")
        observed_sol = require_string(record, "observed_sol_model", required=True)
        if observed_sol != "gpt-5.6-sol":
            raise LedgerError("MATCHED records require observed_sol_model gpt-5.6-sol")
        record["observed_sol_model"] = observed_sol
        observed_luna = require_string(record, "observed_luna_model")
        if record["route"] == "SOL_LUNA":
            if observed_luna != "gpt-5.6-luna":
                raise LedgerError("matched SOL_LUNA records require observed_luna_model gpt-5.6-luna")
            record["observed_luna_model"] = observed_luna
        elif observed_luna:
            raise LedgerError("matched SOL_ONLY records must not report observed_luna_model")
        record["runtime_identity_source"] = safe_summary(
            record, "runtime_identity_source", required=True
        )
        record["runtime_identity_uncertainty"] = safe_summary(
            record, "runtime_identity_uncertainty", required=True
        )

    if "first_pass_accepted" in record and not isinstance(record["first_pass_accepted"], bool):
        raise LedgerError("first_pass_accepted must be boolean")
    effort = require_string(record, "luna_effort")
    if effort and effort not in EFFORTS:
        raise LedgerError(f"luna_effort must be one of {sorted(EFFORTS)}")
    if record["route"] == "SOL_LUNA" and mode == "MATCHED" and not effort:
        raise LedgerError("matched SOL_LUNA records require luna_effort")
    if "writer_count" in record:
        non_negative_number(record["writer_count"], "writer_count", integer=True)
    depth = require_string(record, "review_depth")
    if depth and depth not in REVIEW_DEPTHS:
        raise LedgerError(f"review_depth must be one of {sorted(REVIEW_DEPTHS)}")

    elapsed_seconds = non_negative_number(record.get("elapsed_seconds"), "elapsed_seconds")
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

    phase_elapsed = validate_phase_map(record.get("phase_elapsed_seconds"), "phase_elapsed_seconds")
    phase_tokens = validate_phase_map(record.get("phase_tokens"), "phase_tokens", integer=True)
    phase_credits = validate_phase_map(record.get("phase_credits"), "phase_credits")
    if phase_elapsed:
        record["phase_elapsed_seconds"] = phase_elapsed
    if phase_tokens:
        record["phase_tokens"] = phase_tokens
    if phase_credits:
        record["phase_credits"] = phase_credits
    if mode == "MATCHED" and not phase_elapsed:
        raise LedgerError("MATCHED records require phase_elapsed_seconds")
    if mode == "MATCHED":
        execution_phase = "sol_execution" if record["route"] == "SOL_ONLY" else "luna_execution"
        if execution_phase not in phase_elapsed:
            raise LedgerError(f"matched {record['route']} records require {execution_phase} elapsed evidence")
        if total_tokens is not None and phase_tokens and execution_phase not in phase_tokens:
            raise LedgerError(f"matched {record['route']} token phases require {execution_phase}")
        if credit_value is not None and phase_credits and execution_phase not in phase_credits:
            raise LedgerError(f"matched {record['route']} credit phases require {execution_phase}")
    if elapsed_seconds is not None and phase_elapsed and any(
        float(value) > float(elapsed_seconds) + 1e-6 for value in phase_elapsed.values()
    ):
        raise LedgerError("no individual phase duration may exceed elapsed_seconds")
    if total_tokens is not None and phase_tokens and sum(phase_tokens.values()) != total_tokens:
        raise LedgerError("phase_tokens must sum to total_tokens")
    if credit_value is not None and phase_credits and not math.isclose(
        float(sum(phase_credits.values())), float(credit_value), rel_tol=1e-9, abs_tol=1e-9
    ):
        raise LedgerError("phase_credits must sum to credit_value")

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
    expected_id = record_id(record)
    supplied_id = require_string(record, "record_id")
    if supplied_id and supplied_id != expected_id:
        raise LedgerError("record_id does not match the canonical record identity")
    record["record_id"] = expected_id
    return record


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(validate_record(json.loads(line)))
        except (json.JSONDecodeError, LedgerError) as exc:
            raise LedgerError(f"invalid ledger line {line_number}: {exc}") from exc
    return records


@contextlib.contextmanager
def ledger_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    key = str(lock_path.resolve())
    with _LOCKS_GUARD:
        process_lock = _LOCKS.setdefault(key, threading.Lock())
    with process_lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_records(path: Path, records: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n")
    temp_path = Path(handle.name)
    try:
        with handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def append_record(path: Path, source: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    record = validate_record(source, normalize_run_ref=True, now=now)
    with ledger_lock(path):
        records = load_records(path)
        if any(existing["record_id"] == record["record_id"] for existing in records):
            raise LedgerError(f"duplicate record_id: {record['record_id']}")
        atomic_write_records(path, [*records, record])
    return record


def comparable_metric(left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[str, str] | None:
    if (
        left.get("credit_value") is not None
        and right.get("credit_value") is not None
        and left.get("credit_kind") == right.get("credit_kind")
        and left.get("credit_source") == right.get("credit_source")
        and left.get("credit_uncertainty") == right.get("credit_uncertainty")
    ):
        return "credit_value", f"{left.get('credit_kind')}:{left.get('credit_source')}"
    if (
        left.get("total_tokens") is not None
        and right.get("total_tokens") is not None
        and left.get("token_source") == right.get("token_source")
        and left.get("token_uncertainty") == right.get("token_uncertainty")
    ):
        return "total_tokens", str(left.get("token_source"))
    return None


def fully_assessed(record: Mapping[str, Any]) -> bool:
    return (
        record.get("outcome") in {"ACCEPTED", "FAILED"}
        and record.get("independent_acceptance") in {"PASSED", "FAILED"}
        and bool(record.get("acceptance_suite_id"))
    )


def median(values: list[float | int]) -> float | None:
    return round(float(statistics.median(values)), 6) if values else None


def cohort_identity(left: Mapping[str, Any], metric: tuple[str, str]) -> tuple[str, ...]:
    return (
        str(left.get("acceptance_suite_digest") or left.get("acceptance_suite_id")),
        str(left.get("policy_fingerprint") or left.get("policy_version") or "legacy-policy"),
        metric[0],
        metric[1],
    )


def evidence_status(
    records: list[Mapping[str, Any]],
    *,
    task_family: str,
    minimum_pairs: int = MIN_MATCHED_PAIRS,
    minimum_credit_savings_fraction: float = 0.15,
    minimum_first_pass_acceptance_rate: float = 0.80,
) -> dict[str, Any]:
    if minimum_pairs < MIN_MATCHED_PAIRS:
        raise LedgerError(f"minimum_pairs cannot be lower than {MIN_MATCHED_PAIRS}")
    if not 0 <= minimum_credit_savings_fraction <= 1:
        raise LedgerError("minimum_credit_savings_fraction must be between 0 and 1")
    if not 0 <= minimum_first_pass_acceptance_rate <= 1:
        raise LedgerError("minimum_first_pass_acceptance_rate must be between 0 and 1")
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("task_family") == task_family and record.get("pair_id"):
            grouped[(str(record.get("campaign_id") or "legacy-campaign"), str(record["pair_id"]))].append(record)

    cohorts: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    rejected: dict[str, int] = defaultdict(int)
    for (campaign_id, pair_id), items in sorted(grouped.items()):
        if len(items) != 2:
            rejected["pair_does_not_contain_exactly_two_runs"] += 1
            continue
        by_route = {str(item.get("route")): item for item in items}
        if set(by_route) != ROUTES:
            rejected["pair_does_not_cover_both_routes"] += 1
            continue
        left, right = by_route["SOL_ONLY"], by_route["SOL_LUNA"]
        if not fully_assessed(left) or not fully_assessed(right):
            rejected["pair_is_not_fully_assessed"] += 1
            continue
        matched_fields = (
            "acceptance_suite_id",
            "acceptance_suite_digest",
            "task_spec_digest",
            "starting_candidate_ref",
            "policy_version",
            "policy_fingerprint",
        )
        mismatch = next((field for field in matched_fields if left.get(field) != right.get(field)), None)
        if mismatch:
            rejected[f"{mismatch}_mismatch"] += 1
            continue
        metric = comparable_metric(left, right)
        if not metric:
            rejected["no_comparable_cost_measurement"] += 1
            continue
        cohorts[cohort_identity(left, metric)].append(
            {
                "campaign_id": campaign_id,
                "pair_id": pair_id,
                "metric": metric[0],
                "source": metric[1],
                "routes": by_route,
            }
        )

    cohort_outputs: list[dict[str, Any]] = []
    for identity, pairs in sorted(cohorts.items()):
        metric = pairs[0]["metric"]
        sol_values = [float(pair["routes"]["SOL_ONLY"][metric]) for pair in pairs]
        luna_values = [float(pair["routes"]["SOL_LUNA"][metric]) for pair in pairs]
        paired_savings = [1 - luna / sol for sol, luna in zip(sol_values, luna_values) if sol > 0]
        elapsed_deltas = [
            float(pair["routes"]["SOL_LUNA"].get("elapsed_seconds", 0))
            - float(pair["routes"]["SOL_ONLY"].get("elapsed_seconds", 0))
            for pair in pairs
            if pair["routes"]["SOL_LUNA"].get("elapsed_seconds") is not None
            and pair["routes"]["SOL_ONLY"].get("elapsed_seconds") is not None
        ]
        sol_elapsed_values = [float(pair["routes"]["SOL_ONLY"]["elapsed_seconds"]) for pair in pairs]
        luna_elapsed_values = [float(pair["routes"]["SOL_LUNA"]["elapsed_seconds"]) for pair in pairs]
        first_pass = {
            route: sum(bool(pair["routes"][route].get("first_pass_accepted")) for pair in pairs) / len(pairs)
            for route in sorted(ROUTES)
        }
        acceptance_rates = {
            route: sum(
                pair["routes"][route].get("outcome") == "ACCEPTED"
                and pair["routes"][route].get("independent_acceptance") == "PASSED"
                for pair in pairs
            )
            / len(pairs)
            for route in sorted(ROUTES)
        }
        defect_rates = {
            route: sum(float(pair["routes"][route].get("defects", 0)) > 0 for pair in pairs) / len(pairs)
            for route in sorted(ROUTES)
        }
        coordination_shares: list[float] = []
        for pair in pairs:
            record = pair["routes"]["SOL_LUNA"]
            phase = record.get("phase_credits") if metric == "credit_value" else record.get("phase_tokens")
            if phase and float(record[metric]) > 0:
                coordination_shares.append(
                    (float(phase.get("sol_planning", 0)) + float(phase.get("sol_review", 0)))
                    / float(record[metric])
                )
        median_savings = median(paired_savings)
        median_elapsed_delta = median(elapsed_deltas)
        credible_credit_metric = metric == "credit_value" and pairs[0]["source"].startswith("exact:")
        gates = {
            "minimum_pairs": len(pairs) >= minimum_pairs,
            "independent_acceptance_equal_or_better": acceptance_rates["SOL_LUNA"]
            >= acceptance_rates["SOL_ONLY"],
            "credible_credit_reduction": credible_credit_metric
            and median_savings is not None
            and median_savings >= minimum_credit_savings_fraction,
            "no_elapsed_regression": median_elapsed_delta is not None and median_elapsed_delta <= 0,
            "no_final_defect_regression": defect_rates["SOL_LUNA"] <= defect_rates["SOL_ONLY"],
            "first_pass_acceptance_is_high_enough": first_pass["SOL_LUNA"]
            >= minimum_first_pass_acceptance_rate,
            "sol_planning_and_review_are_minority": bool(coordination_shares)
            and median(coordination_shares) < 0.5,
        }
        cohort_outputs.append(
            {
                "cohort": {
                    "acceptance_suite": identity[0],
                    "policy": identity[1],
                    "metric": identity[2],
                    "measurement_source": identity[3],
                },
                "qualified_matched_pairs": len(pairs),
                "observed_luna_efforts": sorted(
                    {
                        str(pair["routes"]["SOL_LUNA"].get("luna_effort"))
                        for pair in pairs
                        if pair["routes"]["SOL_LUNA"].get("luna_effort")
                    }
                ),
                "median_paired_reduction_fraction": median_savings,
                "median_elapsed_delta_seconds": median_elapsed_delta,
                "median_sol_elapsed_seconds": median(sol_elapsed_values),
                "median_luna_elapsed_seconds": median(luna_elapsed_values),
                "independent_acceptance_rate": acceptance_rates,
                "final_defect_rate": defect_rates,
                "first_pass_acceptance_rate": first_pass,
                "median_sol_coordination_share": median(coordination_shares),
                "success_gates": gates,
                "policy_change_eligible": all(gates.values()),
            }
        )

    reviewable = [cohort for cohort in cohort_outputs if cohort["qualified_matched_pairs"] >= minimum_pairs]
    return {
        "schema_version": SCHEMA_VERSION,
        "task_family": task_family,
        "status": "eligible_for_human_review" if reviewable else "insufficient_evidence",
        "automatic_routing_allowed": False,
        "qualified_matched_pairs": sum(item["qualified_matched_pairs"] for item in cohort_outputs),
        "largest_cohort_pairs": max((item["qualified_matched_pairs"] for item in cohort_outputs), default=0),
        "minimum_required_per_cohort": minimum_pairs,
        "rejected_pair_reasons": dict(sorted(rejected.items())),
        "cohorts": cohort_outputs,
        "next_action": (
            "Review each qualifying cohort manually; this tool never changes routing."
            if reviewable
            else "Collect more clean matched pairs in one exact cohort before reviewing a policy change."
        ),
    }


def task_family_feedback(
    records: list[Mapping[str, Any]],
    *,
    task_family: str,
    minimum_pairs: int = MIN_MATCHED_PAIRS,
    minimum_credit_savings_fraction: float = 0.15,
    minimum_first_pass_acceptance_rate: float = 0.80,
) -> dict[str, Any]:
    """Convert matched evidence into an advisory, fail-closed routing posture."""
    status = evidence_status(
        records,
        task_family=task_family,
        minimum_pairs=minimum_pairs,
        minimum_credit_savings_fraction=minimum_credit_savings_fraction,
        minimum_first_pass_acceptance_rate=minimum_first_pass_acceptance_rate,
    )
    cohorts = list(status["cohorts"])
    eligible = [cohort for cohort in cohorts if cohort["policy_change_eligible"]]
    strongest = max(
        cohorts,
        key=lambda cohort: (
            bool(cohort["policy_change_eligible"]),
            int(cohort["qualified_matched_pairs"]),
        ),
        default=None,
    )
    supported_efforts = sorted(
        {
            effort
            for cohort in eligible
            for effort in cohort.get("observed_luna_efforts", [])
        }
    )
    if eligible:
        posture = "SOL_LUNA_POLICY_REVIEW_CANDIDATE"
        reasons = [
            "at least one exact matched cohort passes every configured quality, credit, and elapsed gate"
        ]
    elif strongest:
        posture = "HOLD_SOL_ONLY"
        reasons = [
            gate
            for gate, passed in strongest["success_gates"].items()
            if not passed
        ]
    else:
        posture = "HOLD_SOL_ONLY"
        reasons = ["no comparable matched cohort exists for this task family"]
    return {
        "schema_version": SCHEMA_VERSION,
        "task_family": task_family,
        "posture": posture,
        "supported_luna_efforts": supported_efforts,
        "automatic_routing_allowed": False,
        "human_policy_review_required": bool(eligible),
        "reasons": reasons,
        "strongest_cohort": strongest,
        "evidence_status": status["status"],
        "next_action": (
            "A human may review the passing cohort before changing task-family routing priors."
            if eligible
            else "Keep this task family in Sol unless concrete task evidence independently justifies delegation."
        ),
    }


def template() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_ref": "replace-with-local-run-id; it will be hashed",
        "campaign_id": "routine-local",
        "task_family": "bounded-feature",
        "pair_id": "pair-001",
        "route": "SOL_ONLY",
        "evaluation_mode": "ROUTINE",
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
        "observed_sol_model": "",
        "observed_luna_model": "",
        "runtime_identity_source": "",
        "runtime_identity_uncertainty": "",
        "phase_elapsed_seconds": {},
        "phase_tokens": {},
        "phase_credits": {},
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage an explicit, atomic Sol-Luna evidence ledger.")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("template")
    append = sub.add_parser("append")
    append.add_argument("--ledger", required=True, type=Path)
    append.add_argument("--record", required=True, type=Path)
    validate = sub.add_parser("validate")
    validate.add_argument("--ledger", required=True, type=Path)
    for name in ("status", "feedback"):
        command = sub.add_parser(name)
        command.add_argument("--ledger", required=True, type=Path)
        command.add_argument("--task-family", required=True)
        command.add_argument("--minimum-pairs", type=int, default=MIN_MATCHED_PAIRS)
        command.add_argument("--minimum-credit-savings-fraction", type=float, default=0.15)
        command.add_argument("--minimum-first-pass-acceptance-rate", type=float, default=0.80)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "template":
            document = template()
        elif args.command == "append":
            document = append_record(args.ledger, json.loads(args.record.read_text(encoding="utf-8")))
        elif args.command == "validate":
            records = load_records(args.ledger)
            document = {"schema_version": SCHEMA_VERSION, "status": "valid", "records": len(records)}
        elif args.command in {"status", "feedback"}:
            task_family = str(args.task_family)
            if not LABEL.fullmatch(task_family):
                raise LedgerError("task_family must be a non-sensitive hyphen-case label")
            evaluator = evidence_status if args.command == "status" else task_family_feedback
            document = evaluator(
                load_records(args.ledger),
                task_family=task_family,
                minimum_pairs=args.minimum_pairs,
                minimum_credit_savings_fraction=args.minimum_credit_savings_fraction,
                minimum_first_pass_acceptance_rate=args.minimum_first_pass_acceptance_rate,
            )
    except (OSError, json.JSONDecodeError, LedgerError) as exc:
        print(f"evidence ledger error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

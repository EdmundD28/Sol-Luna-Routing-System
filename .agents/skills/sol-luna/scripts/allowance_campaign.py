#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Record and assess counterbalanced subscription-allowance campaigns."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping


SCHEMA_VERSION = 3
ROUTES = {"SOL_ONLY", "SOL_LUNA"}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
LABEL = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
ZERO_PREVIOUS = "0" * 64
LIMIT_KINDS = ("five_hour", "weekly")
DEFAULT_STARTING_COMMIT_SHA = "0" * 40
DEFAULT_TASK_DIGEST = "sha256:" + "0" * 64
DEFAULT_TARGET_ELAPSED_MIN_SECONDS = 1200
DEFAULT_TARGET_ELAPSED_MAX_SECONDS = 2400
DEFAULT_METER_RESOLUTION = 1.0
DEFAULT_SOL_LUNA_WORKER_COUNT = 1
DEFAULT_SOL_LUNA_ACTIVE_LUNA_WRITER_COUNT = 1
TOPOLOGIES = {
    "sol_only": "single-controller-no-workers",
    "sol_luna": "single-controller-one-active-luna",
}

INIT_FIELDS = {
    "schema_version", "event_type", "previous_event_sha256", "contract_digest",
    "usage_scope_digest", "task_family", "batch_size",
    "reading_uncertainty_percentage_points", "first_routes", "windows",
    "starting_commit_sha", "task_spec_digest", "acceptance_suite_digest",
    "sol_only_topology", "sol_luna_topology", "target_elapsed_min_seconds",
    "target_elapsed_max_seconds", "meter_resolution_percentage_points",
    "repair_policy_digest", "sol_luna_worker_count",
    "sol_luna_active_luna_writer_count",
}
BEGIN_FIELDS = {
    "schema_version", "event_type", "previous_event_sha256", "pair_id", "route",
    "route_revision", "arm_position", "observed_at", "remaining_percent",
    "start_evidence_digest", "excluded_since_previous_end_percentage_points",
}
END_FIELDS = {
    "schema_version", "event_type", "previous_event_sha256", "pair_id", "route",
    "observed_at", "remaining_percent", "end_evidence_digest", "elapsed_seconds",
    "candidate_digest",
}
ACCEPTANCE_FIELDS = {
    "schema_version", "event_type", "previous_event_sha256", "pair_id", "route",
    "candidate_digest", "acceptance_command_digest", "acceptance_result_digest",
    "acceptance_suite_digest", "observed_at", "acceptance_elapsed_seconds",
    "independent_acceptance", "defects",
}
WINDOW_FIELDS = {"window_id", "reset_at"}


class CampaignError(ValueError):
    """The campaign command or ledger violates the frozen contract."""


def _load_allowance_meter() -> Any:
    path = Path(__file__).with_name("allowance_meter.py")
    spec = importlib.util.spec_from_file_location("sol_luna_allowance_meter", path)
    if spec is None or spec.loader is None:
        raise CampaignError("cannot load allowance_meter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ALLOWANCE_METER = _load_allowance_meter()


def canonical_bytes(value: Mapping[str, Any] | list[Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def require_exact_fields(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CampaignError(f"{name} must be a JSON object")
    unsupported = set(value) - fields
    missing = fields - set(value)
    if unsupported:
        raise CampaignError(f"{name} has unsupported fields: {sorted(unsupported)}")
    if missing:
        raise CampaignError(f"{name} is missing fields: {sorted(missing)}")
    return value


def require_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise CampaignError(f"{name} must be a lowercase sha256 digest")
    return value


def require_commit_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise CampaignError(f"{name} must be a 40- or 64-character lowercase commit SHA")
    return value


def require_label(value: Any, name: str) -> str:
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise CampaignError(f"{name} must be a non-sensitive hyphen-case label")
    return value


def require_identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise CampaignError(f"{name} must be a compact identifier")
    return value


def require_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CampaignError(f"{name} must be an ISO-8601 timestamp with an offset")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CampaignError(f"{name} must be an ISO-8601 timestamp with an offset") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CampaignError(f"{name} must include a UTC offset")
    return result


def finite_number(value: Any, name: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CampaignError(f"{name} must be a finite number")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        raise CampaignError(f"{name} is outside the permitted range")
    return result


def positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CampaignError(f"{name} must be a positive integer")
    return value


def normalize_first_routes(value: Any) -> list[str]:
    if isinstance(value, str):
        routes = value.split(",")
    elif isinstance(value, list):
        routes = value
    else:
        raise CampaignError("first_routes must be a comma-separated string or JSON array")
    if len(routes) < 2 or any(route not in ROUTES for route in routes):
        raise CampaignError("first_routes must contain at least two valid routes")
    if set(routes) != ROUTES or abs(routes.count("SOL_ONLY") - routes.count("SOL_LUNA")) > 1:
        raise CampaignError("first_routes must contain both routes and be counterbalanced")
    return list(routes)


def _opposite(route: str) -> str:
    return "SOL_LUNA" if route == "SOL_ONLY" else "SOL_ONLY"


def route_sequence(first_routes: list[str]) -> list[str]:
    return [route for first in first_routes for route in (first, _opposite(first))]


def combined_evidence_digest(start_digest: str, end_digest: str) -> str:
    return sha256_bytes(canonical_bytes([start_digest, end_digest]))


def acceptance_event_digest(event: Mapping[str, Any]) -> str:
    """Digest the bound acceptance payload, excluding the mutable chain link."""
    payload = {key: value for key, value in event.items() if key != "previous_event_sha256"}
    return sha256_bytes(canonical_bytes(payload))


def _event_previous(event_bytes: bytes) -> str:
    return hashlib.sha256(event_bytes).hexdigest()


def _validate_init(event: Mapping[str, Any]) -> dict[str, Any]:
    source = require_exact_fields(event, INIT_FIELDS, "init event")
    if (
        not isinstance(source["schema_version"], int)
        or isinstance(source["schema_version"], bool)
        or source["schema_version"] != SCHEMA_VERSION
        or source["event_type"] != "init"
    ):
        raise CampaignError("ledger must start with a supported init event")
    if source["previous_event_sha256"] != ZERO_PREVIOUS:
        raise CampaignError("init event must use the zero previous digest")
    batch_size = positive_integer(source["batch_size"], "batch_size")
    uncertainty = finite_number(
        source["reading_uncertainty_percentage_points"],
        "reading_uncertainty_percentage_points", maximum=10,
    )
    first_routes = normalize_first_routes(source["first_routes"])
    starting_commit_sha = require_commit_sha(source["starting_commit_sha"], "starting_commit_sha")
    frozen_digests = {
        field: require_digest(source[field], field)
        for field in ("task_spec_digest", "acceptance_suite_digest", "repair_policy_digest")
    }
    sol_only_topology = require_label(source["sol_only_topology"], "sol_only_topology")
    sol_luna_topology = require_label(source["sol_luna_topology"], "sol_luna_topology")
    sol_luna_worker_count = positive_integer(
        source["sol_luna_worker_count"], "sol_luna_worker_count"
    )
    sol_luna_active_luna_writer_count = positive_integer(
        source["sol_luna_active_luna_writer_count"],
        "sol_luna_active_luna_writer_count",
    )
    if sol_luna_active_luna_writer_count > sol_luna_worker_count:
        raise CampaignError(
            "sol_luna_active_luna_writer_count cannot exceed sol_luna_worker_count"
        )
    target_min = source["target_elapsed_min_seconds"]
    target_max = source["target_elapsed_max_seconds"]
    if (
        isinstance(target_min, bool) or not isinstance(target_min, int) or target_min < 0
        or isinstance(target_max, bool) or not isinstance(target_max, int) or target_max <= target_min
    ):
        raise CampaignError("target elapsed bounds must be ordered non-negative integers")
    meter_resolution = finite_number(
        source["meter_resolution_percentage_points"],
        "meter_resolution_percentage_points", minimum=1e-9, maximum=100,
    )
    windows = require_exact_fields(source["windows"], set(LIMIT_KINDS), "windows")
    normalized_windows: dict[str, dict[str, str]] = {}
    for kind in LIMIT_KINDS:
        window = require_exact_fields(windows[kind], WINDOW_FIELDS, f"windows.{kind}")
        reset = require_timestamp(window["reset_at"], f"windows.{kind}.reset_at")
        normalized_windows[kind] = {
            "window_id": require_label(window["window_id"], f"windows.{kind}.window_id"),
            "reset_at": reset.isoformat(),
        }
    return {
        "contract_digest": require_digest(source["contract_digest"], "contract_digest"),
        "usage_scope_digest": require_digest(source["usage_scope_digest"], "usage_scope_digest"),
        "task_family": require_label(source["task_family"], "task_family"),
        "batch_size": batch_size,
        "reading_uncertainty_percentage_points": uncertainty,
        "first_routes": first_routes,
        "starting_commit_sha": starting_commit_sha,
        **frozen_digests,
        "sol_only_topology": sol_only_topology,
        "sol_luna_topology": sol_luna_topology,
        "sol_luna_worker_count": sol_luna_worker_count,
        "sol_luna_active_luna_writer_count": sol_luna_active_luna_writer_count,
        "target_elapsed_min_seconds": target_min,
        "target_elapsed_max_seconds": target_max,
        "meter_resolution_percentage_points": meter_resolution,
        "windows": normalized_windows,
    }


def _new_state(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "config": config,
        "records": [],
        "active": None,
        "pending_end": None,
        "last_end": None,
        "route_revisions": {},
        "excluded": {kind: 0.0 for kind in LIMIT_KINDS},
    }


def _expected_arm(state: Mapping[str, Any]) -> tuple[int, str, str, int]:
    index = len(state["records"])
    sequence = route_sequence(state["config"]["first_routes"])
    if index >= len(sequence):
        raise CampaignError("all pre-registered campaign arms are complete")
    pair_number = index // 2 + 1
    return index, sequence[index], f"pair-{pair_number:03d}", index % 2 + 1


def _validate_percent_map(
    value: Any, name: str, *, meter_resolution: float | None = None
) -> dict[str, float]:
    source = require_exact_fields(value, set(LIMIT_KINDS), name)
    result = {kind: finite_number(source[kind], f"{name}.{kind}", maximum=100) for kind in LIMIT_KINDS}
    if meter_resolution is not None:
        for kind, amount in result.items():
            quotient = amount / meter_resolution
            if not math.isclose(quotient, round(quotient), rel_tol=0.0, abs_tol=1e-9):
                raise CampaignError(f"{name}.{kind} must be an integer multiple of meter resolution")
    return result


def _apply_begin(state: dict[str, Any], event: Mapping[str, Any]) -> None:
    source = require_exact_fields(event, BEGIN_FIELDS, "begin_arm event")
    if (
        not isinstance(source["schema_version"], int)
        or isinstance(source["schema_version"], bool)
        or source["schema_version"] != SCHEMA_VERSION
        or source["event_type"] != "begin_arm"
    ):
        raise CampaignError("invalid begin_arm event")
    if state["active"] is not None:
        raise CampaignError("only one campaign arm may be active")
    if state["pending_end"] is not None:
        raise CampaignError("independent acceptance is required before the next arm")
    _, expected_route, expected_pair, expected_position = _expected_arm(state)
    if source["route"] != expected_route:
        raise CampaignError(f"next route must be {expected_route}")
    if (
        source["pair_id"] != expected_pair
        or isinstance(source["arm_position"], bool)
        or not isinstance(source["arm_position"], int)
        or source["arm_position"] != expected_position
    ):
        raise CampaignError("begin_arm pair or position does not match the pre-registered order")
    revision = require_identifier(source["route_revision"], "route_revision")
    previous_revision = state["route_revisions"].get(expected_route)
    if previous_revision is not None and previous_revision != revision:
        raise CampaignError(f"{expected_route} route_revision changed during the campaign")
    observed = require_timestamp(source["observed_at"], "observed_at")
    for kind in LIMIT_KINDS:
        reset = require_timestamp(state["config"]["windows"][kind]["reset_at"], f"{kind} reset_at")
        if observed >= reset:
            raise CampaignError(f"begin observation crosses or reaches the {kind} reset boundary")
    remaining = _validate_percent_map(
        source["remaining_percent"], "remaining_percent",
        meter_resolution=state["config"]["meter_resolution_percentage_points"],
    )
    excluded = _validate_percent_map(
        source["excluded_since_previous_end_percentage_points"],
        "excluded_since_previous_end_percentage_points",
        meter_resolution=state["config"]["meter_resolution_percentage_points"],
    )
    last_end = state["last_end"]
    if last_end is None:
        expected_excluded = {kind: 0.0 for kind in LIMIT_KINDS}
    else:
        if observed <= last_end["observed_at"]:
            raise CampaignError("begin observations must be strictly later than the previous end")
        expected_excluded = {}
        for kind in LIMIT_KINDS:
            before = last_end["remaining_percent"][kind]
            if remaining[kind] > before:
                raise CampaignError(f"{kind} remaining allowance increased between arms")
            expected_excluded[kind] = before - remaining[kind]
    if excluded != expected_excluded:
        raise CampaignError("begin_arm excluded consumption does not match replayed readings")
    state["route_revisions"][expected_route] = revision
    for kind in LIMIT_KINDS:
        state["excluded"][kind] += excluded[kind]
    state["active"] = {
        "pair_id": expected_pair,
        "route": expected_route,
        "route_revision": revision,
        "arm_position": expected_position,
        "observed_at": observed,
        "observed_at_text": observed.isoformat(),
        "remaining_percent": remaining,
        "start_evidence_digest": require_digest(source["start_evidence_digest"], "start_evidence_digest"),
        "excluded_since_previous_end_percentage_points": excluded,
    }


def _build_record(
    state: Mapping[str, Any], pending: Mapping[str, Any], acceptance: Mapping[str, Any]
) -> dict[str, Any]:
    active = pending["active"]
    end_digest = pending["end_digest"]
    end_at = pending["end_at"]
    remaining = pending["remaining"]
    acceptance_value = acceptance["independent_acceptance"]
    defects = acceptance["defects"]
    expected_limits: dict[str, Any] = {}
    for kind in LIMIT_KINDS:
        expected_limits[kind] = {
            "window_id": state["config"]["windows"][kind]["window_id"],
            "before_observed_at": active["observed_at_text"],
            "after_observed_at": end_at.isoformat(),
            "window_reset_at": state["config"]["windows"][kind]["reset_at"],
            "before_remaining_percent": active["remaining_percent"][kind],
            "after_remaining_percent": remaining[kind],
            "reading_uncertainty_percentage_points": state["config"]["reading_uncertainty_percentage_points"],
        }
    expected = {
        "schema_version": SCHEMA_VERSION,
        "pair_id": active["pair_id"],
        "task_family": state["config"]["task_family"],
        "route": active["route"],
        "route_revision": active["route_revision"],
        "arm_position": active["arm_position"],
        "batch_size": state["config"]["batch_size"],
        "independent_acceptance": acceptance_value,
        "defects": defects,
        "elapsed_seconds": pending["elapsed_seconds"],
        "measurement_scope": "ROUTE_TASK_INTERVAL_ONLY",
        "contamination_status": "NO_OTHER_SHARED_USAGE_OBSERVED",
        "source": "chatgpt-usage-dashboard-v1",
        "evidence_digest": combined_evidence_digest(active["start_evidence_digest"], end_digest),
        "benchmark_contract_digest": state["config"]["contract_digest"],
        "usage_scope_digest": state["config"]["usage_scope_digest"],
        "starting_commit_sha": state["config"]["starting_commit_sha"],
        "task_spec_digest": state["config"]["task_spec_digest"],
        "acceptance_suite_digest": state["config"]["acceptance_suite_digest"],
        "sol_only_topology": state["config"]["sol_only_topology"],
        "sol_luna_topology": state["config"]["sol_luna_topology"],
        "top_level_run_count": 1,
        "worker_count": 0 if active["route"] == "SOL_ONLY" else state["config"]["sol_luna_worker_count"],
        "active_luna_writer_count": 0 if active["route"] == "SOL_ONLY" else state["config"]["sol_luna_active_luna_writer_count"],
        "target_elapsed_min_seconds": state["config"]["target_elapsed_min_seconds"],
        "target_elapsed_max_seconds": state["config"]["target_elapsed_max_seconds"],
        "meter_resolution_percentage_points": state["config"]["meter_resolution_percentage_points"],
        "repair_policy_digest": state["config"]["repair_policy_digest"],
        "limits": expected_limits,
    }
    return ALLOWANCE_METER.validate_record(expected)


def _validate_end_reading(state: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    active = state["active"]
    assert active is not None
    end_digest = require_digest(event["end_evidence_digest"], "end_evidence_digest")
    end_at = require_timestamp(event["observed_at"], "observed_at")
    remaining = _validate_percent_map(
        event["remaining_percent"], "remaining_percent",
        meter_resolution=state["config"]["meter_resolution_percentage_points"],
    )
    elapsed = finite_number(event["elapsed_seconds"], "elapsed_seconds")
    return {"active": active, "end_digest": end_digest, "end_at": end_at, "remaining": remaining, "elapsed_seconds": elapsed}


def _apply_end(state: dict[str, Any], event: Mapping[str, Any]) -> None:
    source = require_exact_fields(event, END_FIELDS, "end_arm event")
    if (
        not isinstance(source["schema_version"], int)
        or isinstance(source["schema_version"], bool)
        or source["schema_version"] != SCHEMA_VERSION
        or source["event_type"] != "end_arm"
    ):
        raise CampaignError("invalid end_arm event")
    active = state["active"]
    if active is None:
        raise CampaignError("end_arm has no active arm or duplicates a prior ending")
    if source["route"] != active["route"]:
        raise CampaignError("end_arm route does not match the active arm")
    if source["pair_id"] != active["pair_id"]:
        raise CampaignError("end_arm pair_id does not match the active arm")
    if state["pending_end"] is not None:
        raise CampaignError("an arm end is awaiting its independent acceptance event")
    candidate_digest = require_digest(source["candidate_digest"], "candidate_digest")
    pending = _validate_end_reading(state, source)
    pending["candidate_digest"] = candidate_digest
    end_at = pending["end_at"]
    if end_at <= active["observed_at"]:
        raise CampaignError("end observation must be strictly later than begin observation")
    for kind in LIMIT_KINDS:
        kind_end = end_at
        if kind_end != end_at:
            raise CampaignError("both meter readings must use the same end observation time")
        reset = require_timestamp(state["config"]["windows"][kind]["reset_at"], f"{kind} reset_at")
        if end_at >= reset:
            raise CampaignError(f"end observation crosses or reaches the {kind} reset boundary")
    state["pending_end"] = pending
    state["active"] = None


def _apply_acceptance(state: dict[str, Any], event: Mapping[str, Any]) -> None:
    source = require_exact_fields(event, ACCEPTANCE_FIELDS, "record_acceptance event")
    if (
        source["schema_version"] != SCHEMA_VERSION
        or source["event_type"] != "record_acceptance"
    ):
        raise CampaignError("invalid record_acceptance event")
    pending = state["pending_end"]
    if pending is None:
        raise CampaignError("record_acceptance has no pending arm end")
    active = pending["active"]
    if source["pair_id"] != active["pair_id"] or source["route"] != active["route"]:
        raise CampaignError("record_acceptance does not match the pending arm")
    candidate_digest = require_digest(source["candidate_digest"], "candidate_digest")
    if candidate_digest != pending["candidate_digest"]:
        raise CampaignError("record_acceptance candidate_digest does not match the route result")
    require_digest(source["acceptance_command_digest"], "acceptance_command_digest")
    require_digest(source["acceptance_result_digest"], "acceptance_result_digest")
    if require_digest(source["acceptance_suite_digest"], "acceptance_suite_digest") != state["config"]["acceptance_suite_digest"]:
        raise CampaignError("record_acceptance acceptance_suite_digest differs from campaign")
    observed_at = require_timestamp(source["observed_at"], "record_acceptance observed_at")
    if observed_at <= pending["end_at"]:
        raise CampaignError("record_acceptance must occur after route interval end")
    if state["last_end"] is not None and observed_at <= state["last_end"]["observed_at"]:
        raise CampaignError("record_acceptance must precede the next arm and follow the prior end")
    acceptance = source["independent_acceptance"]
    if acceptance not in {"PASSED", "FAILED"}:
        raise CampaignError("independent_acceptance must be PASSED or FAILED")
    defects = source["defects"]
    if isinstance(defects, bool) or not isinstance(defects, int) or defects < 0:
        raise CampaignError("defects must be a non-negative integer")
    acceptance_elapsed = finite_number(
        source["acceptance_elapsed_seconds"], "acceptance_elapsed_seconds"
    )
    record = _build_record(state, pending, source)
    if record["independent_acceptance"] != acceptance or record["defects"] != defects:
        raise CampaignError("record_acceptance result does not match the bound record")
    state["records"].append(record)
    state["last_end"] = {
        "observed_at": pending["end_at"],
        "observed_at_text": pending["end_at"].isoformat(),
        "remaining_percent": pending["remaining"],
    }
    state["active"] = None
    state["pending_end"] = None


def replay(ledger: Path) -> dict[str, Any]:
    try:
        raw = ledger.read_bytes()
    except OSError as exc:
        raise CampaignError(f"cannot read ledger: {exc}") from exc
    if not raw or not raw.endswith(b"\n"):
        raise CampaignError("ledger must be non-empty canonical UTF-8 JSONL")
    lines = raw[:-1].split(b"\n")
    previous = ZERO_PREVIOUS
    state: dict[str, Any] | None = None
    for number, line in enumerate(lines, start=1):
        if not line:
            raise CampaignError(f"ledger line {number} is blank")
        try:
            text = line.decode("utf-8")
            event = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CampaignError(f"ledger line {number} is not valid UTF-8 JSON") from exc
        if not isinstance(event, dict) or canonical_bytes(event) != line:
            raise CampaignError(f"ledger line {number} is not a canonical JSON object")
        if event.get("previous_event_sha256") != previous:
            raise CampaignError(f"ledger hash chain breaks at line {number}")
        if number == 1:
            state = _new_state(_validate_init(event))
        else:
            assert state is not None
            if event.get("event_type") == "begin_arm":
                _apply_begin(state, event)
            elif event.get("event_type") == "end_arm":
                _apply_end(state, event)
            elif event.get("event_type") == "record_acceptance":
                _apply_acceptance(state, event)
            else:
                raise CampaignError(f"ledger line {number} has an unknown event_type")
        previous = _event_previous(line)
    assert state is not None
    state["last_event_sha256"] = previous
    state["event_count"] = len(lines)
    return state


class ExclusiveLedgerLock:
    def __init__(self, ledger: Path):
        self.path = Path(str(ledger) + ".lock")
        self.fd: int | None = None

    def __enter__(self) -> "ExclusiveLedgerLock":
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(self.fd, b"allowance-campaign-lock\n")
            os.fsync(self.fd)
        except FileExistsError as exc:
            raise CampaignError(f"ledger lock already exists: {self.path}") from exc
        except OSError as exc:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
                try:
                    self.path.unlink()
                except OSError:
                    pass
            raise CampaignError(f"cannot acquire ledger lock: {exc}") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
            try:
                self.path.unlink()
            except OSError as unlink_exc:
                if exc is None:
                    raise CampaignError(f"cannot remove owned ledger lock: {unlink_exc}") from unlink_exc


def atomic_write(ledger: Path, events: list[Mapping[str, Any]]) -> None:
    if not ledger.parent.is_dir():
        raise CampaignError("ledger parent directory does not exist")
    payload = b"\n".join(canonical_bytes(event) for event in events) + b"\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=ledger.parent, prefix=ledger.name + ".", suffix=".tmp"
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ledger)
        temporary = None
    except OSError as exc:
        raise CampaignError(f"cannot atomically update ledger: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise CampaignError(f"cannot clean temporary ledger: {exc}") from exc


def _read_events(ledger: Path) -> list[dict[str, Any]]:
    replay(ledger)
    try:
        return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"cannot reload ledger events: {exc}") from exc


def _append(ledger: Path, builder: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    with ExclusiveLedgerLock(ledger):
        state = replay(ledger)
        events = _read_events(ledger)
        event = builder(state)
        event["previous_event_sha256"] = state["last_event_sha256"]
        if event.get("event_type") == "begin_arm":
            _apply_begin(state, event)
        elif event.get("event_type") == "end_arm":
            _apply_end(state, event)
        elif event.get("event_type") == "record_acceptance":
            _apply_acceptance(state, event)
        else:
            raise CampaignError("write command produced an unknown event_type")
        events.append(event)
        atomic_write(ledger, events)
        replay(ledger)
        return event


def initialize(
    ledger: Path, *, contract_digest: str, usage_scope_digest: str, task_family: str,
    batch_size: int, reading_uncertainty: float, first_routes: str | list[str],
    five_hour_window_id: str, five_hour_reset_at: str,
    weekly_window_id: str, weekly_reset_at: str,
    starting_commit_sha: str = DEFAULT_STARTING_COMMIT_SHA,
    task_spec_digest: str = DEFAULT_TASK_DIGEST,
    acceptance_suite_digest: str = DEFAULT_TASK_DIGEST,
    sol_only_topology: str = TOPOLOGIES["sol_only"],
    sol_luna_topology: str = TOPOLOGIES["sol_luna"],
    sol_luna_worker_count: int = DEFAULT_SOL_LUNA_WORKER_COUNT,
    sol_luna_active_luna_writer_count: int = DEFAULT_SOL_LUNA_ACTIVE_LUNA_WRITER_COUNT,
    target_elapsed_min_seconds: int = DEFAULT_TARGET_ELAPSED_MIN_SECONDS,
    target_elapsed_max_seconds: int = DEFAULT_TARGET_ELAPSED_MAX_SECONDS,
    meter_resolution_percentage_points: float = DEFAULT_METER_RESOLUTION,
    repair_policy_digest: str = DEFAULT_TASK_DIGEST,
) -> dict[str, Any]:
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "init",
        "previous_event_sha256": ZERO_PREVIOUS,
        "contract_digest": contract_digest,
        "usage_scope_digest": usage_scope_digest,
        "task_family": task_family,
        "batch_size": batch_size,
        "reading_uncertainty_percentage_points": reading_uncertainty,
        "first_routes": normalize_first_routes(first_routes),
        "windows": {
            "five_hour": {"window_id": five_hour_window_id, "reset_at": five_hour_reset_at},
            "weekly": {"window_id": weekly_window_id, "reset_at": weekly_reset_at},
        },
        "starting_commit_sha": starting_commit_sha,
        "task_spec_digest": task_spec_digest,
        "acceptance_suite_digest": acceptance_suite_digest,
        "sol_only_topology": sol_only_topology,
        "sol_luna_topology": sol_luna_topology,
        "sol_luna_worker_count": sol_luna_worker_count,
        "sol_luna_active_luna_writer_count": sol_luna_active_luna_writer_count,
        "target_elapsed_min_seconds": target_elapsed_min_seconds,
        "target_elapsed_max_seconds": target_elapsed_max_seconds,
        "meter_resolution_percentage_points": meter_resolution_percentage_points,
        "repair_policy_digest": repair_policy_digest,
    }
    _validate_init(event)
    with ExclusiveLedgerLock(ledger):
        if ledger.exists():
            raise CampaignError("ledger already exists; refusing to truncate it")
        atomic_write(ledger, [event])
        replay(ledger)
    return campaign_status(ledger)


def begin_arm(
    ledger: Path, *, route: str, route_revision: str, observed_at: str,
    five_hour_remaining_percent: float, weekly_remaining_percent: float,
    start_evidence_digest: str,
) -> dict[str, Any]:
    def build(state: dict[str, Any]) -> dict[str, Any]:
        if state["active"] is not None:
            raise CampaignError("only one campaign arm may be active")
        _, expected_route, pair_id, position = _expected_arm(state)
        if route != expected_route:
            raise CampaignError(f"next route must be {expected_route}")
        require_identifier(route_revision, "route_revision")
        require_timestamp(observed_at, "observed_at")
        require_digest(start_evidence_digest, "start_evidence_digest")
        remaining = _validate_percent_map({
            "five_hour": five_hour_remaining_percent,
            "weekly": weekly_remaining_percent,
        }, "remaining_percent", meter_resolution=state["config"]["meter_resolution_percentage_points"])
        last_end = state["last_end"]
        if last_end is None:
            excluded = {kind: 0.0 for kind in LIMIT_KINDS}
        else:
            excluded = {}
            for kind in LIMIT_KINDS:
                if remaining[kind] > last_end["remaining_percent"][kind]:
                    raise CampaignError(f"{kind} remaining allowance increased between arms")
                excluded[kind] = last_end["remaining_percent"][kind] - remaining[kind]
        return {
            "schema_version": SCHEMA_VERSION,
            "event_type": "begin_arm",
            "previous_event_sha256": "",
            "pair_id": pair_id,
            "route": route,
            "route_revision": route_revision,
            "arm_position": position,
            "observed_at": observed_at,
            "remaining_percent": remaining,
            "start_evidence_digest": start_evidence_digest,
            "excluded_since_previous_end_percentage_points": excluded,
        }

    event = _append(ledger, build)
    return {
        "pair_id": event["pair_id"], "route": event["route"],
        "arm_position": event["arm_position"],
        "excluded_since_previous_end_percentage_points": event[
            "excluded_since_previous_end_percentage_points"
        ],
    }


def end_arm(
    ledger: Path, *, pair_id: str, route: str, observed_at: str,
    five_hour_remaining_percent: float, weekly_remaining_percent: float,
    end_evidence_digest: str, elapsed_seconds: float,
    candidate_digest: str,
) -> dict[str, Any]:
    def build(state: dict[str, Any]) -> dict[str, Any]:
        active = state["active"]
        if active is None:
            raise CampaignError("there is no active arm to end")
        if pair_id != active["pair_id"]:
            raise CampaignError("end_arm pair_id does not match the active arm")
        if route != active["route"]:
            raise CampaignError("end_arm route does not match the active arm")
        return {
            "schema_version": SCHEMA_VERSION,
            "event_type": "end_arm",
            "previous_event_sha256": "",
            "pair_id": active["pair_id"],
            "route": route,
            "observed_at": observed_at,
            "remaining_percent": {
                "five_hour": five_hour_remaining_percent,
                "weekly": weekly_remaining_percent,
            },
            "end_evidence_digest": end_evidence_digest,
            "elapsed_seconds": elapsed_seconds,
            "candidate_digest": candidate_digest,
        }

    return _append(ledger, build)


def record_acceptance(
    ledger: Path, *, pair_id: str, route: str, candidate_digest: str,
    acceptance_command_digest: str, acceptance_result_digest: str,
    acceptance_suite_digest: str, observed_at: str,
    acceptance_elapsed_seconds: float, independent_acceptance: str, defects: int,
) -> dict[str, Any]:
    def build(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "event_type": "record_acceptance",
            "previous_event_sha256": "",
            "pair_id": pair_id,
            "route": route,
            "candidate_digest": candidate_digest,
            "acceptance_command_digest": acceptance_command_digest,
            "acceptance_result_digest": acceptance_result_digest,
            "acceptance_suite_digest": acceptance_suite_digest,
            "observed_at": observed_at,
            "acceptance_elapsed_seconds": acceptance_elapsed_seconds,
            "independent_acceptance": independent_acceptance,
            "defects": defects,
        }

    _append(ledger, build)
    return replay(ledger)["records"][-1]


def campaign_status(ledger: Path) -> dict[str, Any]:
    state = replay(ledger)
    records = state["records"]
    sequence = route_sequence(state["config"]["first_routes"])
    active = state["active"]
    next_index = len(records) + (1 if active is not None else 0)
    active_output = None
    if active is not None:
        active_output = {
            "pair_id": active["pair_id"], "route": active["route"],
            "route_revision": active["route_revision"], "arm_position": active["arm_position"],
            "observed_at": active["observed_at_text"],
            "remaining_percent": active["remaining_percent"],
            "start_evidence_digest": active["start_evidence_digest"],
        }
    last = state["last_end"]
    return {
        "schema_version": SCHEMA_VERSION,
        "completed_pairs": len(records) // 2,
        "completed_arms": len(records),
        "planned_pairs": len(state["config"]["first_routes"]),
        "active_arm": active_output,
        "next_route": (
            None if state["pending_end"] is not None
            else sequence[next_index] if next_index < len(sequence) else None
        ),
        "pending_acceptance": None if state["pending_end"] is None else {
            "pair_id": state["pending_end"]["active"]["pair_id"],
            "route": state["pending_end"]["active"]["route"],
            "observed_at": state["pending_end"]["end_at"].isoformat(),
            "candidate_digest": state["pending_end"]["candidate_digest"],
        },
        "last_reading": None if last is None else {
            "observed_at": last["observed_at_text"], "remaining_percent": last["remaining_percent"]
        },
        "excluded_consumption_percentage_points": state["excluded"],
    }


def assess_campaign(
    ledger: Path, *, minimum_advantage_multiple: float = 10.0, minimum_pairs: int = 5,
) -> dict[str, Any]:
    if isinstance(minimum_pairs, bool) or not isinstance(minimum_pairs, int) or minimum_pairs < 5:
        raise CampaignError("production campaign minimum_pairs must be at least 5")
    state = replay(ledger)
    config = state["config"]
    placeholder_digest = "sha256:" + "0" * 64
    if (
        config["starting_commit_sha"] in {"0" * 40, "0" * 64}
        or any(
            config[field] == placeholder_digest
            for field in ("task_spec_digest", "acceptance_suite_digest", "repair_policy_digest")
        )
    ):
        raise CampaignError("production assessment requires non-placeholder frozen identity fields")
    if state["active"] is not None:
        raise CampaignError("cannot assess while an arm is active")
    if state["pending_end"] is not None:
        raise CampaignError("independent acceptance event is required before assessment")
    try:
        return ALLOWANCE_METER.assess(
            state["records"], minimum_advantage_multiple=minimum_advantage_multiple,
            minimum_pairs=minimum_pairs,
        )
    except ALLOWANCE_METER.AllowanceError as exc:
        raise CampaignError(str(exc)) from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Record a pre-registered allowance benchmark campaign.")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--ledger", required=True, type=Path)
    init.add_argument("--contract-digest", required=True)
    init.add_argument("--usage-scope-digest", required=True)
    init.add_argument("--task-family", required=True)
    init.add_argument("--batch-size", required=True, type=int)
    init.add_argument("--reading-uncertainty", required=True, type=float)
    init.add_argument("--first-routes", required=True)
    init.add_argument("--five-hour-window-id", required=True)
    init.add_argument("--five-hour-reset-at", required=True)
    init.add_argument("--weekly-window-id", required=True)
    init.add_argument("--weekly-reset-at", required=True)
    init.add_argument("--starting-commit-sha", required=True)
    init.add_argument("--task-spec-digest", required=True)
    init.add_argument("--acceptance-suite-digest", required=True)
    init.add_argument("--sol-only-topology", default=TOPOLOGIES["sol_only"])
    init.add_argument("--sol-luna-topology", default=TOPOLOGIES["sol_luna"])
    init.add_argument(
        "--sol-luna-worker-count", type=int, default=DEFAULT_SOL_LUNA_WORKER_COUNT
    )
    init.add_argument(
        "--sol-luna-active-luna-writer-count", type=int,
        default=DEFAULT_SOL_LUNA_ACTIVE_LUNA_WRITER_COUNT,
    )
    init.add_argument("--target-elapsed-min-seconds", type=int, default=DEFAULT_TARGET_ELAPSED_MIN_SECONDS)
    init.add_argument("--target-elapsed-max-seconds", type=int, default=DEFAULT_TARGET_ELAPSED_MAX_SECONDS)
    init.add_argument(
        "--meter-resolution-percentage-points", type=float, default=DEFAULT_METER_RESOLUTION
    )
    init.add_argument("--repair-policy-digest", required=True)
    for name in ("begin-arm", "end-arm"):
        command = commands.add_parser(name)
        command.add_argument("--ledger", required=True, type=Path)
        if name == "end-arm":
            command.add_argument("--pair-id", required=True)
        command.add_argument("--route", required=True, choices=sorted(ROUTES))
        command.add_argument("--observed-at", required=True)
        command.add_argument("--five-hour-remaining-percent", required=True, type=float)
        command.add_argument("--weekly-remaining-percent", required=True, type=float)
        if name == "begin-arm":
            command.add_argument("--route-revision", required=True)
            command.add_argument("--start-evidence-digest", required=True)
        else:
            command.add_argument("--end-evidence-digest", required=True)
            command.add_argument("--elapsed-seconds", required=True, type=float)
            command.add_argument("--candidate-digest", required=True)
    acceptance = commands.add_parser("record-acceptance")
    acceptance.add_argument("--ledger", required=True, type=Path)
    acceptance.add_argument("--pair-id", required=True)
    acceptance.add_argument("--route", required=True, choices=sorted(ROUTES))
    acceptance.add_argument("--candidate-digest", required=True)
    acceptance.add_argument("--acceptance-command-digest", required=True)
    acceptance.add_argument("--acceptance-result-digest", required=True)
    acceptance.add_argument("--acceptance-suite-digest", required=True)
    acceptance.add_argument("--observed-at", required=True)
    acceptance.add_argument("--acceptance-elapsed-seconds", required=True, type=float)
    acceptance.add_argument("--independent-acceptance", required=True, choices=("PASSED", "FAILED"))
    acceptance.add_argument("--defects", required=True, type=int)
    status_command = commands.add_parser("status")
    status_command.add_argument("--ledger", required=True, type=Path)
    assess_command = commands.add_parser("assess")
    assess_command.add_argument("--ledger", required=True, type=Path)
    assess_command.add_argument("--minimum-advantage-multiple", type=float, default=10.0)
    assess_command.add_argument("--minimum-pairs", type=int, default=5)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "init":
            output = initialize(
                args.ledger, contract_digest=args.contract_digest,
                usage_scope_digest=args.usage_scope_digest, task_family=args.task_family,
                batch_size=args.batch_size, reading_uncertainty=args.reading_uncertainty,
                first_routes=args.first_routes, five_hour_window_id=args.five_hour_window_id,
                five_hour_reset_at=args.five_hour_reset_at, weekly_window_id=args.weekly_window_id,
                weekly_reset_at=args.weekly_reset_at,
                starting_commit_sha=args.starting_commit_sha,
                task_spec_digest=args.task_spec_digest,
                acceptance_suite_digest=args.acceptance_suite_digest,
                sol_only_topology=args.sol_only_topology,
                sol_luna_topology=args.sol_luna_topology,
                sol_luna_worker_count=args.sol_luna_worker_count,
                sol_luna_active_luna_writer_count=args.sol_luna_active_luna_writer_count,
                target_elapsed_min_seconds=args.target_elapsed_min_seconds,
                target_elapsed_max_seconds=args.target_elapsed_max_seconds,
                meter_resolution_percentage_points=args.meter_resolution_percentage_points,
                repair_policy_digest=args.repair_policy_digest,
            )
        elif args.command == "begin-arm":
            output = begin_arm(
                args.ledger, route=args.route, route_revision=args.route_revision,
                observed_at=args.observed_at,
                five_hour_remaining_percent=args.five_hour_remaining_percent,
                weekly_remaining_percent=args.weekly_remaining_percent,
                start_evidence_digest=args.start_evidence_digest,
            )
        elif args.command == "end-arm":
            output = end_arm(
                args.ledger, pair_id=args.pair_id, route=args.route, observed_at=args.observed_at,
                five_hour_remaining_percent=args.five_hour_remaining_percent,
                weekly_remaining_percent=args.weekly_remaining_percent,
                end_evidence_digest=args.end_evidence_digest,
                elapsed_seconds=args.elapsed_seconds,
                candidate_digest=args.candidate_digest,
            )
        elif args.command == "record-acceptance":
            output = record_acceptance(
                args.ledger, pair_id=args.pair_id, route=args.route,
                candidate_digest=args.candidate_digest,
                acceptance_command_digest=args.acceptance_command_digest,
                acceptance_result_digest=args.acceptance_result_digest,
                acceptance_suite_digest=args.acceptance_suite_digest,
                observed_at=args.observed_at,
                acceptance_elapsed_seconds=args.acceptance_elapsed_seconds,
                independent_acceptance=args.independent_acceptance,
                defects=args.defects,
            )
        elif args.command == "status":
            output = campaign_status(args.ledger)
        else:
            output = assess_campaign(
                args.ledger, minimum_advantage_multiple=args.minimum_advantage_multiple,
                minimum_pairs=args.minimum_pairs,
            )
    except CampaignError as exc:
        print(f"allowance campaign error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Record replayable Sol-Luna phase intervals and execution overlap metrics."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import evidence_ledger

LEGACY_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2
PHASES = evidence_ledger.PHASES
EXECUTION_PHASES = {"sol_execution", "sol_retained_execution", "luna_execution"}
SOL_PHASES = {"sol_planning", "sol_execution", "sol_retained_execution", "sol_review", "integration"}
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
JOURNAL_V2_FIELDS = frozenset({
    "schema_version", "run_ref", "route", "created_at", "last_event_at",
    "open_intervals", "phase_intervals", "events",
})
LEGACY_FIELDS = frozenset({
    "schema_version", "run_ref", "route", "created_at", "last_event_at",
    "open_phases", "phase_elapsed_seconds", "phase_tokens", "phase_credits", "events",
})
OPEN_INTERVAL_FIELDS = frozenset({
    "interval_id", "phase", "executor_id", "actor", "started_at",
})
CLOSED_INTERVAL_FIELDS = frozenset({
    *OPEN_INTERVAL_FIELDS, "ended_at", "duration_seconds", "tokens", "credits",
    "command_exit_code", "command_launch_error",
})


class TrackerError(ValueError):
    """A phase journal event is invalid or inconsistent."""


def _reject_constant(value: str) -> None:
    raise TrackerError(f"non-finite JSON constant is not allowed: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrackerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise TrackerError(f"invalid JSON: {exc}") from exc


def timestamp(value: str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, str) or not value or value != value.strip():
        raise TrackerError("timestamp must be ISO-8601")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise TrackerError("timestamp must be ISO-8601") from exc
    if result.tzinfo is None:
        raise TrackerError("timestamp must include a timezone")
    try:
        result.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise TrackerError("timestamp is out of range") from exc
    return result


def timestamp_text(value: str | None = None) -> str:
    return timestamp(value).astimezone(timezone.utc).isoformat()


def finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise TrackerError(f"{field} must be a finite non-negative number")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise TrackerError(f"{field} must be a finite non-negative number") from exc
    if not math.isfinite(converted):
        raise TrackerError(f"{field} must be a finite non-negative number")
    return converted


def finite_sum(left: float, right: float, field: str) -> float:
    """Add finite values without allowing IEEE-754 overflow to escape."""
    try:
        total = left + right
    except (OverflowError, ValueError) as exc:
        raise TrackerError(f"{field} aggregate is not finite") from exc
    if not math.isfinite(total):
        raise TrackerError(f"{field} aggregate is not finite")
    return total


def finite_mapping_sum(values: Mapping[str, Any], field: str) -> float:
    total = 0.0
    for key, value in values.items():
        total = finite_sum(total, finite(value, f"{field}[{key}]"), field)
    return total


def non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrackerError(f"{field} must be a non-negative integer")
    return value


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise TrackerError(f"{field} must be a compact hyphen-case identifier")
    return value


def _exact_fields(value: Mapping[str, Any], fields: frozenset[str], field: str) -> None:
    unknown = set(value) - fields
    missing = set(fields) - set(value)
    if unknown:
        raise TrackerError(f"{field} contains unsupported fields: {sorted(unknown)}")
    if missing:
        raise TrackerError(f"{field} is missing required fields: {sorted(missing)}")


def atomic_write(path: Path, document: Mapping[str, Any]) -> None:
    """Flush strict JSON to a same-directory temporary and atomically replace target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n",
            prefix=f".{path.name}.", suffix=".tmp",
        ) as handle:
            temporary = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def initialize(run_ref: str, route: str, *, at: str | None = None) -> dict[str, Any]:
    if not isinstance(route, str) or route not in evidence_ledger.ROUTES:
        raise TrackerError(f"route must be one of {sorted(evidence_ledger.ROUTES)}")
    if not isinstance(run_ref, str) or not run_ref.strip() or "\n" in run_ref or "\r" in run_ref:
        raise TrackerError("run_ref is required and must be single-line")
    created = timestamp_text(at)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_ref": evidence_ledger.redacted_ref(run_ref.strip()),
        "route": route,
        "created_at": created,
        "last_event_at": created,
        "open_intervals": [],
        "phase_intervals": [],
        "events": 0,
    }


def _validate_route_phase(route: str, phase: str) -> None:
    if not isinstance(route, str) or route not in evidence_ledger.ROUTES:
        raise TrackerError("route must be one of the supported routes")
    if not isinstance(phase, str):
        raise TrackerError("phase must be a string")
    if phase not in PHASES:
        raise TrackerError(f"unsupported phase: {phase}")
    if route == "SOL_ONLY" and phase in {"luna_execution", "sol_retained_execution"}:
        raise TrackerError(f"SOL_ONLY journal cannot contain {phase}")
    if route == "SOL_LUNA" and phase == "sol_execution":
        raise TrackerError("SOL_LUNA journal cannot contain sol_execution")


def _required_actor(route: str, phase: str) -> str | None:
    _validate_route_phase(route, phase)
    if phase in SOL_PHASES:
        return "SOL"
    if phase == "luna_execution":
        return "LUNA"
    return None


def _actor_hint(executor_id: str) -> str | None:
    if executor_id == "sol" or executor_id.startswith("sol-"):
        return "SOL"
    if executor_id == "luna" or executor_id.startswith("luna-"):
        return "LUNA"
    return None


def _normalize_interval(
    raw: Any,
    *,
    closed: bool,
    route: str,
    created: datetime,
    actors_by_executor: dict[str, str],
    field: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TrackerError(f"{field} must be a JSON object")
    fields = CLOSED_INTERVAL_FIELDS if closed else OPEN_INTERVAL_FIELDS
    _exact_fields(raw, fields, field)
    interval_id = identifier(raw.get("interval_id"), f"{field}.interval_id")
    phase = raw.get("phase")
    if not isinstance(phase, str):
        raise TrackerError(f"{field}.phase must be a string")
    required_actor = _required_actor(route, phase)
    executor_id = identifier(raw.get("executor_id"), f"{field}.executor_id")
    actor = raw.get("actor")
    if not isinstance(actor, str) or actor not in {"SOL", "LUNA"}:
        raise TrackerError(f"{field}.actor must be SOL or LUNA")
    if required_actor is not None and actor != required_actor:
        raise TrackerError(f"{phase} must be recorded by a {required_actor} executor")
    hint = _actor_hint(executor_id)
    if hint is not None and hint != actor:
        raise TrackerError(f"executor_id {executor_id} conflicts with actor {actor}")
    previous_actor = actors_by_executor.get(executor_id)
    if previous_actor is not None and previous_actor != actor:
        raise TrackerError(f"executor_id {executor_id} cannot change actor")
    actors_by_executor[executor_id] = actor
    started = timestamp(raw.get("started_at"))
    if started < created:
        raise TrackerError(f"{field}.started_at precedes journal creation")
    normalized: dict[str, Any] = {
        "interval_id": interval_id,
        "phase": phase,
        "executor_id": executor_id,
        "actor": actor,
        "started_at": started.astimezone(timezone.utc).isoformat(),
    }
    if not closed:
        return normalized
    ended = timestamp(raw.get("ended_at"))
    if ended < started:
        raise TrackerError(f"{field}.ended_at precedes its start")
    duration = finite(raw.get("duration_seconds"), f"{field}.duration_seconds")
    expected_duration = round((ended - started).total_seconds(), 6)
    if abs(duration - expected_duration) > 1e-6:
        raise TrackerError(f"{field}.duration_seconds does not match its timestamps")
    tokens = raw.get("tokens")
    if tokens is not None:
        tokens = non_negative_integer(tokens, f"{field}.tokens")
    credits = raw.get("credits")
    if credits is not None:
        credits = finite(credits, f"{field}.credits")
    command_exit_code = raw.get("command_exit_code")
    if command_exit_code is not None and (
        isinstance(command_exit_code, bool) or not isinstance(command_exit_code, int)
    ):
        raise TrackerError(f"{field}.command_exit_code must be an integer or null")
    command_launch_error = raw.get("command_launch_error")
    if command_launch_error is not None and (
        not isinstance(command_launch_error, str) or "\n" in command_launch_error
        or "\r" in command_launch_error or len(command_launch_error) > 500
    ):
        raise TrackerError(f"{field}.command_launch_error must be a short single-line string or null")
    normalized.update({
        "ended_at": ended.astimezone(timezone.utc).isoformat(),
        "duration_seconds": expected_duration,
        "tokens": tokens,
        "credits": credits,
        "command_exit_code": command_exit_code,
        "command_launch_error": command_launch_error,
    })
    return normalized


def _validate_legacy(source: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(source) - LEGACY_FIELDS
    missing = set(LEGACY_FIELDS) - set(source)
    if unknown:
        raise TrackerError(f"phase journal contains unsupported fields: {sorted(unknown)}")
    if missing:
        raise TrackerError(f"legacy phase journal is missing fields: {sorted(missing)}")
    journal = deepcopy(dict(source))
    if not isinstance(journal.get("route"), str) or journal["route"] not in evidence_ledger.ROUTES:
        raise TrackerError("invalid journal route")
    if not isinstance(journal.get("run_ref"), str) or not journal["run_ref"].startswith("redacted:run:"):
        raise TrackerError("journal run_ref must be redacted")
    created = timestamp(journal.get("created_at"))
    last_event = timestamp(journal.get("last_event_at"))
    if last_event < created:
        raise TrackerError("last event precedes journal creation")
    for field in ("open_phases", "phase_elapsed_seconds", "phase_tokens", "phase_credits"):
        if not isinstance(journal.get(field), dict):
            raise TrackerError(f"{field} must be a JSON object")
        if set(journal[field]) - PHASES:
            raise TrackerError(f"{field} contains an unsupported phase")
        for phase in journal[field]:
            _validate_route_phase(journal["route"], phase)
    for phase, value in journal["open_phases"].items():
        started = timestamp(value)
        if started < created or started > last_event:
            raise TrackerError(f"invalid open phase start: {phase}")
    elapsed = (last_event - created).total_seconds()
    for phase, value in journal["phase_elapsed_seconds"].items():
        if finite(value, f"phase_elapsed_seconds[{phase}]") > elapsed + 1e-6:
            raise TrackerError(f"phase_elapsed_seconds[{phase}] exceeds journal elapsed time")
    for phase, value in journal["phase_tokens"].items():
        non_negative_integer(value, f"phase_tokens[{phase}]")
    for phase, value in journal["phase_credits"].items():
        finite(value, f"phase_credits[{phase}]")
    for field in ("phase_tokens", "phase_credits"):
        orphaned = set(journal[field]) - set(journal["phase_elapsed_seconds"])
        if orphaned:
            raise TrackerError(f"{field} has no elapsed phase: {sorted(orphaned)}")
    non_negative_integer(journal.get("events"), "events")
    return journal


def validate_journal(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise TrackerError("phase journal must be a JSON object")
    version = source.get("schema_version")
    if type(version) is not int:
        raise TrackerError("schema_version must be an integer")
    if version == LEGACY_SCHEMA_VERSION:
        return _validate_legacy(source)
    if version != SCHEMA_VERSION:
        raise TrackerError("unsupported phase journal schema")
    unknown = set(source) - JOURNAL_V2_FIELDS
    missing = set(JOURNAL_V2_FIELDS) - set(source)
    if unknown:
        raise TrackerError(f"phase journal contains unsupported fields: {sorted(unknown)}")
    if missing:
        raise TrackerError(f"phase journal is missing required fields: {sorted(missing)}")
    route = source.get("route")
    if not isinstance(route, str) or route not in evidence_ledger.ROUTES:
        raise TrackerError("invalid journal route")
    run_ref = source.get("run_ref")
    if not isinstance(run_ref, str) or not re.fullmatch(r"redacted:run:[0-9a-f]{16}", run_ref):
        raise TrackerError("journal run_ref must be redacted")
    created = timestamp(source.get("created_at"))
    supplied_last = timestamp(source.get("last_event_at"))
    if supplied_last < created:
        raise TrackerError("last event precedes journal creation")
    if not isinstance(source.get("open_intervals"), list):
        raise TrackerError("open_intervals must be a JSON array")
    if not isinstance(source.get("phase_intervals"), list):
        raise TrackerError("phase_intervals must be a JSON array")
    actors_by_executor: dict[str, str] = {}
    closed = [
        _normalize_interval(item, closed=True, route=route, created=created,
                            actors_by_executor=actors_by_executor, field=f"phase_intervals[{index}]")
        for index, item in enumerate(source["phase_intervals"])
    ]
    opened = [
        _normalize_interval(item, closed=False, route=route, created=created,
                            actors_by_executor=actors_by_executor, field=f"open_intervals[{index}]")
        for index, item in enumerate(source["open_intervals"])
    ]
    interval_ids = [item["interval_id"] for item in closed + opened]
    if len(interval_ids) != len(set(interval_ids)):
        raise TrackerError("interval_id values must be unique across the journal")
    latest = max(
        [created]
        + [timestamp(item["ended_at"]) for item in closed]
        + [timestamp(item["started_at"]) for item in opened]
    )
    if supplied_last != latest:
        raise TrackerError("last_event_at must equal the latest recorded interval event")
    events = non_negative_integer(source.get("events"), "events")
    if events != len(opened) + 2 * len(closed):
        raise TrackerError("events does not match the recorded interval events")
    closed.sort(key=lambda item: (item["started_at"], item["ended_at"], item["interval_id"]))
    opened.sort(key=lambda item: (item["started_at"], item["interval_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "run_ref": run_ref,
        "route": route,
        "created_at": created.astimezone(timezone.utc).isoformat(),
        "last_event_at": latest.astimezone(timezone.utc).isoformat(),
        "open_intervals": opened,
        "phase_intervals": closed,
        "events": events,
    }


def load(path: Path) -> dict[str, Any]:
    try:
        source = strict_json_loads(path.read_text(encoding="utf-8"))
        return validate_journal(source)
    except (OSError, UnicodeError) as exc:
        raise TrackerError(f"cannot read phase journal: {exc}") from exc


def _production(journal: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_journal(journal)
    if result.get("schema_version") != SCHEMA_VERSION:
        raise TrackerError("legacy schema 1 journals are read-only; initialize a schema 2 journal")
    return result


def _next_interval_id(journal: Mapping[str, Any]) -> str:
    used = {item["interval_id"] for item in journal["open_intervals"] + journal["phase_intervals"]}
    sequence = int(journal["events"]) + 1
    while f"interval-{sequence:06d}" in used:
        sequence += 1
    return f"interval-{sequence:06d}"


def _known_actors(journal: Mapping[str, Any]) -> dict[str, str]:
    return {
        item["executor_id"]: item["actor"]
        for item in journal["phase_intervals"] + journal["open_intervals"]
    }


def start(
    journal: Mapping[str, Any],
    phase: str,
    executor_id: str | None = None,
    *,
    actor: str | None = None,
    interval_id: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    result = _production(journal)
    if not isinstance(phase, str):
        raise TrackerError("phase must be a string")
    if executor_id is None:
        raise TrackerError("executor_id is required for schema 2 events")
    executor_id = identifier(executor_id, "executor_id")
    interval_id = identifier(interval_id, "interval_id") if interval_id is not None else _next_interval_id(result)
    if any(
        item["interval_id"] == interval_id
        for item in result["open_intervals"] + result["phase_intervals"]
    ):
        raise TrackerError(f"interval_id already exists: {interval_id}")
    required_actor = _required_actor(result["route"], phase)
    known_actor = _known_actors(result).get(executor_id)
    hinted_actor = _actor_hint(executor_id)
    if actor is not None and (not isinstance(actor, str) or actor not in {"SOL", "LUNA"}):
        raise TrackerError("actor must be SOL or LUNA")
    if actor is not None and known_actor is not None and actor != known_actor:
        raise TrackerError(f"executor_id {executor_id} is registered as {known_actor}, not {actor}")
    if actor is not None and hinted_actor is not None and actor != hinted_actor:
        raise TrackerError(f"executor_id {executor_id} conflicts with actor {actor}")
    if required_actor is None:
        actor = known_actor or actor or hinted_actor
        if actor is None:
            raise TrackerError("repair executor actor is unknown; pass actor or use a registered executor_id")
    else:
        if actor is not None and actor != required_actor:
            raise TrackerError(f"{phase} must be recorded by a {required_actor} executor")
        actor = required_actor
        if known_actor is not None and known_actor != actor:
            raise TrackerError(f"executor_id {executor_id} is registered as {known_actor}, not {actor}")
        if hinted_actor is not None and hinted_actor != actor:
            raise TrackerError(f"executor_id {executor_id} conflicts with {phase}")
    started = timestamp(at)
    if started < timestamp(result["created_at"]):
        raise TrackerError("phase start precedes journal creation")
    result["open_intervals"].append({
        "interval_id": interval_id,
        "phase": phase,
        "executor_id": executor_id,
        "actor": actor,
        "started_at": started.astimezone(timezone.utc).isoformat(),
    })
    result["events"] += 1
    result["last_event_at"] = max(timestamp(result["last_event_at"]), started).astimezone(timezone.utc).isoformat()
    return validate_journal(result)


def stop(
    journal: Mapping[str, Any],
    phase: str,
    executor_id: str | None = None,
    *,
    interval_id: str | None = None,
    at: str | None = None,
    tokens: int | None = None,
    credits: float | None = None,
    command_exit_code: int | None = None,
    command_launch_error: str | None = None,
) -> dict[str, Any]:
    result = _production(journal)
    if not isinstance(phase, str):
        raise TrackerError("phase must be a string")
    if executor_id is None:
        raise TrackerError("executor_id is required for schema 2 events")
    executor_id = identifier(executor_id, "executor_id")
    if interval_id is not None:
        interval_id = identifier(interval_id, "interval_id")
    matches = [
        item for item in result["open_intervals"]
        if item["phase"] == phase and item["executor_id"] == executor_id
        and (interval_id is None or item["interval_id"] == interval_id)
    ]
    if not matches:
        raise TrackerError(f"matching phase interval is not open: {phase}/{executor_id}")
    if len(matches) > 1:
        raise TrackerError("multiple matching intervals are open; interval_id is required")
    opened = matches[0]
    ended = timestamp(at)
    started = timestamp(opened["started_at"])
    if ended < started:
        raise TrackerError("phase end precedes phase start")
    if tokens is not None:
        tokens = non_negative_integer(tokens, "tokens")
    if credits is not None:
        credits = finite(credits, "credits")
    if command_exit_code is not None and (
        isinstance(command_exit_code, bool) or not isinstance(command_exit_code, int)
    ):
        raise TrackerError("command_exit_code must be an integer or null")
    if command_launch_error is not None:
        command_launch_error = str(command_launch_error).replace("\r", " ").replace("\n", " ")[:500]
    result["open_intervals"] = [
        item for item in result["open_intervals"] if item["interval_id"] != opened["interval_id"]
    ]
    closed = dict(opened)
    closed.update({
        "ended_at": ended.astimezone(timezone.utc).isoformat(),
        "duration_seconds": round((ended - started).total_seconds(), 6),
        "tokens": tokens,
        "credits": credits,
        "command_exit_code": command_exit_code,
        "command_launch_error": command_launch_error,
    })
    result["phase_intervals"].append(closed)
    result["events"] += 1
    result["last_event_at"] = max(timestamp(result["last_event_at"]), ended).astimezone(timezone.utc).isoformat()
    return validate_journal(result)


def _merged(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    result = [ordered[0]]
    for start_at, end_at in ordered[1:]:
        previous_start, previous_end = result[-1]
        if start_at <= previous_end:
            result[-1] = (previous_start, max(previous_end, end_at))
        else:
            result.append((start_at, end_at))
    return result


def _seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    total = 0.0
    for started, ended in _merged(intervals):
        total = finite_sum(total, (ended - started).total_seconds(), "duration")
    return round(total, 6)


def _overlap_seconds(
    left: list[tuple[datetime, datetime]], right: list[tuple[datetime, datetime]]
) -> float:
    left_merged, right_merged = _merged(left), _merged(right)
    left_index = right_index = 0
    total = 0.0
    while left_index < len(left_merged) and right_index < len(right_merged):
        left_start, left_end = left_merged[left_index]
        right_start, right_end = right_merged[right_index]
        overlap_start, overlap_end = max(left_start, right_start), min(left_end, right_end)
        if overlap_end > overlap_start:
            total = finite_sum(total, (overlap_end - overlap_start).total_seconds(), "overlap")
        if left_end <= right_end:
            left_index += 1
        else:
            right_index += 1
    return round(total, 6)


def _export_legacy(result: Mapping[str, Any]) -> dict[str, Any]:
    if result["open_phases"]:
        raise TrackerError(f"cannot export with open phases: {sorted(result['open_phases'])}")
    elapsed = (timestamp(result["last_event_at"]) - timestamp(result["created_at"])).total_seconds()
    return {
        "source_schema_version": LEGACY_SCHEMA_VERSION,
        "run_ref": result["run_ref"],
        "route": result["route"],
        "elapsed_seconds": round(elapsed, 6),
        "total_tokens": sum(result["phase_tokens"].values()) if result["phase_tokens"] else None,
        "credit_value": round(
            finite_mapping_sum(result["phase_credits"], "phase_credits"), 6
        ) if result["phase_credits"] else None,
        "phase_elapsed_seconds": result["phase_elapsed_seconds"],
        "phase_tokens": result["phase_tokens"],
        "phase_credits": result["phase_credits"],
        "elapsed_semantics": "legacy schema 1 wall-clock; no executor overlap metrics",
    }


def export(journal: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_journal(journal)
    if result.get("schema_version") == LEGACY_SCHEMA_VERSION:
        return _export_legacy(result)
    if result["open_intervals"]:
        ids = [item["interval_id"] for item in result["open_intervals"]]
        raise TrackerError(f"cannot export with open intervals: {ids}")
    phase_elapsed: dict[str, float] = {}
    phase_counts: dict[str, int] = {}
    phase_tokens: dict[str, int] = {}
    phase_credits: dict[str, float] = {}
    execution_by_executor: dict[str, list[tuple[datetime, datetime]]] = {}
    execution_by_actor: dict[str, list[tuple[datetime, datetime]]] = {"SOL": [], "LUNA": []}
    all_execution: list[tuple[datetime, datetime]] = []
    any_tokens = any(item["tokens"] is not None for item in result["phase_intervals"])
    any_credits = any(item["credits"] is not None for item in result["phase_intervals"])
    for item in result["phase_intervals"]:
        phase = item["phase"]
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        phase_elapsed[phase] = round(
            finite_sum(
                phase_elapsed.get(phase, 0.0), item["duration_seconds"],
                f"phase_elapsed_seconds[{phase}]",
            ),
            6,
        )
        if item["tokens"] is not None:
            phase_tokens[phase] = phase_tokens.get(phase, 0) + item["tokens"]
        if item["credits"] is not None:
            phase_credits[phase] = round(
                finite_sum(
                    phase_credits.get(phase, 0.0), item["credits"],
                    f"phase_credits[{phase}]",
                ),
                6,
            )
        if phase in EXECUTION_PHASES:
            pair = (timestamp(item["started_at"]), timestamp(item["ended_at"]))
            execution_by_executor.setdefault(item["executor_id"], []).append(pair)
            execution_by_actor[item["actor"]].append(pair)
            all_execution.append(pair)
    elapsed = (timestamp(result["last_event_at"]) - timestamp(result["created_at"])).total_seconds()
    return {
        "source_schema_version": SCHEMA_VERSION,
        "run_ref": result["run_ref"],
        "route": result["route"],
        "elapsed_seconds": round(elapsed, 6),
        "phase_intervals": result["phase_intervals"],
        "phase_interval_counts": dict(sorted(phase_counts.items())),
        "phase_elapsed_seconds": dict(sorted(phase_elapsed.items())),
        "phase_tokens": dict(sorted(phase_tokens.items())),
        "phase_credits": dict(sorted(phase_credits.items())),
        "total_tokens": sum(phase_tokens.values()) if any_tokens else None,
        "credit_value": round(
            finite_mapping_sum(phase_credits, "phase_credits"), 6
        ) if any_credits else None,
        "executor_execution_union_seconds": {
            executor_id: _seconds(intervals)
            for executor_id, intervals in sorted(execution_by_executor.items())
        },
        "execution_overlap_seconds": _overlap_seconds(
            execution_by_actor["SOL"], execution_by_actor["LUNA"]
        ),
        "execution_union_seconds": _seconds(all_execution),
        "elapsed_semantics": "wall-clock from creation to latest event; execution unions use half-open intervals",
    }


def run_command(
    journal_path: Path,
    phase: str,
    command: list[str],
    *,
    executor_id: str | None = None,
    actor: str | None = None,
    interval_id: str | None = None,
    tokens: int | None = None,
    credits: float | None = None,
) -> tuple[int, dict[str, Any]]:
    if not command:
        raise TrackerError("run requires a command after --")
    if executor_id is None:
        raise TrackerError("executor_id is required for run")
    # Validate all caller-supplied metrics before opening or persisting an
    # interval.  Otherwise a bad value would leave the journal open when the
    # final stop validation fails.
    if tokens is not None:
        non_negative_integer(tokens, "tokens")
    if credits is not None:
        finite(credits, "credits")
    with evidence_ledger.ledger_lock(journal_path):
        journal = _production(load(journal_path))
        chosen_interval = identifier(interval_id, "interval_id") if interval_id is not None else _next_interval_id(journal)
        journal = start(
            journal, phase, executor_id=executor_id, actor=actor, interval_id=chosen_interval
        )
        atomic_write(journal_path, journal)
    exit_code = 127
    launch_error: str | None = None
    try:
        completed = subprocess.run(command, check=False)
        exit_code = int(completed.returncode)
    except (OSError, ValueError) as exc:
        launch_error = str(exc).replace("\r", " ").replace("\n", " ")[:500]
    finally:
        with evidence_ledger.ledger_lock(journal_path):
            journal = stop(
                load(journal_path), phase, executor_id=executor_id,
                interval_id=chosen_interval, tokens=tokens, credits=credits,
                command_exit_code=exit_code, command_launch_error=launch_error,
            )
            atomic_write(journal_path, journal)
    output = export(journal)
    output["command_exit_code"] = exit_code
    output["command_launch_error"] = launch_error
    return exit_code, output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Track explicit Sol-Luna delivery intervals.")
    sub = result.add_subparsers(dest="subcommand", required=True)
    init = sub.add_parser("init")
    init.add_argument("--journal", required=True, type=Path)
    init.add_argument("--run-ref", required=True)
    init.add_argument("--route", required=True)
    init.add_argument("--at")
    for name in ("start", "stop"):
        command = sub.add_parser(name)
        command.add_argument("--journal", required=True, type=Path)
        command.add_argument("--phase", required=True)
        command.add_argument("--executor-id", required=True)
        if name == "start":
            command.add_argument("--actor", choices=("SOL", "LUNA"))
        command.add_argument("--interval-id")
        command.add_argument("--at")
        if name == "stop":
            command.add_argument("--tokens", type=int)
            command.add_argument("--credits", type=float)
    output = sub.add_parser("export")
    output.add_argument("--journal", required=True, type=Path)
    run = sub.add_parser("run")
    run.add_argument("--journal", required=True, type=Path)
    run.add_argument("--phase", required=True)
    run.add_argument("--executor-id", required=True)
    run.add_argument("--actor", choices=("SOL", "LUNA"))
    run.add_argument("--interval-id")
    run.add_argument("--tokens", type=int)
    run.add_argument("--credits", type=float)
    run.add_argument("run_argv", nargs=argparse.REMAINDER)
    return result


def main() -> int:
    args = parser().parse_args()
    exit_code = 0
    try:
        if args.subcommand == "init":
            with evidence_ledger.ledger_lock(args.journal):
                if args.journal.exists():
                    raise TrackerError("journal already exists")
                journal = initialize(args.run_ref, args.route, at=args.at)
                atomic_write(args.journal, journal)
            output = journal
        elif args.subcommand == "export":
            output = export(load(args.journal))
        elif args.subcommand == "run":
            command = list(args.run_argv)
            if command and command[0] == "--":
                command = command[1:]
            exit_code, output = run_command(
                args.journal, args.phase, command, executor_id=args.executor_id,
                actor=args.actor, interval_id=args.interval_id,
                tokens=args.tokens, credits=args.credits,
            )
        else:
            with evidence_ledger.ledger_lock(args.journal):
                journal = load(args.journal)
                if args.subcommand == "start":
                    journal = start(
                        journal, args.phase, executor_id=args.executor_id,
                        actor=args.actor, interval_id=args.interval_id, at=args.at,
                    )
                else:
                    journal = stop(
                        journal, args.phase, executor_id=args.executor_id,
                        interval_id=args.interval_id, at=args.at,
                        tokens=args.tokens, credits=args.credits,
                    )
                atomic_write(args.journal, journal)
            output = journal
    except (OSError, TrackerError, evidence_ledger.LedgerError) as exc:
        print(f"phase tracker error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

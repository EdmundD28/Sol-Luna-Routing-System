#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Collect phase elapsed time and optional source readings for one explicit run."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import evidence_ledger


SCHEMA_VERSION = 1
PHASES = evidence_ledger.PHASES
JOURNAL_FIELDS = frozenset(
    {
        "schema_version",
        "run_ref",
        "route",
        "created_at",
        "last_event_at",
        "open_phases",
        "phase_elapsed_seconds",
        "phase_tokens",
        "phase_credits",
        "events",
    }
)


class TrackerError(ValueError):
    """A phase journal event is invalid or inconsistent."""


def timestamp(value: str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise TrackerError("timestamp must be ISO-8601")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise TrackerError("timestamp must be ISO-8601") from exc
    if result.tzinfo is None:
        raise TrackerError("timestamp must include a timezone")
    return result


def finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise TrackerError(f"{field} must be a finite non-negative number")
    return float(value)


def atomic_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        temporary = Path(handle.name)
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def initialize(run_ref: str, route: str, *, at: str | None = None) -> dict[str, Any]:
    if route not in evidence_ledger.ROUTES:
        raise TrackerError(f"route must be one of {sorted(evidence_ledger.ROUTES)}")
    if not isinstance(run_ref, str) or not run_ref.strip():
        raise TrackerError("run_ref is required")
    created = timestamp(at)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_ref": evidence_ledger.redacted_ref(run_ref.strip()),
        "route": route,
        "created_at": created.astimezone(timezone.utc).isoformat(),
        "last_event_at": created.astimezone(timezone.utc).isoformat(),
        "open_phases": {},
        "phase_elapsed_seconds": {},
        "phase_tokens": {},
        "phase_credits": {},
        "events": 0,
    }


def _validate_route_phases(route: str, field: str, phases: Mapping[str, Any]) -> None:
    forbidden = "luna_execution" if route == "SOL_ONLY" else "sol_execution"
    if forbidden in phases:
        raise TrackerError(f"{route} journal cannot contain {forbidden} in {field}")


def validate_journal(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise TrackerError("phase journal must be a JSON object")
    unknown = set(source) - JOURNAL_FIELDS
    if unknown:
        raise TrackerError(f"phase journal contains unsupported fields: {sorted(unknown)}")
    if not isinstance(source, Mapping) or source.get("schema_version") != SCHEMA_VERSION:
        raise TrackerError("unsupported phase journal schema")
    journal = deepcopy(dict(source))
    if journal.get("route") not in evidence_ledger.ROUTES:
        raise TrackerError("invalid journal route")
    if not isinstance(journal.get("run_ref"), str) or not journal["run_ref"].startswith("redacted:run:"):
        raise TrackerError("journal run_ref must be redacted")
    created = timestamp(journal.get("created_at"))
    last_event = timestamp(journal.get("last_event_at"))
    if last_event < created:
        raise TrackerError("last event precedes journal creation")
    elapsed_seconds = (last_event - created).total_seconds()
    for field in ("open_phases", "phase_elapsed_seconds", "phase_tokens", "phase_credits"):
        if not isinstance(journal.get(field), dict):
            raise TrackerError(f"{field} must be a JSON object")
        if set(journal[field]) - PHASES:
            raise TrackerError(f"{field} contains an unsupported phase")
        _validate_route_phases(journal["route"], field, journal[field])

    events = journal.get("events")
    if isinstance(events, bool) or not isinstance(events, int) or events < 0:
        raise TrackerError("events must be a non-negative integer")

    for phase, value in journal["open_phases"].items():
        started = timestamp(value)
        if started < created:
            raise TrackerError(f"open phase start precedes journal creation: {phase}")
        if started > last_event:
            raise TrackerError(f"open phase start follows the latest journal event: {phase}")

    for phase, value in journal["phase_elapsed_seconds"].items():
        duration = finite(value, f"phase_elapsed_seconds[{phase}]")
        if duration > elapsed_seconds + 1e-6:
            raise TrackerError(f"phase_elapsed_seconds[{phase}] exceeds journal elapsed time")

    for phase, value in journal["phase_tokens"].items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TrackerError(f"phase_tokens[{phase}] must be a non-negative integer")

    for phase, value in journal["phase_credits"].items():
        finite(value, f"phase_credits[{phase}]")

    elapsed_phases = set(journal["phase_elapsed_seconds"])
    for field in ("phase_tokens", "phase_credits"):
        orphaned = set(journal[field]) - elapsed_phases
        if orphaned:
            raise TrackerError(f"{field} has no elapsed phase: {sorted(orphaned)}")
    return journal


def load(path: Path) -> dict[str, Any]:
    try:
        return validate_journal(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrackerError(f"cannot read phase journal: {exc}") from exc


def start(journal: Mapping[str, Any], phase: str, *, at: str | None = None) -> dict[str, Any]:
    result = validate_journal(journal)
    if phase not in PHASES:
        raise TrackerError(f"unsupported phase: {phase}")
    _validate_route_phases(result["route"], "phase", {phase: None})
    if phase in result["open_phases"]:
        raise TrackerError(f"phase is already open: {phase}")
    started = timestamp(at)
    if started < timestamp(result["last_event_at"]):
        raise TrackerError("phase start precedes the latest journal event")
    result["open_phases"][phase] = started.astimezone(timezone.utc).isoformat()
    result["last_event_at"] = started.astimezone(timezone.utc).isoformat()
    result["events"] = int(result.get("events", 0)) + 1
    return result


def stop(
    journal: Mapping[str, Any],
    phase: str,
    *,
    at: str | None = None,
    tokens: int | None = None,
    credits: float | None = None,
) -> dict[str, Any]:
    result = validate_journal(journal)
    if phase not in result["open_phases"]:
        raise TrackerError(f"phase is not open: {phase}")
    started = timestamp(str(result["open_phases"].pop(phase)))
    ended = timestamp(at)
    seconds = (ended - started).total_seconds()
    if seconds < 0:
        raise TrackerError("phase end precedes phase start")
    if ended < timestamp(result["last_event_at"]):
        raise TrackerError("phase end precedes the latest journal event")
    result["last_event_at"] = ended.astimezone(timezone.utc).isoformat()
    result["phase_elapsed_seconds"][phase] = round(
        float(result["phase_elapsed_seconds"].get(phase, 0)) + seconds, 6
    )
    if tokens is not None:
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            raise TrackerError("tokens must be a non-negative integer")
        result["phase_tokens"][phase] = int(result["phase_tokens"].get(phase, 0)) + tokens
    if credits is not None:
        amount = finite(credits, "credits")
        result["phase_credits"][phase] = round(float(result["phase_credits"].get(phase, 0)) + amount, 6)
    result["events"] = int(result.get("events", 0)) + 1
    return result


def export(journal: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_journal(journal)
    if result["open_phases"]:
        raise TrackerError(f"cannot export with open phases: {sorted(result['open_phases'])}")
    elapsed = (timestamp(result["last_event_at"]) - timestamp(result["created_at"])).total_seconds()
    return {
        "run_ref": result["run_ref"],
        "route": result["route"],
        "elapsed_seconds": round(elapsed, 6),
        "total_tokens": sum(int(value) for value in result["phase_tokens"].values()) if result["phase_tokens"] else None,
        "credit_value": round(sum(float(value) for value in result["phase_credits"].values()), 6)
        if result["phase_credits"]
        else None,
        "phase_elapsed_seconds": result["phase_elapsed_seconds"],
        "phase_tokens": result["phase_tokens"],
        "phase_credits": result["phase_credits"],
        "elapsed_semantics": "wall-clock from journal creation to latest event; phase active durations may overlap",
    }


def run_command(
    journal_path: Path,
    phase: str,
    command: list[str],
    *,
    tokens: int | None = None,
    credits: float | None = None,
) -> tuple[int, dict[str, Any]]:
    if not command:
        raise TrackerError("run requires a command after --")
    with evidence_ledger.ledger_lock(journal_path):
        journal = start(load(journal_path), phase)
        atomic_write(journal_path, journal)
    exit_code = 127
    launch_error: str | None = None
    try:
        completed = subprocess.run(command, check=False)
        exit_code = int(completed.returncode)
    except OSError as exc:
        launch_error = str(exc)
    finally:
        with evidence_ledger.ledger_lock(journal_path):
            journal = stop(load(journal_path), phase, tokens=tokens, credits=credits)
            atomic_write(journal_path, journal)
    output = export(journal)
    output["command_exit_code"] = exit_code
    output["command_launch_error"] = launch_error
    return exit_code, output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Track explicit Sol-Luna delivery phases.")
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
        command.add_argument("--at")
        if name == "stop":
            command.add_argument("--tokens", type=int)
            command.add_argument("--credits", type=float)
    output = sub.add_parser("export")
    output.add_argument("--journal", required=True, type=Path)
    run = sub.add_parser("run")
    run.add_argument("--journal", required=True, type=Path)
    run.add_argument("--phase", required=True)
    run.add_argument("--tokens", type=int)
    run.add_argument("--credits", type=float)
    run.add_argument("run_argv", nargs=argparse.REMAINDER)
    return result


def main() -> int:
    args = parser().parse_args()
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
                args.journal,
                args.phase,
                command,
                tokens=args.tokens,
                credits=args.credits,
            )
        else:
            with evidence_ledger.ledger_lock(args.journal):
                journal = load(args.journal)
                if args.subcommand == "start":
                    journal = start(journal, args.phase, at=args.at)
                else:
                    journal = stop(
                        journal,
                        args.phase,
                        at=args.at,
                        tokens=args.tokens,
                        credits=args.credits,
                    )
                atomic_write(args.journal, journal)
            output = journal
    except (OSError, TrackerError, evidence_ledger.LedgerError) as exc:
        print(f"phase tracker error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code if args.subcommand == "run" else 0


if __name__ == "__main__":
    raise SystemExit(main())

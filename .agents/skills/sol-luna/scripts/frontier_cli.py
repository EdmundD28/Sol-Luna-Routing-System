#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Command-line interface for the replay-only rolling frontier planner."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


PLANNER_PATH = Path(__file__).with_name("frontier_planner.py")
SPEC = importlib.util.spec_from_file_location("sol_luna_frontier_planner", PLANNER_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery invariant
    raise RuntimeError("cannot load sibling frontier planner")
PLANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLANNER)
FrontierError = PLANNER.FrontierError


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FrontierError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise FrontierError(f"non-finite JSON constant is not allowed: {value}")


def _load_json(path: str) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FrontierError(f"cannot read input file: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise FrontierError(f"invalid JSON: {exc}") from exc


def _emit(value: Any) -> None:
    serialized = (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        + "\n"
    )
    binary = getattr(sys.stdout, "buffer", None)
    if binary is None:
        sys.stdout.write(serialized)
    else:
        binary.write(serialized.encode("utf-8"))


def _single_line(message: Any) -> str:
    return " ".join(str(message).splitlines()) or "unknown error"


def _emit_error(message: Any) -> None:
    serialized = f"frontier error: {_single_line(message)}\n"
    binary = getattr(sys.stderr, "buffer", None)
    if binary is None:
        sys.stderr.write(serialized)
    else:
        binary.write(serialized.encode("utf-8", errors="replace"))


def main(argv=None) -> int:
    """Run the strict two-command CLI, returning 0 on success and 2 on error."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["template"]:
            output = PLANNER.template()
        elif len(arguments) == 3 and arguments[:2] == ["evaluate", "--input"]:
            if not isinstance(arguments[2], str) or not arguments[2]:
                raise FrontierError("input file path must be non-empty")
            output = PLANNER.plan(_load_json(arguments[2]))
        else:
            raise FrontierError(
                "invalid arguments; expected 'template' or 'evaluate --input FILE'"
            )
        _emit(output)
        return 0
    except (FrontierError, OSError, UnicodeError, TypeError, ValueError) as exc:
        _emit_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

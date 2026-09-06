#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Command-line interface for the replay-only rolling frontier planner."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


class FrontierCliError(ValueError):
    """The command line or serialized input cannot be processed safely."""


def _load_planner() -> ModuleType:
    path = Path(__file__).with_name("frontier_planner.py")
    try:
        spec = importlib.util.spec_from_file_location("sol_luna_frontier_planner", path)
        if spec is None or spec.loader is None:
            raise ImportError("no module loader")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not callable(getattr(module, "template", None)) or not callable(
            getattr(module, "plan", None)
        ):
            raise ImportError("planner interface is incomplete")
        return module
    except Exception as exc:
        raise FrontierCliError(f"cannot load sibling frontier planner: {exc}") from exc


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FrontierCliError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise FrontierCliError(f"non-finite JSON constant is not allowed: {value}")


def _load_json(path: str) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FrontierCliError(f"cannot read input file: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise FrontierCliError(f"invalid JSON: {exc}") from exc


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
        planner = None
        if arguments == ["template"]:
            planner = _load_planner()
            output = planner.template()
        elif len(arguments) == 3 and arguments[:2] == ["evaluate", "--input"]:
            if not isinstance(arguments[2], str) or not arguments[2]:
                raise FrontierCliError("input file path must be non-empty")
            planner = _load_planner()
            output = planner.plan(_load_json(arguments[2]))
        else:
            raise FrontierCliError(
                "invalid arguments; expected 'template' or 'evaluate --input FILE'"
            )
        _emit(output)
        return 0
    except (FrontierCliError, OSError, UnicodeError, TypeError, ValueError) as exc:
        _emit_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

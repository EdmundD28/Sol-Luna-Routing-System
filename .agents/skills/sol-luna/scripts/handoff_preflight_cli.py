#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Command-line interface for candidate-bound handoff preflight."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any


class PreflightCliError(ValueError):
    """The command line or serialized input cannot be processed safely."""


def _load_preflight() -> ModuleType:
    path = Path(__file__).with_name("handoff_preflight.py")
    try:
        spec = importlib.util.spec_from_file_location("sol_luna_handoff_preflight", path)
        if spec is None or spec.loader is None:
            raise ImportError("no module loader")
        module = importlib.util.module_from_spec(spec)
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            spec.loader.exec_module(module)
        if captured_stdout.getvalue() or captured_stderr.getvalue():
            raise ImportError("preflight import produced output")
        if not callable(getattr(module, "template", None)) or not callable(
            getattr(module, "evaluate", None)
        ):
            raise ImportError("preflight interface is incomplete")
        return module
    except Exception as exc:
        raise PreflightCliError(f"cannot load sibling handoff preflight: {exc}") from exc


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreflightCliError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise PreflightCliError(f"non-finite JSON constant is not allowed: {value}")


def _load_json(path: str) -> Any:
    try:
        serialized = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PreflightCliError(f"cannot read input file: {exc}") from exc
    try:
        return json.loads(
            serialized,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise PreflightCliError(f"invalid JSON: {exc}") from exc


def _emit(value: Any) -> None:
    serialized = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
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
    serialized = f"handoff preflight error: {_single_line(message)}\n"
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
            output = _load_preflight().template()
        elif len(arguments) == 3 and arguments[:2] == ["evaluate", "--input"]:
            if not isinstance(arguments[2], str) or not arguments[2]:
                raise PreflightCliError("input file path must be non-empty")
            output = _load_preflight().evaluate(_load_json(arguments[2]))
        else:
            raise PreflightCliError(
                "invalid arguments; expected 'template' or 'evaluate --input FILE'"
            )
        _emit(output)
        return 0
    except (PreflightCliError, OSError, UnicodeError, TypeError, ValueError) as exc:
        _emit_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

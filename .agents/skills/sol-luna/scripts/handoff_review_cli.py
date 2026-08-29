#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Strict command-line interface for read-only handoff review."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import importlib.util
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any


class ReviewCliError(ValueError):
    """The CLI request cannot be processed safely."""


def _load_sibling(filename: str, module_name: str, required: tuple[str, ...]) -> ModuleType:
    path = Path(__file__).with_name(filename)
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError("no module loader")
        module = importlib.util.module_from_spec(spec)
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            spec.loader.exec_module(module)
        if captured_stdout.getvalue() or captured_stderr.getvalue():
            raise ImportError("sibling import produced output")
        if any(not callable(getattr(module, name, None)) for name in required):
            raise ImportError("sibling interface is incomplete")
        return module
    except BaseException as exc:
        if isinstance(exc, ReviewCliError):
            raise
        raise ReviewCliError(f"cannot load sibling module {filename}: {_safe_text(exc)}") from exc


def _safe_text(value: Any) -> str:
    try:
        text = str(value)
    except BaseException:
        text = type(value).__name__
    return " ".join(text.splitlines()) or type(value).__name__


def _write(stream: Any, serialized: str, *, errors: str = "strict") -> None:
    binary = getattr(stream, "buffer", None)
    if binary is None:
        stream.write(serialized)
    else:
        binary.write(serialized.encode("utf-8", errors=errors))


def _error(message: Any) -> None:
    _write(sys.stderr, f"error: {_safe_text(message)}\n", errors="replace")


def main(argv: Any = None) -> int:
    """Run one exact command, returning status 0 or 2."""
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if any(not isinstance(argument, str) for argument in arguments):
            raise ReviewCliError("arguments must be strings")
        if arguments == ["template"]:
            review = _load_sibling(
                "handoff_review.py", "sol_luna_handoff_review", ("template", "compile_portfolio", "compare")
            )
            output = review.template()
        elif len(arguments) == 3 and arguments[:2] == ["compile", "--input"]:
            if not arguments[2]:
                raise ReviewCliError("input file path must be non-empty")
            review = _load_sibling(
                "handoff_review.py", "sol_luna_handoff_review", ("template", "compile_portfolio", "compare")
            )
            transport = _load_sibling(
                "handoff_review_json.py", "sol_luna_handoff_review_json", ("load_file", "dumps")
            )
            output = review.compile_portfolio(transport.load_file(arguments[2]))
        elif len(arguments) == 5 and arguments[0:2] == ["compare", "--before"] and arguments[3] == "--after":
            if not arguments[2] or not arguments[4]:
                raise ReviewCliError("snapshot file paths must be non-empty")
            review = _load_sibling(
                "handoff_review.py", "sol_luna_handoff_review", ("template", "compile_portfolio", "compare")
            )
            transport = _load_sibling(
                "handoff_review_json.py", "sol_luna_handoff_review_json", ("load_file", "dumps")
            )
            output = review.compare(
                transport.load_file(arguments[2]), transport.load_file(arguments[4])
            )
        else:
            raise ReviewCliError(
                "invalid arguments; expected 'template', 'compile --input FILE', or "
                "'compare --before FILE --after FILE'"
            )

        if arguments == ["template"]:
            transport = _load_sibling(
                "handoff_review_json.py", "sol_luna_handoff_review_json", ("load_file", "dumps")
            )
        serialized = transport.dumps(output)
        _write(sys.stdout, serialized)
        return 0
    except BaseException as exc:
        try:
            _error(exc)
        except BaseException:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Command-line transport for replay-only handoff portfolio review."""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence


# This assignment must precede every import of a sibling implementation.
sys.dont_write_bytecode = True


class CliError(ValueError):
    """The command line or a sibling operation cannot be processed safely."""


def _load_module(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise CliError(f"cannot load sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_siblings() -> tuple[ModuleType, ModuleType]:
    # Keep this inside the caller's redirected streams: a malformed or noisy
    # sibling must never leak output into the CLI protocol.
    transport = _load_module(
        "handoff_review_json.py", "sol_luna_handoff_review_json_cli"
    )
    review = _load_module("handoff_review.py", "sol_luna_handoff_review_cli")
    if not callable(getattr(transport, "load_file", None)) or not callable(
        getattr(transport, "dumps", None)
    ):
        raise CliError("JSON transport interface is incomplete")
    if not callable(getattr(review, "template", None)) or not callable(
        getattr(review, "compile_portfolio", None)
    ) or not callable(getattr(review, "compare", None)):
        raise CliError("handoff review interface is incomplete")
    return transport, review


def _parse_arguments(arguments: Sequence[Any]) -> tuple[str, str | None, str | None]:
    if list(arguments) == ["template"]:
        return "template", None, None
    if len(arguments) == 3 and list(arguments[:2]) == ["compile", "--input"]:
        if not isinstance(arguments[2], str) or not arguments[2]:
            raise CliError("input file path must be non-empty")
        return "compile", arguments[2], None
    if (
        len(arguments) == 5
        and list(arguments[:2]) == ["compare", "--before"]
        and arguments[3] == "--after"
    ):
        before, after = arguments[2], arguments[4]
        if not isinstance(before, str) or not before:
            raise CliError("before file path must be non-empty")
        if not isinstance(after, str) or not after:
            raise CliError("after file path must be non-empty")
        return "compare", before, after
    raise CliError(
        "invalid arguments; expected 'template', "
        "'compile --input FILE', or 'compare --before FILE --after FILE'"
    )


def _write_stdout(serialized: str) -> None:
    binary = getattr(sys.stdout, "buffer", None)
    if binary is None:
        sys.stdout.write(serialized)
    else:
        binary.write(serialized.encode("utf-8"))


def _single_line(message: Any) -> str:
    text = str(message).replace("\r", " ").replace("\n", " ").strip()
    return text or "unknown error"


def _write_error(message: Any) -> None:
    serialized = f"error: {_single_line(message)}\n"
    binary = getattr(sys.stderr, "buffer", None)
    if binary is None:
        sys.stderr.write(serialized)
    else:
        binary.write(serialized.encode("utf-8", errors="replace"))


def main(argv: Sequence[Any] | None = None) -> int:
    """Run the strict CLI, returning 0 on success and 2 on any failure."""

    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        command, first_path, second_path = _parse_arguments(arguments)

        # Capture all sibling import and execution output.  The public wire
        # contract permits only the serialized result on stdout and no stderr.
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            transport, review = _load_siblings()
            if command == "template":
                result = review.template()
            elif command == "compile":
                result = review.compile_portfolio(transport.load_file(first_path))
            else:
                result = review.compare(
                    transport.load_file(first_path),
                    transport.load_file(second_path),
                )
            serialized = transport.dumps(result)
        _write_stdout(serialized)
        return 0
    except BaseException as exc:
        # Deliberately include SystemExit and KeyboardInterrupt from sibling
        # imports/operations: the CLI is a closed protocol, not an interactive
        # Python shell.
        _write_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CliError", "main"]

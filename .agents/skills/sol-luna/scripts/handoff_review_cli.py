#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Strict command-line transport for the read-only handoff review API."""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

# This assignment must precede every import of a sibling module.  In
# particular, the dynamically loaded transport and review modules must never
# leave a __pycache__ behind during a CLI invocation.
sys.dont_write_bytecode = True


class CliError(ValueError):
    """The command line, sibling module, or input cannot be processed."""


def _load_sibling(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).with_name(filename)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"no loader for {filename}")
        module = importlib.util.module_from_spec(spec)
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            spec.loader.exec_module(module)
        if captured_stdout.getvalue() or captured_stderr.getvalue():
            raise ImportError(f"{filename} import produced output")
        return module
    except BaseException as exc:
        # Import-time SystemExit and KeyboardInterrupt are transport failures,
        # not reasons to leak a traceback or a non-standard process status.
        if isinstance(exc, CliError):
            raise
        detail = str(exc).strip() or type(exc).__name__
        raise CliError(f"cannot load sibling {filename}: {detail}") from exc


def _module_function(module: ModuleType, name: str):
    function = getattr(module, name, None)
    if not callable(function):
        raise CliError(f"sibling module is missing callable {name}")
    return function


def _call_silently(function, *arguments: Any) -> Any:
    """Call user-facing sibling code without allowing incidental output."""

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    try:
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            result = function(*arguments)
    except BaseException as exc:
        if isinstance(exc, CliError):
            raise
        detail = str(exc).strip() or type(exc).__name__
        raise CliError(detail) from exc
    if captured_stdout.getvalue() or captured_stderr.getvalue():
        raise CliError("sibling operation produced output")
    return result


def _write(stream: Any, text: str, *, replace_encoding_errors: bool = False) -> None:
    encoded = text.encode(
        "utf-8", errors="replace" if replace_encoding_errors else "strict"
    )
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        binary.write(encoded)
    else:
        stream.write(text)


def _single_line(message: Any) -> str:
    text = str(message)
    # splitlines handles CR, LF, and the Unicode line separators.  Joining
    # makes the error contract exactly one physical line.
    return " ".join(text.splitlines()) or "unknown error"


def _emit_error(message: Any) -> None:
    try:
        _write(
            sys.stderr,
            f"error: {_single_line(message)}\n",
            replace_encoding_errors=True,
        )
    except BaseException:
        # A normal stderr stream should not fail, but do not turn an error
        # report into an unhandled exception if a host replaces it.
        try:
            sys.stderr.write("error: unknown error\n")
        except BaseException:
            pass


def _arguments(argv: Sequence[Any] | None) -> list[str]:
    raw = list(sys.argv[1:] if argv is None else argv)
    if any(not isinstance(item, str) for item in raw):
        raise CliError("arguments must be strings")
    return raw


def main(argv: Sequence[Any] | None = None) -> int:
    """Run the exact template, compile, and compare command set."""

    try:
        arguments = _arguments(argv)

        # Validate the grammar before loading either sibling.  This keeps a
        # malformed invocation independent of the repository modules and
        # makes the no-import failure path deterministic.
        command = None
        if arguments == ["template"]:
            command = "template"
        elif len(arguments) == 3 and arguments[:2] == ["compile", "--input"]:
            if not arguments[2]:
                raise CliError("input file path must be non-empty")
            command = "compile"
        elif (
            len(arguments) == 5
            and arguments[:2] == ["compare", "--before"]
            and arguments[3] == "--after"
        ):
            if not arguments[2] or not arguments[4]:
                raise CliError("input file paths must be non-empty")
            command = "compare"
        else:
            raise CliError(
                "invalid arguments; expected 'template', 'compile --input FILE', "
                "or 'compare --before FILE --after FILE'"
            )

        transport = _load_sibling("handoff_review_json.py", "sol_luna_handoff_review_json")
        load_file = _module_function(transport, "load_file")
        dumps = _module_function(transport, "dumps")

        if command == "template":
            review = _load_sibling("handoff_review.py", "sol_luna_handoff_review")
            result = _call_silently(_module_function(review, "template"))
        elif command == "compile":
            review = _load_sibling("handoff_review.py", "sol_luna_handoff_review")
            source = _call_silently(load_file, arguments[2])
            result = _call_silently(_module_function(review, "compile_portfolio"), source)
        else:
            review = _load_sibling("handoff_review.py", "sol_luna_handoff_review")
            before = _call_silently(load_file, arguments[2])
            after = _call_silently(load_file, arguments[4])
            result = _call_silently(_module_function(review, "compare"), before, after)

        serialized = _call_silently(dumps, result)
        if not isinstance(serialized, str) or not serialized.endswith("\n"):
            raise CliError("JSON transport returned invalid serialized output")
        _write(sys.stdout, serialized)
        return 0
    except BaseException as exc:
        # This deliberately includes SystemExit and KeyboardInterrupt from
        # sibling imports or operations: the CLI's public failure channel is
        # always status 2, empty stdout, and one error line.
        _emit_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

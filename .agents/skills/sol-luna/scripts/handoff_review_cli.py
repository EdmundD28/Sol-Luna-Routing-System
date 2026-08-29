#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Strict command-line transport for the replay-only handoff review tool."""

from __future__ import annotations

import sys

# This must be set before either sibling module is loaded.  The CLI is also
# deliberately free of argparse so malformed argument handling stays uniform.
sys.dont_write_bytecode = True

import importlib.util
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any


class HandoffReviewCliError(ValueError):
    """The command line or a sibling module could not be processed safely."""


def _load_sibling(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise HandoffReviewCliError(f"cannot load sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
        spec.loader.exec_module(module)
    if captured_stdout.getvalue() or captured_stderr.getvalue():
        raise HandoffReviewCliError(f"sibling import produced output: {filename}")
    return module


def _load_modules() -> tuple[ModuleType, ModuleType]:
    review = _load_sibling("handoff_review.py", "sol_luna_handoff_review")
    transport = _load_sibling("handoff_review_json.py", "sol_luna_handoff_review_json")
    if not callable(getattr(review, "template", None)) or not callable(
        getattr(review, "compile_portfolio", None)
    ) or not callable(getattr(review, "compare", None)):
        raise HandoffReviewCliError("handoff review interface is incomplete")
    if not callable(getattr(transport, "load_file", None)) or not callable(
        getattr(transport, "dumps", None)
    ):
        raise HandoffReviewCliError("JSON transport interface is incomplete")
    return review, transport


def _emit(serialized: str) -> None:
    binary = getattr(sys.stdout, "buffer", None)
    if binary is None:
        sys.stdout.write(serialized)
    else:
        binary.write(serialized.encode("utf-8"))


def _single_line(message: Any) -> str:
    try:
        line = " ".join(str(message).splitlines())
    except BaseException:  # pragma: no cover - only hostile exception objects
        line = ""
    return line or "unknown error"


def _emit_error(message: Any) -> None:
    serialized = f"error: {_single_line(message)}\n"
    binary = getattr(sys.stderr, "buffer", None)
    if binary is None:
        sys.stderr.write(serialized)
    else:
        binary.write(serialized.encode("utf-8", errors="replace"))


def main(argv: Any = None) -> int:
    """Run the exact three-command interface, returning 0 or 2."""

    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        review, transport = _load_modules()
        if arguments == ["template"]:
            output = review.template()
        elif len(arguments) == 3 and arguments[0:2] == ["compile", "--input"]:
            if not isinstance(arguments[2], str) or not arguments[2]:
                raise HandoffReviewCliError("input file path must be non-empty")
            output = review.compile_portfolio(transport.load_file(arguments[2]))
        elif len(arguments) == 5 and arguments[0:2] == ["compare", "--before"] and arguments[3] == "--after":
            if not isinstance(arguments[2], str) or not arguments[2]:
                raise HandoffReviewCliError("before file path must be non-empty")
            if not isinstance(arguments[4], str) or not arguments[4]:
                raise HandoffReviewCliError("after file path must be non-empty")
            output = review.compare(
                transport.load_file(arguments[2]), transport.load_file(arguments[4])
            )
        else:
            raise HandoffReviewCliError(
                "invalid arguments; expected 'template', 'compile --input FILE', or "
                "'compare --before FILE --after FILE'"
            )
        serialized = transport.dumps(output)
        _emit(serialized)
        return 0
    except BaseException as exc:
        try:
            _emit_error(exc)
        except BaseException:
            # The contract still requires a non-empty error line.  This last
            # fallback is for unusual test doubles that reject normal writes.
            try:
                sys.stderr.write("error: unknown error\n")
            except BaseException:
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


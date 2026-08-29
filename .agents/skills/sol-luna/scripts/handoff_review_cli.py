#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict command-line transport for replay-only handoff review."""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any

sys.dont_write_bytecode = True


class CliError(ValueError):
    """The command, sibling import, input, or output is invalid."""


def _load_sibling(filename: str, module_name: str, functions: tuple[str, ...]) -> ModuleType:
    path = Path(__file__).with_name(filename)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError("no module loader")
        module = importlib.util.module_from_spec(spec)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            spec.loader.exec_module(module)
        if stdout.getvalue() or stderr.getvalue():
            raise ImportError("sibling import produced output")
        if any(not callable(getattr(module, function, None)) for function in functions):
            raise ImportError("sibling interface is incomplete")
        return module
    except BaseException as exc:
        raise CliError(f"cannot load sibling module {filename}: {exc}") from exc


def _error_text(value: Any) -> str:
    message = " ".join(str(value).split())
    return message or "unknown error"


def _write_stdout(value: str) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(value)
    else:
        stream.write(value.encode("utf-8"))


def _write_stderr(value: Any) -> None:
    serialized = f"error: {_error_text(value)}\n"
    stream = getattr(sys.stderr, "buffer", None)
    if stream is None:
        sys.stderr.write(serialized)
    else:
        stream.write(serialized.encode("utf-8", errors="replace"))


def main(argv: Any = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["template"]:
            review = _load_sibling("handoff_review.py", "sol_luna_handoff_review", ("template",))
            transport = _load_sibling("handoff_review_json.py", "sol_luna_handoff_review_json", ("dumps",))
            output = review.template()
        elif len(arguments) == 3 and arguments[:2] == ["compile", "--input"] and arguments[2]:
            review = _load_sibling("handoff_review.py", "sol_luna_handoff_review", ("compile_portfolio",))
            transport = _load_sibling("handoff_review_json.py", "sol_luna_handoff_review_json", ("load_file", "dumps"))
            output = review.compile_portfolio(transport.load_file(arguments[2]))
        elif len(arguments) == 5 and arguments[0] == "compare" and arguments[1] == "--before" and arguments[3] == "--after" and arguments[2] and arguments[4]:
            review = _load_sibling("handoff_review.py", "sol_luna_handoff_review", ("compare",))
            transport = _load_sibling("handoff_review_json.py", "sol_luna_handoff_review_json", ("load_file", "dumps"))
            output = review.compare(transport.load_file(arguments[2]), transport.load_file(arguments[4]))
        else:
            raise CliError("invalid arguments; expected 'template', 'compile --input FILE', or 'compare --before FILE --after FILE'")
        _write_stdout(transport.dumps(output))
        return 0
    except BaseException as exc:
        try:
            _write_stderr(exc)
        except BaseException:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CliError", "main"]

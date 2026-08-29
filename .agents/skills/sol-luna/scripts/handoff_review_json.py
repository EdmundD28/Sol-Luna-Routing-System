#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Strict JSON transport for handoff review."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class JsonTransportError(ValueError):
    """JSON input or output violates the strict transport contract."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonTransportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise JsonTransportError(f"non-finite JSON constant is not allowed: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise JsonTransportError("non-finite JSON number is not allowed")
    return parsed


def load_file(path: Any) -> Any:
    """Load one UTF-8 JSON file with duplicate and non-finite rejection."""
    try:
        serialized = Path(path).read_text(encoding="utf-8")
        return json.loads(
            serialized,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except JsonTransportError:
        raise
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ) as exc:
        raise JsonTransportError(f"cannot load JSON file: {exc}") from exc


def dumps(value: Any) -> str:
    """Return the exact strict pretty-printed JSON representation."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise JsonTransportError(f"cannot serialize JSON value: {exc}") from exc


__all__ = ["JsonTransportError", "dumps", "load_file"]

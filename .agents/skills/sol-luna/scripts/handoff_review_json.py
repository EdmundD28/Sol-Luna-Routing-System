#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict JSON transport for the handoff review tool."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class JsonTransportError(ValueError):
    """The JSON document cannot be safely loaded or serialized."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonTransportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise JsonTransportError(f"non-finite JSON constant is not allowed: {value}")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise JsonTransportError("non-finite JSON number is not allowed")
    return number


def load_file(path: str | Path) -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except JsonTransportError:
        raise
    except Exception as exc:
        raise JsonTransportError(f"cannot load JSON: {exc}") from exc


def dumps(value: Any) -> str:
    """Serialize exact sorted, UTF-8-friendly, two-space JSON with one LF."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    except (TypeError, ValueError, OverflowError) as exc:
        raise JsonTransportError(f"cannot serialize JSON: {exc}") from exc


__all__ = ["JsonTransportError", "load_file", "dumps"]

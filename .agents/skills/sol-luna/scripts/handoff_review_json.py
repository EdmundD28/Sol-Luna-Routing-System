#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Strict, side-effect-free JSON transport for handoff review records."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class JsonTransportError(ValueError):
    """The JSON document could not be read or serialized safely."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonTransportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise JsonTransportError(f"non-finite JSON constant is not allowed: {value}")


def _parse_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise JsonTransportError(f"non-finite JSON number is not allowed: {value}")
    return parsed


def load_file(path: str | bytes | Path) -> Any:
    """Read one UTF-8 JSON file using strict object and number handling.

    Filesystem, decoding, and JSON failures are deliberately exposed through
    one exception type so callers can provide one stable error channel.
    """

    try:
        serialized = Path(path).read_bytes().decode("utf-8")
        return json.loads(
            serialized,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
        )
    except JsonTransportError:
        raise
    except Exception as exc:
        raise JsonTransportError(f"cannot load JSON file: {exc}") from exc


def dumps(value: Any) -> str:
    """Serialize a value in the canonical CLI format, with one final LF."""

    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
    except Exception as exc:
        raise JsonTransportError(f"cannot serialize JSON: {exc}") from exc


__all__ = ["JsonTransportError", "load_file", "dumps"]

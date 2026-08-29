#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Strict JSON transport for the replay-only handoff review tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonTransportError(ValueError):
    """The JSON document could not be read or serialized safely."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonTransportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise JsonTransportError(f"non-finite JSON constant is not allowed: {value}")


def load_file(path: str | Path) -> Any:
    """Read one UTF-8 JSON file with duplicate-key and non-finite rejection."""

    try:
        serialized = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise JsonTransportError(f"cannot read JSON file: {exc}") from exc
    try:
        return json.loads(
            serialized,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except JsonTransportError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise JsonTransportError(f"invalid JSON: {exc}") from exc


def dumps(value: Any) -> str:
    """Serialize JSON deterministically with exactly one LF terminator."""

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
    except (TypeError, ValueError, OverflowError) as exc:
        raise JsonTransportError(f"cannot serialize JSON: {exc}") from exc


__all__ = ["JsonTransportError", "dumps", "load_file"]

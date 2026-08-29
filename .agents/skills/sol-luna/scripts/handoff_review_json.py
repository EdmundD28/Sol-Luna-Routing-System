#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Strict JSON transport for the handoff-review command line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonTransportError(ValueError):
    """A file, encoding, JSON, or serialization error."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonTransportError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise JsonTransportError(f"non-finite JSON constant is not allowed: {value}")


def load_file(path: str | Path) -> Any:
    """Read one UTF-8 JSON file, rejecting duplicate keys and non-finite values."""

    try:
        serialized = Path(path).read_text(encoding="utf-8")
    except Exception as exc:
        raise JsonTransportError(f"cannot read JSON file: {exc}") from exc
    try:
        return json.loads(
            serialized,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except JsonTransportError:
        raise
    except Exception as exc:
        raise JsonTransportError(f"invalid JSON: {exc}") from exc


def dumps(value: Any) -> str:
    """Serialize JSON deterministically with a two-space indent and one LF."""

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

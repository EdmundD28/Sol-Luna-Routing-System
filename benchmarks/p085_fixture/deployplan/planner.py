from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .model import Plan


def compile_plan(
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
    *,
    roots: tuple[str, ...] | None = None,
) -> Plan:
    raise NotImplementedError


def render_plan(plan: Plan) -> str:
    """Return canonical UTF-8-safe JSON with a trailing newline."""
    raise NotImplementedError

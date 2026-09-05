from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .model import Service


def normalize_name(value: object, *, path: str = "name") -> str:
    raise NotImplementedError


def parse_manifest(raw: Mapping[str, Any]) -> tuple[Service, ...]:
    raise NotImplementedError

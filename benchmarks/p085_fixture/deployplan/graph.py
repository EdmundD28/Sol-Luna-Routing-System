from __future__ import annotations

from collections.abc import Iterable

from .model import Service


def dependency_order(services: Iterable[Service]) -> tuple[Service, ...]:
    """Return dependencies before dependants with lexical tie-breaking."""
    raise NotImplementedError


def dependency_closure(
    services: Iterable[Service], roots: Iterable[str]
) -> tuple[Service, ...]:
    """Return normalized roots and their dependencies in dependency order."""
    raise NotImplementedError

from __future__ import annotations

from collections.abc import Iterable

from .model import Operation, Service


def diff_services(
    current: Iterable[Service], desired: Iterable[Service]
) -> tuple[Operation, ...]:
    """Return removals, then additions/updates, in safe dependency order."""
    raise NotImplementedError

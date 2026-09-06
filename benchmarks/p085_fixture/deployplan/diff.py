from __future__ import annotations

from collections.abc import Iterable

from .errors import ManifestError
from .graph import dependency_order
from .model import Operation, Service


def diff_services(
    current: Iterable[Service], desired: Iterable[Service]
) -> tuple[Operation, ...]:
    """Return removals, then additions/updates, in safe dependency order."""
    current_order = dependency_order(current)
    desired_order = dependency_order(desired)
    return _diff_ordered(current_order, desired_order)


def _diff_ordered(
    current_order: tuple[Service, ...],
    desired_order: tuple[Service, ...],
    *,
    scope: set[str] | None = None,
) -> tuple[Operation, ...]:
    current_map = {service.name: service for service in current_order}
    desired_map = {service.name: service for service in desired_order}
    if scope is None:
        current_names = set(current_map)
        desired_names = set(desired_map)
    else:
        current_names = set(current_map).intersection(scope)
        desired_names = set(desired_map).intersection(scope)
    operations: list[Operation] = []
    for service in reversed(current_order):
        if service.name in current_names and service.name not in desired_names:
            operations.append(Operation("remove", service.name, service, None))
    for service in desired_order:
        if service.name not in desired_names:
            continue
        before = current_map.get(service.name)
        if before is None:
            operations.append(Operation("add", service.name, None, service))
        elif before != service:
            operations.append(Operation("update", service.name, before, service))
    return tuple(operations)

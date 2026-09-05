from __future__ import annotations

from collections.abc import Iterable

from .graph import dependency_order
from .model import Operation, Service


def diff_services(
    current: Iterable[Service], desired: Iterable[Service]
) -> tuple[Operation, ...]:
    """Return removals, then additions/updates, in safe dependency order."""
    current_items = tuple(current)
    desired_items = tuple(desired)
    current_order = dependency_order(current_items)
    desired_order = dependency_order(desired_items)
    current_by_name = {item.name: item for item in current_items}
    desired_by_name = {item.name: item for item in desired_items}
    operations: list[Operation] = []
    for item in reversed(current_order):
        if item.name not in desired_by_name:
            operations.append(Operation("remove", item.name, item, None))
    for item in desired_order:
        before = current_by_name.get(item.name)
        if before is None:
            operations.append(Operation("add", item.name, None, item))
        elif before != item:
            operations.append(Operation("update", item.name, before, item))
    return tuple(operations)

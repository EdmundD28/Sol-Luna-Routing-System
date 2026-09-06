from __future__ import annotations

from collections.abc import Iterable

from .model import Operation, Service

def with_restarts(current: Iterable[Service], desired: Iterable[Service], operations: Iterable[Operation]) -> tuple[Operation, ...]:
    current_items = tuple(current)
    desired_items = tuple(desired)
    ordinary = tuple(operations)
    changed = {operation.name for operation in ordinary}
    desired_map = {service.name: service for service in desired_items}
    dependants = {service.name: [] for service in desired_items}
    for service in desired_items:
        for dependency in service.depends_on:
            if dependency in dependants:
                dependants[dependency].append(service.name)
    marked: set[str] = set()
    pending = list(changed.intersection(desired_map))
    while pending:
        name = pending.pop()
        for dependant in dependants.get(name, ()):
            if dependant not in marked and dependant not in changed:
                marked.add(dependant)
                pending.append(dependant)
    already = changed | {operation.name for operation in ordinary}
    restarts = [Operation("restart", name, desired_map[name], desired_map[name]) for name in marked if name not in already]
    removals = tuple(operation for operation in ordinary if operation.kind == "remove")
    forwards = tuple(operation for operation in ordinary if operation.kind != "remove")
    desired_order = {service.name: index for index, service in enumerate(desired_items)}
    restarts.sort(key=lambda operation: desired_order[operation.name])
    # Merge forward operations and restarts in final dependency order.
    forward_by_name = {operation.name: operation for operation in forwards}
    restart_by_name = {operation.name: operation for operation in restarts}
    merged = tuple(forward_by_name.get(service.name) or restart_by_name[service.name] for service in desired_items if service.name in forward_by_name or service.name in restart_by_name)
    return removals + merged


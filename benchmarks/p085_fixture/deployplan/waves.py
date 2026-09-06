from __future__ import annotations

from collections.abc import Iterable

from .errors import ManifestError
from .model import Operation, Service

def _removal_waves(operations: tuple[Operation, ...], current: tuple[Service, ...], limit: int) -> list[tuple[Operation, ...]]:
    by_name = {service.name: service for service in current}
    pending = {operation.name: operation for operation in operations if operation.kind == "remove"}
    dependants = {name: [] for name in by_name}
    for service in current:
        for dependency in service.depends_on:
            if dependency in dependants:
                dependants[dependency].append(service.name)
    result = []
    while pending:
        ready = sorted(name for name in pending if not any(dependant in pending for dependant in dependants[name]))
        wave_names = ready[:limit]
        if not wave_names:
            raise ManifestError("BAD_PROFILE", "waves", "removal dependencies cannot be scheduled")
        result.append(tuple(pending.pop(name) for name in wave_names))
    return result

def _forward_waves(operations: tuple[Operation, ...], desired: tuple[Service, ...], limit: int) -> list[tuple[Operation, ...]]:
    pending = {operation.name: operation for operation in operations if operation.kind != "remove"}
    by_name = {service.name: service for service in desired}
    result = []
    while pending:
        ready = []
        for name in sorted(pending):
            operation = pending[name]
            service = operation.after
            if service is not None and all(dependency not in pending for dependency in service.depends_on):
                ready.append(name)
        wave_names = ready[:limit]
        if not wave_names:
            raise ManifestError("BAD_PROFILE", "waves", "forward dependencies cannot be scheduled")
        result.append(tuple(pending.pop(name) for name in wave_names))
    return result

def make_waves(operations: tuple[Operation, ...], current: tuple[Service, ...], desired: tuple[Service, ...], max_parallel: int) -> tuple[tuple[Operation, ...], ...]:
    return tuple(_removal_waves(operations, current, max_parallel) + _forward_waves(operations, desired, max_parallel))

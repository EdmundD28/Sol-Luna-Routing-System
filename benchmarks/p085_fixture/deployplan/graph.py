from __future__ import annotations

from collections.abc import Iterable
import heapq

from .errors import ManifestError
from .model import Service


def _items(services: Iterable[Service]) -> tuple[Service, ...]:
    return tuple(services)


def _index(items: tuple[Service, ...]) -> dict[str, Service]:
    return {item.name: item for item in items}


def _validate(items: tuple[Service, ...]) -> dict[str, Service]:
    by_name = _index(items)
    for item in items:
        for dependency in item.depends_on:
            if dependency not in by_name:
                raise ManifestError("UNKNOWN_DEPENDENCY", f"services.{item.name}.depends_on", dependency)
    return by_name


def _cycle_component(items: tuple[Service, ...]) -> tuple[str, ...]:
    graph = {item.name: item.depends_on for item in items}
    next_index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    cycles: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal next_index
        indices[node] = low[node] = next_index
        next_index += 1
        stack.append(node)
        active.add(node)
        for neighbor in graph[node]:
            if neighbor not in indices:
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
            elif neighbor in active:
                low[node] = min(low[node], indices[neighbor])
        if low[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                active.remove(member)
                component.append(member)
                if member == node:
                    break
            ordered = tuple(sorted(component))
            if len(ordered) > 1 or node in graph[node]:
                cycles.append(ordered)

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return min(cycles)


def dependency_order(services: Iterable[Service]) -> tuple[Service, ...]:
    """Return dependencies before dependants with lexical tie-breaking."""
    items = _items(services)
    by_name = _validate(items)
    degree = {item.name: len(item.depends_on) for item in items}
    dependants: dict[str, list[str]] = {name: [] for name in by_name}
    for item in items:
        for dependency in item.depends_on:
            dependants[dependency].append(item.name)
    ready = [name for name, count in degree.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[Service] = []
    while ready:
        name = heapq.heappop(ready)
        ordered.append(by_name[name])
        for dependant in sorted(dependants[name]):
            degree[dependant] -= 1
            if degree[dependant] == 0:
                heapq.heappush(ready, dependant)
    if len(ordered) != len(items):
        component = _cycle_component(items)
        raise ManifestError("DEPENDENCY_CYCLE", "services", ",".join(component))
    return tuple(ordered)


def dependency_closure(
    services: Iterable[Service], roots: Iterable[str]
) -> tuple[Service, ...]:
    """Return normalized roots and their dependencies in dependency order."""
    items = _items(services)
    ordered = dependency_order(items)
    by_name = _index(items)
    selected: set[str] = set()
    for raw in roots:
        from .normalize import normalize_name

        name = normalize_name(raw, path="roots")
        if name not in by_name:
            raise ManifestError("UNKNOWN_ROOT", "roots", name)
        pending = [name]
        while pending:
            current = pending.pop()
            if current in selected:
                continue
            selected.add(current)
            pending.extend(by_name[current].depends_on)
    return tuple(item for item in ordered if item.name in selected)

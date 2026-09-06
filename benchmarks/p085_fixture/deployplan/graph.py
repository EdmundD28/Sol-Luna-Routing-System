from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .errors import ManifestError
from .model import Service


def dependency_order(services: Iterable[Service]) -> tuple[Service, ...]:
    """Return dependencies before dependants with lexical tie-breaking."""
    try:
        items = tuple(services)
    except TypeError as error:
        raise ManifestError("BAD_SERVICE", "services", "services must be iterable") from error
    by_name: dict[str, Service] = {}
    for service in items:
        if not isinstance(service, Service):
            raise ManifestError("BAD_SERVICE", "services", "expected normalized service")
        if service.name in by_name:
            raise ManifestError("DUPLICATE_SERVICE", f"services.{service.name}", "duplicate service name")
        by_name[service.name] = service
    for service in items:
        for dependency in service.depends_on:
            if dependency not in by_name:
                raise ManifestError(
                    "UNKNOWN_DEPENDENCY",
                    f"services.{service.name}.depends_on",
                    f"unknown dependency {dependency}",
                )

    # Tarjan's algorithm identifies actual cyclic components, excluding
    # acyclic downstream nodes which merely cannot be reached by Kahn's queue.
    adjacency = {service.name: tuple(service.depends_on) for service in items}
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(name: str) -> None:
        nonlocal index
        indices[name] = index
        low[name] = index
        index += 1
        stack.append(name)
        on_stack.add(name)
        for dependency in adjacency[name]:
            if dependency not in indices:
                visit(dependency)
                low[name] = min(low[name], low[dependency])
            elif dependency in on_stack:
                low[name] = min(low[name], indices[dependency])
        if low[name] == indices[name]:
            members: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                members.append(member)
                if member == name:
                    break
            component = tuple(sorted(members))
            if len(component) > 1 or component[0] in adjacency[component[0]]:
                components.append(component)

    for name in sorted(by_name):
        if name not in indices:
            visit(name)
    if components:
        component = min(components)
        raise ManifestError(
            "DEPENDENCY_CYCLE",
            f"services.{component[0]}.depends_on",
            ",".join(component),
        )

    indegree = {name: len(service.depends_on) for name, service in by_name.items()}
    dependants = {name: [] for name in by_name}
    for service in items:
        for dependency in service.depends_on:
            dependants[dependency].append(service.name)
    ready = sorted(name for name, degree in indegree.items() if degree == 0)
    order: list[Service] = []
    while ready:
        name = ready.pop(0)
        order.append(by_name[name])
        for dependant in sorted(dependants[name]):
            indegree[dependant] -= 1
            if indegree[dependant] == 0:
                ready.append(dependant)
                ready.sort()
    return tuple(order)


def dependency_closure(
    services: Iterable[Service], roots: Iterable[str]
) -> tuple[Service, ...]:
    """Return normalized roots and their dependencies in dependency order."""
    ordered = dependency_order(services)
    by_name = {service.name: service for service in ordered}
    try:
        raw_roots = (roots,) if isinstance(roots, str) else tuple(roots)
    except TypeError as error:
        raise ManifestError("UNKNOWN_ROOT", "roots", "roots must be iterable") from error
    normalized_roots: list[str] = []
    from .normalize import normalize_name

    for index, root in enumerate(raw_roots):
        try:
            normalized = normalize_name(root, path=f"roots[{index}]")
        except ManifestError as error:
            raise ManifestError("UNKNOWN_ROOT", f"roots[{index}]", error.message) from error
        if normalized not in by_name:
            raise ManifestError("UNKNOWN_ROOT", f"roots[{index}]", f"unknown root {normalized}")
        if normalized not in normalized_roots:
            normalized_roots.append(normalized)
    included = set(normalized_roots)
    pending = list(normalized_roots)
    while pending:
        name = pending.pop()
        for dependency in by_name[name].depends_on:
            if dependency not in included:
                included.add(dependency)
                pending.append(dependency)
    return tuple(service for service in ordered if service.name in included)

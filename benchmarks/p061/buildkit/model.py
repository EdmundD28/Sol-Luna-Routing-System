from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .errors import BuildPlanError


_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_TASK_KEYS = {"id", "deps", "resources", "cost"}
_RESOURCE_CONTAINERS = (list, tuple, set, frozenset)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    deps: tuple[str, ...]
    resources: frozenset[str]
    cost: int


@dataclass(frozen=True)
class BuildPlan:
    changed: tuple[str, ...]
    impacted: tuple[str, ...]
    batches: tuple[tuple[str, ...], ...]
    critical_path: tuple[str, ...]
    critical_cost: int
    total_cost: int


def _check_identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value


def _check_sequence(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{label} must be a list or tuple")
    return list(value)


def _check_resources(value: Any) -> list[Any]:
    if not isinstance(value, _RESOURCE_CONTAINERS):
        raise TypeError("resources must be a list, tuple, set, or frozenset")
    return list(value)


def normalize_tasks(records: Any) -> tuple[TaskSpec, ...]:
    """Validate and canonicalize a task-record collection."""
    if not isinstance(records, (list, tuple)):
        raise TypeError("records must be a list or tuple")

    parsed: list[TaskSpec] = []
    seen_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("each task record must be a dict")
        if set(record) != _TASK_KEYS:
            raise ValueError("task records must contain exactly id, deps, resources, and cost")
        task_id = _check_identifier(record["id"], label="task id")
        if task_id in seen_ids:
            raise ValueError("duplicate task id")
        seen_ids.add(task_id)

        deps_values = _check_sequence(record["deps"], label="deps")
        deps: list[str] = []
        for dep in deps_values:
            deps.append(_check_identifier(dep, label="dependency id"))
        if len(set(deps)) != len(deps):
            raise ValueError("duplicate dependency")

        resource_values = _check_resources(record["resources"])
        resources: list[str] = []
        for resource in resource_values:
            resources.append(_check_identifier(resource, label="resource id"))
        if len(set(resources)) != len(resources):
            raise ValueError("duplicate resource")

        cost = record["cost"]
        if isinstance(cost, bool) or not isinstance(cost, int):
            raise TypeError("cost must be an integer")
        if cost <= 0:
            raise ValueError("cost must be positive")

        parsed.append(TaskSpec(task_id, tuple(sorted(deps)), frozenset(resources), cost))

    known = {task.task_id for task in parsed}
    for task in parsed:
        for dep in task.deps:
            if dep not in known:
                raise BuildPlanError("missing dependency")
            if dep == task.task_id:
                raise BuildPlanError("self-dependency")

    # Kahn's algorithm detects cycles without relying on input order.
    indegree = {task.task_id: len(task.deps) for task in parsed}
    dependents = {task.task_id: [] for task in parsed}
    for task in parsed:
        for dep in task.deps:
            dependents[dep].append(task.task_id)
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        task_id = ready.pop(0)
        visited += 1
        for dependent in sorted(dependents[task_id]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()
    if visited != len(parsed):
        raise BuildPlanError("cycle detected")
    return tuple(sorted(parsed, key=lambda task: task.task_id))


def _coerce_tasks(tasks: Any) -> tuple[TaskSpec, ...]:
    """Accept either records or the normalized output of normalize_tasks."""
    if not isinstance(tasks, (list, tuple)):
        raise TypeError("tasks must be a list or tuple")
    if all(isinstance(task, TaskSpec) for task in tasks):
        normalized = tuple(tasks)
        ids = [task.task_id for task in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task id")
        known = set(ids)
        for task in normalized:
            if not isinstance(task.task_id, str) or _IDENTIFIER.fullmatch(task.task_id) is None:
                raise ValueError("invalid task id")
            if not isinstance(task.deps, tuple) or any(not isinstance(dep, str) for dep in task.deps):
                raise TypeError("normalized dependencies must be a tuple")
            if len(task.deps) != len(set(task.deps)):
                raise ValueError("duplicate dependency")
            if any(_IDENTIFIER.fullmatch(dep) is None for dep in task.deps):
                raise ValueError("invalid dependency id")
            if not isinstance(task.resources, frozenset) or any(not isinstance(resource, str) for resource in task.resources):
                raise TypeError("normalized resources must be a frozenset")
            if any(_IDENTIFIER.fullmatch(resource) is None for resource in task.resources):
                raise ValueError("invalid resource id")
            if isinstance(task.cost, bool) or not isinstance(task.cost, int):
                raise TypeError("cost must be an integer")
            if task.cost <= 0:
                raise ValueError("cost must be positive")
            for dep in task.deps:
                if dep not in known or dep == task.task_id:
                    raise BuildPlanError("invalid dependency")
        indegree = {task.task_id: len(task.deps) for task in normalized}
        dependents = {task.task_id: [] for task in normalized}
        for task in normalized:
            for dep in task.deps:
                dependents[dep].append(task.task_id)
        ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
        visited = 0
        while ready:
            task_id = ready.pop(0)
            visited += 1
            for dependent in sorted(dependents[task_id]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()
        if visited != len(normalized):
            raise BuildPlanError("cycle detected")
        return tuple(sorted(normalized, key=lambda task: task.task_id))
    return normalize_tasks(tasks)


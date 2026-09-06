from __future__ import annotations

import heapq
from typing import Any

from .model import _coerce_tasks


def topological_order(tasks: Any) -> tuple[str, ...]:
    normalized = _coerce_tasks(tasks)
    indegree = {task.task_id: len(task.deps) for task in normalized}
    dependents = {task.task_id: [] for task in normalized}
    for task in normalized:
        for dep in task.deps:
            dependents[dep].append(task.task_id)
    ready = [task.task_id for task in normalized if indegree[task.task_id] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        task_id = heapq.heappop(ready)
        order.append(task_id)
        for dependent in sorted(dependents[task_id]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)
    return tuple(order)


def dependents_map(tasks: Any) -> dict[str, tuple[str, ...]]:
    normalized = _coerce_tasks(tasks)
    result: dict[str, list[str]] = {task.task_id: [] for task in normalized}
    for task in normalized:
        for dep in task.deps:
            result[dep].append(task.task_id)
    return {task_id: tuple(sorted(values)) for task_id, values in result.items()}


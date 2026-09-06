from __future__ import annotations

from typing import Any

from .errors import BuildPlanError
from .impact import _validate_ids
from .model import _coerce_tasks


def schedule_batches(tasks: Any, selected: Any, max_parallel: Any) -> tuple[tuple[str, ...], ...]:
    normalized = _coerce_tasks(tasks)
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int):
        raise TypeError("max_parallel must be an integer")
    if max_parallel <= 0:
        raise ValueError("max_parallel must be positive")
    known = {task.task_id for task in normalized}
    selected_ids = _validate_ids(selected, known, label="selected tasks")
    if not selected_ids:
        return ()

    by_id = {task.task_id: task for task in normalized}
    remaining = set(selected_ids)
    scheduled: set[str] = set()
    batches: list[tuple[str, ...]] = []
    while remaining:
        ready = [
            task_id
            for task_id in sorted(remaining)
            if all(dep not in remaining or dep in scheduled for dep in by_id[task_id].deps)
        ]
        batch: list[str] = []
        resources: set[str] = set()
        for task_id in ready:
            if len(batch) >= max_parallel:
                break
            task_resources = by_id[task_id].resources
            if resources.intersection(task_resources):
                continue
            batch.append(task_id)
            resources.update(task_resources)
        if not batch:
            raise BuildPlanError("selected tasks cannot be scheduled")
        batches.append(tuple(batch))
        scheduled.update(batch)
        remaining.difference_update(batch)
    return tuple(batches)


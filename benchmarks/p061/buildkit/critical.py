from __future__ import annotations

from typing import Any

from .impact import _validate_ids
from .graph import topological_order
from .model import _coerce_tasks


def critical_path(tasks: Any, selected: Any) -> tuple[tuple[str, ...], int]:
    normalized = _coerce_tasks(tasks)
    known = {task.task_id for task in normalized}
    selected_ids = _validate_ids(selected, known, label="selected tasks")
    if not selected_ids:
        return ((), 0)

    selected_set = set(selected_ids)
    by_id = {task.task_id: task for task in normalized}
    best: dict[str, tuple[tuple[str, ...], int]] = {}
    order = topological_order(normalized)
    for task_id in order:
        if task_id not in selected_set:
            continue
        task = by_id[task_id]
        predecessors = [dep for dep in task.deps if dep in selected_set]
        if not predecessors:
            best[task_id] = ((task_id,), task.cost)
            continue
        chosen = best[predecessors[0]]
        for predecessor in predecessors[1:]:
            candidate = best[predecessor]
            if candidate[1] > chosen[1] or (candidate[1] == chosen[1] and candidate[0] < chosen[0]):
                chosen = candidate
        best[task_id] = (chosen[0] + (task_id,), chosen[1] + task.cost)

    chosen_path: tuple[str, ...] = ()
    chosen_cost = 0
    for task_id in order:
        if task_id not in best:
            continue
        path, cost = best[task_id]
        if cost > chosen_cost or (cost == chosen_cost and (not chosen_path or path < chosen_path)):
            chosen_path, chosen_cost = path, cost
    return chosen_path, chosen_cost


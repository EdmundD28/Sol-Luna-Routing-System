from __future__ import annotations

from typing import Any

from .errors import BuildPlanError
from .graph import dependents_map, topological_order
from .model import _coerce_tasks


def _validate_ids(values: Any, known: set[str], *, label: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise TypeError(f"{label} must be a list or tuple")
    result = tuple(values)
    if any(not isinstance(value, str) for value in result):
        raise TypeError(f"{label} must contain strings")
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate {label}")
    if any(value not in known for value in result):
        raise BuildPlanError(f"unknown {label}")
    return result


def impacted_tasks(tasks: Any, changed: Any) -> tuple[str, ...]:
    normalized = _coerce_tasks(tasks)
    known = {task.task_id for task in normalized}
    selected = _validate_ids(changed, known, label="changed tasks")
    if not selected:
        return ()
    direct = dependents_map(normalized)
    impacted = set(selected)
    pending = list(selected)
    while pending:
        task_id = pending.pop()
        for dependent in direct[task_id]:
            if dependent not in impacted:
                impacted.add(dependent)
                pending.append(dependent)
    return tuple(task_id for task_id in topological_order(normalized) if task_id in impacted)


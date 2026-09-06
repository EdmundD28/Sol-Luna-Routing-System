from __future__ import annotations

from typing import Any

from .batches import schedule_batches
from .critical import critical_path
from .impact import _validate_ids, impacted_tasks
from .model import BuildPlan, _coerce_tasks


def plan_build(records: Any, changed: Any, max_parallel: Any) -> BuildPlan:
    normalized = _coerce_tasks(records)
    known = {task.task_id for task in normalized}
    changed_ids = _validate_ids(changed, known, label="changed tasks")
    if not changed_ids:
        return BuildPlan((), (), (), (), 0, 0)
    impacted = impacted_tasks(normalized, changed_ids)
    batches = schedule_batches(normalized, impacted, max_parallel)
    path, path_cost = critical_path(normalized, impacted)
    by_id = {task.task_id: task for task in normalized}
    total_cost = sum(by_id[task_id].cost for task_id in impacted)
    return BuildPlan(changed_ids, impacted, batches, path, path_cost, total_cost)


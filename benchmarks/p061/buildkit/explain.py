from __future__ import annotations

from .model import BuildPlan


def explain_plan(plan: BuildPlan) -> tuple[str, ...]:
    if not isinstance(plan, BuildPlan):
        raise TypeError("plan must be a BuildPlan")
    lines = [
        "changed=" + (",".join(plan.changed) if plan.changed else "-"),
        "impacted=" + (",".join(plan.impacted) if plan.impacted else "-"),
    ]
    lines.extend(f"batch[{index}]={','.join(batch)}" for index, batch in enumerate(plan.batches, 1))
    lines.extend([
        "critical=" + (",".join(plan.critical_path) if plan.critical_path else "-") + f":{plan.critical_cost}",
        f"total_cost={plan.total_cost}",
    ])
    return tuple(lines)


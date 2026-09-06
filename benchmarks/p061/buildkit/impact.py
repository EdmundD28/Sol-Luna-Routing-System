from .model import _coerce_tasks,_validate_selected
from .graph import topological_order,dependents_map
def impacted_tasks(tasks,changed):
    ts=_coerce_tasks(tasks); chosen=_validate_selected(changed,{t.task_id for t in ts})
    if not chosen:return ()
    children=dependents_map(ts); found=set(chosen); pending=list(chosen)
    while pending:
        for c in children[pending.pop()]:
            if c not in found: found.add(c); pending.append(c)
    return tuple(x for x in topological_order(ts) if x in found)

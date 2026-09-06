from .model import BuildPlan,normalize_tasks
from .impact import impacted_tasks
from .batches import schedule_batches
from .critical import critical_path
def plan_build(records,changed,max_parallel):
    ts=normalize_tasks(records); changed=tuple(changed) if isinstance(changed,(list,tuple)) else changed
    impacted=impacted_tasks(ts,changed)
    if not impacted:return BuildPlan(changed,(),(),(),0,0)
    batches=schedule_batches(ts,impacted,max_parallel); path,cost=critical_path(ts,impacted); ids=set(impacted)
    return BuildPlan(changed,impacted,batches,path,cost,sum(t.cost for t in ts if t.task_id in ids))

from .model import _coerce_tasks,_validate_selected
from .errors import BuildPlanError
def schedule_batches(tasks,selected,max_parallel):
    ts=_coerce_tasks(tasks)
    if isinstance(max_parallel,bool) or not isinstance(max_parallel,int): raise TypeError('max_parallel must be an integer')
    if max_parallel<=0: raise ValueError('max_parallel must be positive')
    chosen=_validate_selected(selected,{t.task_id for t in ts})
    if not chosen:return ()
    by={t.task_id:t for t in ts}; remain=set(chosen); out=[]
    while remain:
        ready=sorted(k for k in remain if all(d not in remain for d in by[k].deps))
        if not ready: raise BuildPlanError('selected dependency cycle')
        used=set(); batch=[]
        for k in ready:
            if len(batch)>=max_parallel: break
            if by[k].resources.isdisjoint(used): batch.append(k); used.update(by[k].resources)
        if not batch: raise BuildPlanError('unschedulable selection')
        out.append(tuple(batch)); remain.difference_update(batch)
    return tuple(out)

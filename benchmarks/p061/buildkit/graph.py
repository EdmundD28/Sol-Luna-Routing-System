from .model import _coerce_tasks,_topological
def topological_order(tasks): return _topological(_coerce_tasks(tasks))
def dependents_map(tasks):
    ts=_coerce_tasks(tasks); out={t.task_id:[] for t in ts}
    for t in ts:
        for d in t.deps: out[d].append(t.task_id)
    return {k:tuple(sorted(v)) for k,v in sorted(out.items())}

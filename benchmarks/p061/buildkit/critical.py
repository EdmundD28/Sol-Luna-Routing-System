from .model import _coerce_tasks,_validate_selected
from .graph import topological_order
def critical_path(tasks,selected):
    ts=_coerce_tasks(tasks); chosen=_validate_selected(selected,{t.task_id for t in ts})
    if not chosen:return (),0
    by={t.task_id:t for t in ts}; sel=set(chosen); best={}
    for k in topological_order(ts):
        if k not in sel: continue
        preds=[d for d in by[k].deps if d in sel]
        if preds:
            path,cost=min((best[d] for d in preds),key=lambda z:(-z[1],z[0])); best[k]=(path+(k,),cost+by[k].cost)
        else: best[k]=((k,),by[k].cost)
    return min(best.values(),key=lambda z:(-z[1],z[0]))

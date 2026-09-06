from dataclasses import dataclass
import re
from .errors import BuildPlanError
_ID=re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
def _identifier(v):
    if not isinstance(v,str): raise TypeError('identifier must be a string')
    if not _ID.fullmatch(v): raise ValueError('invalid identifier')
    return v
def _sequence(v):
    if not isinstance(v,(list,tuple)): raise TypeError('expected list or tuple')
    return v
@dataclass(frozen=True)
class TaskSpec:
    task_id:str; deps:tuple; resources:frozenset; cost:int
@dataclass(frozen=True)
class BuildPlan:
    changed:tuple; impacted:tuple; batches:tuple; critical_path:tuple; critical_cost:int; total_cost:int
def _topological(tasks):
    indegree={t.task_id:len(t.deps) for t in tasks}; children={t.task_id:[] for t in tasks}
    for t in tasks:
        for d in t.deps: children[d].append(t.task_id)
    ready=sorted(k for k,v in indegree.items() if v==0); out=[]
    while ready:
        k=ready.pop(0); out.append(k)
        for c in sorted(children[k]):
            indegree[c]-=1
            if indegree[c]==0: ready.append(c); ready.sort()
    if len(out)!=len(tasks): raise BuildPlanError('dependency cycle')
    return tuple(out)
def normalize_tasks(records):
    records=_sequence(records); parsed=[]; seen=set()
    for r in records:
        if not isinstance(r,dict): raise TypeError('task record must be a dict')
        if set(r)!={'id','deps','resources','cost'}: raise ValueError('invalid task record keys')
        tid=_identifier(r['id'])
        if tid in seen: raise ValueError('duplicate task id')
        seen.add(tid); deps=_sequence(r['deps'])
        if len(set(deps))!=len(deps): raise ValueError('duplicate dependency')
        deps=tuple(sorted(_identifier(d) for d in deps)); res=r['resources']
        if not isinstance(res,(list,tuple,set,frozenset)): raise TypeError('invalid resources container')
        if len(set(res))!=len(res): raise ValueError('duplicate resource')
        resources=frozenset(_identifier(x) for x in res); cost=r['cost']
        if isinstance(cost,bool) or not isinstance(cost,int): raise TypeError('cost must be an integer')
        if cost<=0: raise ValueError('cost must be positive')
        parsed.append(TaskSpec(tid,deps,resources,cost))
    ids={t.task_id for t in parsed}
    for t in parsed:
        for d in t.deps:
            if d not in ids or d==t.task_id: raise BuildPlanError('invalid dependency')
    _topological(parsed)
    return tuple(sorted(parsed,key=lambda t:t.task_id))
def _coerce_tasks(tasks):
    if not isinstance(tasks,(list,tuple)): raise TypeError('tasks must be a list or tuple')
    return tuple(sorted(tasks,key=lambda t:t.task_id)) if all(isinstance(t,TaskSpec) for t in tasks) else normalize_tasks(tasks)
def _validate_selected(selected,known):
    if not isinstance(selected,(list,tuple)): raise TypeError('selected must be a list or tuple')
    if len(set(selected))!=len(selected): raise ValueError('duplicate selected task')
    for x in selected:
        _identifier(x)
        if x not in known: raise BuildPlanError('unknown task')
    return tuple(selected)

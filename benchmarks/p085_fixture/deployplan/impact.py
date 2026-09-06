from __future__ import annotations
from collections.abc import Iterable
from .diff import diff_services
from .graph import dependency_order
from .model import Operation, Service

def diff_with_impact(current: Iterable[Service], desired: Iterable[Service]) -> tuple[Operation, ...]:
    cur, des = tuple(current), tuple(desired); base = diff_services(cur, des)
    changed={o.name for o in base}; marked=set(); pending=set(changed)
    while pending:
        x=pending.pop()
        for s in des:
            if s.name not in changed and x in s.depends_on and s.name not in marked: marked.add(s.name); pending.add(s.name)
    existing={o.name for o in base}; extra=[]
    for s in dependency_order(des):
        if s.name in marked and s.name not in existing: extra.append(Operation("restart",s.name,s,s))
    return tuple([o for o in base if o.kind=="remove"]+[o for o in base if o.kind!="remove"]+extra)

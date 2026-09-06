from __future__ import annotations
from .model import Operation, Service

def build_waves(operations: tuple[Operation,...], current: tuple[Service,...], desired: tuple[Service,...], max_parallel: int) -> tuple[tuple[Operation,...], ...]:
    cur={s.name:s for s in current}; des={s.name:s for s in desired}; waves=[]
    pending={o.name:o for o in operations if o.kind=="remove"}
    while pending:
        ready=sorted(n for n in pending if not any(n in s.depends_on for x,s in cur.items() if x in pending and x!=n)); chunk=ready[:max_parallel]; waves.append(tuple(pending.pop(n) for n in chunk))
    pending={o.name:o for o in operations if o.kind!="remove"}
    while pending:
        ready=sorted(n for n in pending if all(d not in pending for d in des[n].depends_on)); chunk=ready[:max_parallel]; waves.append(tuple(pending.pop(n) for n in chunk))
    return tuple(waves)

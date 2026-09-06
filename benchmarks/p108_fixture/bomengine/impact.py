def compute_impact(initial,final,changes,removed):
    mapping={c.source:c.target for c in changes if c.kind=="replace"}; seeds={mapping.get(c.source,c.source) for c in changes if c.kind!="remove"}; rev={c.id:set() for c in final}
    for c in final:
        for d in c.depends_on:
            if d in rev: rev[d].add(c.id)
    for c in initial:
        if c.id in removed:
            for d in initial:
                if c.id in d.depends_on: seeds.add(mapping.get(d.id,d.id))
    seen=set(seeds); stack=list(seeds)
    while stack:
        x=stack.pop()
        for y in rev.get(x,()):
            if y not in seen: seen.add(y); stack.append(y)
    return tuple(sorted(x for x in seen if x in rev))

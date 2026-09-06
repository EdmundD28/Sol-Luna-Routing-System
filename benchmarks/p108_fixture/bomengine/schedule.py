from .model import BomError
def assembly_waves(components):
    deps={c.id:set(c.depends_on) for c in components}; left=set(deps); out=[]
    while left:
        ready=tuple(sorted(x for x in left if not deps[x]&left))
        if not ready: raise BomError("CYCLE",("final","depends_on"))
        out.append(ready); left-=set(ready)
    return tuple(out)

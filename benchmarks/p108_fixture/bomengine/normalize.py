import re
from collections.abc import Mapping
from .model import Component, NormalizedChange, BomError
_ID=re.compile(r"[A-Z][A-Z0-9_]*\Z",re.ASCII); _CF=("id","version","quantity","depends_on","excludes")
def err(c,p): raise BomError(c,tuple(p))
def ident(v,p):
    if not isinstance(v,str) or not _ID.fullmatch(v): err("INVALID_ID",p)
    return v
def pos(v,p):
    if isinstance(v,bool) or not isinstance(v,int) or v<=0: err("INVALID_INTEGER",p)
    return v
def normalize_inputs(raw_components,raw_changes):
    if not isinstance(raw_components,(list,tuple)): err("INVALID_TYPE",("components",))
    initial=[]; ids={}
    for i,r in enumerate(raw_components):
        p=("components",i)
        if not isinstance(r,Mapping): err("INVALID_TYPE",p)
        for f in _CF:
            if f not in r: err("MISSING_FIELD",p+(f,))
        u=sorted(set(r)-set(_CF))
        if u: err("UNKNOWN_FIELD",p+(u[0],))
        cid=ident(r["id"],p+("id",)); ver=pos(r["version"],p+("version",)); qty=pos(r["quantity"],p+("quantity",)); vals={}
        for f in ("depends_on","excludes"):
            if not isinstance(r[f],(list,tuple)): err("INVALID_TYPE",p+(f,))
            out=[]; seen=set()
            for j,v in enumerate(r[f]):
                x=ident(v,p+(f,j))
                if x in seen: err("DUPLICATE_REFERENCE",p+(f,j))
                seen.add(x); out.append(x)
            vals[f]=tuple(sorted(out))
        if cid in ids: err("DUPLICATE_ID",p+("id",))
        ids[cid]=i; initial.append(Component(cid,ver,qty,vals["depends_on"],vals["excludes"]))
    for i,c in enumerate(initial):
        for f,items,code in (("depends_on",c.depends_on,"SELF_DEPENDENCY"),("excludes",c.excludes,"SELF_EXCLUSION")):
            for j,x in enumerate(items):
                if x not in ids: err("UNKNOWN_REFERENCE",("components",i,f,j))
                if x==c.id: err(code,("components",i,f,j))
    if not isinstance(raw_changes,(list,tuple)): err("INVALID_TYPE",("changes",))
    changes=[]; by={}
    for i,r in enumerate(raw_changes):
        p=("changes",i)
        if not isinstance(r,Mapping): err("INVALID_TYPE",p)
        for f in ("kind","source"):
            if f not in r: err("MISSING_FIELD",p+(f,))
        k=r["kind"]
        if k not in ("set_quantity","set_version","replace","remove"): err("INVALID_CHANGE",p+("kind",))
        s=ident(r["source"],p+("source",))
        if s not in ids: err("UNKNOWN_SOURCE",p+("source",))
        if s in by: err("DUPLICATE_CHANGE",p+("source",))
        allowed={"set_quantity":{"kind","source","quantity"},"set_version":{"kind","source","version"},"replace":{"kind","source","target","version"},"remove":{"kind","source"}}[k]; u=sorted(set(r)-allowed)
        if u: err("UNKNOWN_FIELD",p+(u[0],))
        if k=="set_quantity":
            if "quantity" not in r: err("MISSING_FIELD",p+("quantity",))
            ch=NormalizedChange(k,s,None,pos(r["quantity"],p+("quantity",)))
        elif k=="set_version":
            if "version" not in r: err("MISSING_FIELD",p+("version",))
            ch=NormalizedChange(k,s,None,pos(r["version"],p+("version",)))
        elif k=="replace":
            if "target" not in r: err("MISSING_FIELD",p+("target",))
            ch=NormalizedChange(k,s,ident(r["target"],p+("target",)),pos(r["version"],p+("version",)) if "version" in r else None)
        else: ch=NormalizedChange(k,s,None,None)
        by[s]=ch; changes.append(ch)
    targets={}
    for i,ch in enumerate(changes):
        if ch.kind=="replace":
            if ch.target in targets or (ch.target in ids and not (ch.target in by and by[ch.target].kind=="replace")): err("TARGET_CONFLICT",("changes",i,"target"))
            targets[ch.target]=i
    mapping={c.source:c.target for c in changes if c.kind=="replace"}; final=[]; removed=[]
    for c in initial:
        ch=by.get(c.id)
        if ch and ch.kind=="remove": removed.append(c.id); continue
        final.append(Component(mapping.get(c.id,c.id),ch.value if ch and ch.kind in ("set_version","replace") and ch.value is not None else c.version,ch.value if ch and ch.kind=="set_quantity" else c.quantity,tuple(sorted(mapping.get(x,x) for x in c.depends_on)),tuple(sorted(mapping.get(x,x) for x in c.excludes if mapping.get(x,x) not in removed))))
    present={c.id for c in final}; rebuilt=[]
    for c in final:
        es=set(c.excludes)
        for o in final:
            if c.id in o.excludes: es.add(o.id)
        rebuilt.append(Component(c.id,c.version,c.quantity,c.depends_on,tuple(sorted(x for x in es if x in present and x!=c.id))))
    final=tuple(sorted(rebuilt,key=lambda x:x.id))
    for c in final:
        for j,d in enumerate(c.depends_on):
            if d not in present: err("MISSING_DEPENDENCY",("final",c.id,"depends_on",j))
        for j,e in enumerate(c.excludes):
            if c.id<e: err("EXCLUSION_CONFLICT",("final",c.id,"excludes",j))
    return tuple(initial),final,tuple(sorted(changes,key=lambda x:(x.source,x.kind,x.target or "",x.value if x.value is not None else -1))),tuple(sorted(removed)),mapping

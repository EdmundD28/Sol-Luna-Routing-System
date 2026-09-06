from collections.abc import Mapping, Sequence
from types import MappingProxyType
from ..errors import WorkbenchError
from ..canonical import clone_json
from ..frozen import freeze_json

from .models import CacheEntry, CacheHit, CacheRequest, EvictionPlan


def validate_cache_entry(raw: Mapping, path: tuple = ("cache",)) -> CacheEntry:
    fields={"key","value","created_at","expires_at","size_bytes","dependencies","last_access","pinned"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    key=raw.get("key")
    if not isinstance(key,str) or not key: raise WorkbenchError("INVALID_FIELD",path+("key",),"invalid key")
    def integer(k,default=None,nonneg=False):
        v=raw.get(k,default)
        if isinstance(v,bool) or not isinstance(v,int) or (nonneg and v<0): raise WorkbenchError("INVALID_FIELD",path+(k,),"invalid integer")
        return v
    created=integer("created_at"); size=integer("size_bytes",nonneg=True); last=integer("last_access",0)
    exp=raw.get("expires_at")
    if exp is not None and (isinstance(exp,bool) or not isinstance(exp,int) or exp<created): raise WorkbenchError("INVALID_FIELD",path+("expires_at",),"invalid expiry")
    deps=raw.get("dependencies",[])
    if not isinstance(deps,list) or any(not isinstance(x,str) or not x for x in deps) or len(set(deps))!=len(deps): raise WorkbenchError("INVALID_FIELD",path+("dependencies",),"invalid dependencies")
    pin=raw.get("pinned",False)
    if not isinstance(pin,bool): raise WorkbenchError("INVALID_FIELD",path+("pinned",),"expected bool")
    try: value=freeze_json(clone_json(raw.get("value")))
    except WorkbenchError as e: raise WorkbenchError("INVALID_FIELD",path+("value",),"invalid JSON value") from e
    return CacheEntry(key,value,created,exp,size,tuple(deps),last,pin)


def validate_cache_request(raw: Mapping, path: tuple = ("request",)) -> CacheRequest:
    fields={"key","now","allow_prefix"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    key=raw.get("key"); now=raw.get("now"); ap=raw.get("allow_prefix",True)
    if not isinstance(key,str) or not key: raise WorkbenchError("INVALID_FIELD",path+("key",),"invalid key")
    if isinstance(now,bool) or not isinstance(now,int): raise WorkbenchError("INVALID_FIELD",path+("now",),"invalid integer")
    if not isinstance(ap,bool): raise WorkbenchError("INVALID_FIELD",path+("allow_prefix",),"expected bool")
    return CacheRequest(key,now,ap)


def resolve_cache(entries: Sequence, request: Mapping | CacheRequest) -> CacheHit | None:
    req=request if isinstance(request,CacheRequest) else validate_cache_request(request)
    vals=[]; by={}
    for i,e in enumerate(entries):
        x=validate_cache_entry(e,("cache",i))
        if x.key in by:
            if x!=by[x.key]: raise WorkbenchError("DUPLICATE_CACHE_ENTRY",("cache",i),"conflicting duplicate")
            continue
        by[x.key]=x; vals.append(x)
    for i,x in enumerate(vals):
        for j,d in enumerate(x.dependencies):
            if d not in by: raise WorkbenchError("MISSING_DEPENDENCY",("cache",i,"dependencies",j),"missing dependency")
    visiting=set(); done=set()
    def cyc(k):
        if k in visiting: return True
        if k in done:return False
        visiting.add(k)
        if any(cyc(d) for d in by[k].dependencies): return True
        visiting.remove(k); done.add(k); return False
    if any(cyc(k) for k in by): raise WorkbenchError("DEPENDENCY_CYCLE",("cache","dependencies"),"dependency cycle",{"members":tuple(sorted(visiting or by))})
    invalid={k for k,e in by.items() if e.expires_at is not None and req.now>=e.expires_at}
    changed=True
    while changed:
        changed=False
        for k,e in by.items():
            if k not in invalid and any(d in invalid for d in e.dependencies): invalid.add(k); changed=True
    exact=by.get(req.key)
    if exact and exact.key not in invalid:return CacheHit(exact,"exact")
    if req.allow_prefix:
        cand=sorted((e for e in vals if e.key not in invalid and e.key.startswith(req.key+"/")),key=lambda e:(-len(e.key),e.key))
        if cand:return CacheHit(cand[0],"prefix")
    return None


def plan_eviction(entries: Sequence, byte_budget: int, now: int) -> EvictionPlan:
    if isinstance(byte_budget,bool) or not isinstance(byte_budget,int) or byte_budget<0: raise WorkbenchError("INVALID_BUDGET",(),"invalid byte budget")
    if isinstance(now,bool) or not isinstance(now,int): raise WorkbenchError("INVALID_FIELD",("now",),"invalid integer")
    vals=[]; by={}
    for i,e in enumerate(entries):
        x=validate_cache_entry(e,("cache",i))
        if x.key in by:
            if x!=by[x.key]: raise WorkbenchError("DUPLICATE_CACHE_ENTRY",("cache",i),"conflicting duplicate")
            continue
        by[x.key]=x; vals.append(x)
    pinned=[e for e in vals if e.pinned]
    req=sum(e.size_bytes for e in pinned)
    if req>byte_budget: raise WorkbenchError("IMPOSSIBLE_BUDGET",(),"pinned entries exceed budget",{"required_bytes":req})
    invalid={k for k,e in by.items() if e.expires_at is not None and now>=e.expires_at}
    changed=True
    while changed:
        changed=False
        for k,e in by.items():
            if k not in invalid and any(d in invalid for d in e.dependencies): invalid.add(k); changed=True
    deletable=sorted([e for e in vals if not e.pinned and e.key in invalid],key=lambda e:e.key)
    retained=[e for e in vals if e.pinned or e.key not in invalid]; total=sum(e.size_bytes for e in retained); deleted=list(deletable)
    for e in deletable: total-=e.size_bytes
    candidates=sorted([e for e in vals if not e.pinned and e.key not in invalid],key=lambda e:(e.last_access,e.key))
    for e in candidates:
        if total<=byte_budget:break
        deleted.append(e); total-=e.size_bytes
    ds=tuple(sorted(e.key for e in deleted)); rs=tuple(sorted(e.key for e in vals if e.key not in set(ds)))
    return EvictionPlan(ds,rs,sum(e.size_bytes for e in deleted))

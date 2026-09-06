from collections.abc import Mapping, Sequence
from types import MappingProxyType
from ..errors import WorkbenchError
from .models import RolloutWave, BlockedTarget

from .models import RolloutPlan, RolloutRequest, RolloutTarget


def validate_target(raw: Mapping, path: tuple = ("rollout", "targets")) -> RolloutTarget:
    fields={"target_id","region","ring","eligible","enabled","anti_affinity","depends_on"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    def txt(k,allow_none=False):
        v=raw.get(k)
        if allow_none and v is None:return None
        if not isinstance(v,str) or not v: raise WorkbenchError("INVALID_FIELD",path+(k,),"invalid string")
        return v
    tid,reg=txt("target_id"),txt("region"); ring=raw.get("ring")
    if isinstance(ring,bool) or not isinstance(ring,int) or ring<0: raise WorkbenchError("INVALID_FIELD",path+("ring",),"invalid ring")
    elig,enabled=raw.get("eligible",True),raw.get("enabled",True)
    if not isinstance(elig,bool): raise WorkbenchError("INVALID_FIELD",path+("eligible",),"expected bool")
    if not isinstance(enabled,bool): raise WorkbenchError("INVALID_FIELD",path+("enabled",),"expected bool")
    aa=txt("anti_affinity",True); dep=raw.get("depends_on",[])
    if not isinstance(dep,list) or any(not isinstance(x,str) or not x for x in dep) or len(set(dep))!=len(dep): raise WorkbenchError("INVALID_FIELD",path+("depends_on",),"invalid dependencies")
    return __import__(__name__.rsplit('.',1)[0]+'.models',fromlist=['RolloutTarget']).RolloutTarget(tid,reg,ring,elig,enabled,aa,tuple(dep))


def validate_rollout_request(raw: Mapping, path: tuple = ("rollout", "request")) -> RolloutRequest:
    fields={"rings","max_per_wave","regional_quota","allow_spillover"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    rings=raw.get("rings")
    if not isinstance(rings,list) or not rings: raise WorkbenchError("INVALID_FIELD",path+("rings",),"invalid rings")
    for i,v in enumerate(rings):
        if isinstance(v,bool) or not isinstance(v,int) or v<0: raise WorkbenchError("INVALID_FIELD",path+("rings",i),"invalid ring")
    if len(set(rings))!=len(rings): raise WorkbenchError("INVALID_FIELD",path+("rings",1),"duplicate ring")
    mp=raw.get("max_per_wave")
    if isinstance(mp,bool) or not isinstance(mp,int) or mp<=0: raise WorkbenchError("INVALID_FIELD",path+("max_per_wave",),"invalid capacity")
    q=raw.get("regional_quota")
    if not isinstance(q,Mapping): raise WorkbenchError("INVALID_FIELD",path+("regional_quota",),"invalid quota")
    out={}
    for k,v in q.items():
        if not isinstance(k,str) or not k or isinstance(v,bool) or not isinstance(v,int) or v<=0: raise WorkbenchError("INVALID_FIELD",path+("regional_quota",k),"invalid quota")
        out[k]=v
    spill=raw.get("allow_spillover",True)
    if not isinstance(spill,bool): raise WorkbenchError("INVALID_FIELD",path+("allow_spillover",),"expected bool")
    return RolloutRequest(tuple(sorted(rings)),mp,MappingProxyType(dict(sorted(out.items()))),spill)


def assign_rollout(targets: Sequence, request: Mapping | RolloutRequest) -> RolloutPlan:
    req=request if isinstance(request,RolloutRequest) else validate_rollout_request(request)
    vals=[]; by={}
    for i,t in enumerate(targets):
        x=validate_target(t,("rollout","targets",i))
        if x.target_id in by:
            if x!=by[x.target_id]: raise WorkbenchError("DUPLICATE_TARGET",("rollout","targets",i),"conflicting duplicate")
            continue
        by[x.target_id]=x; vals.append(x)
    blocked={}; waves=[]; assigned=set()
    for ring in req.rings:
        rem=sorted([t for t in vals if t.ring==ring and t.target_id not in assigned and t.target_id not in blocked],key=lambda t:t.target_id)
        idx=0
        while rem:
            wave=[]; regs={}; aff=set()
            for t in rem:
                if not t.enabled: blocked[t.target_id]="DISABLED"; continue
                if not t.eligible: blocked[t.target_id]="INELIGIBLE"; continue
                if t.ring not in req.rings: blocked[t.target_id]="RING_DISABLED"; continue
                bad=False
                for d in t.depends_on:
                    if d not in by: blocked[t.target_id]="MISSING_DEPENDENCY"; bad=True; break
                    if d in blocked or by[d].ring>=t.ring: blocked[t.target_id]="DEPENDENCY_BLOCKED"; bad=True; break
                    if d not in assigned: bad=True; blocked[t.target_id]="DEPENDENCY_BLOCKED"; break
                if bad: continue
                if not req.allow_spillover and len(wave)>=req.max_per_wave: blocked[t.target_id]="WAVE_CAPACITY"; continue
                if len(wave)>=req.max_per_wave:
                    if req.allow_spillover: continue
                    blocked[t.target_id]="WAVE_CAPACITY"; continue
                if regs.get(t.region,0)>=req.regional_quota.get(t.region,0):
                    if req.allow_spillover: continue
                    blocked[t.target_id]="REGIONAL_QUOTA"; continue
                if t.anti_affinity is not None and t.anti_affinity in aff:
                    if req.allow_spillover: continue
                    blocked[t.target_id]="ANTI_AFFINITY"; continue
                wave.append(t); regs[t.region]=regs.get(t.region,0)+1
                if t.anti_affinity is not None: aff.add(t.anti_affinity)
            if wave:
                ids=tuple(t.target_id for t in wave); waves.append(RolloutWave(ring,idx,ids)); idx+=1; assigned.update(ids); rem=[t for t in rem if t.target_id not in assigned and t.target_id not in blocked]
                if not req.allow_spillover: break
            else:
                if req.allow_spillover:
                    for t in rem:
                        if t.target_id in blocked: continue
                        blocked[t.target_id]="REGIONAL_QUOTA" if req.regional_quota.get(t.region,0)==0 else "ANTI_AFFINITY"
                break
    for t in vals:
        if t.target_id not in assigned and t.target_id not in blocked: blocked[t.target_id]="RING_DISABLED"
    return __import__(__name__.rsplit('.',1)[0]+'.models',fromlist=['RolloutPlan']).RolloutPlan(tuple(waves),tuple(BlockedTarget(k,blocked[k]) for k in sorted(blocked)))

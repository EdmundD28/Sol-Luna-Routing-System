from collections.abc import Mapping, Sequence
from ..errors import WorkbenchError

from .models import LegalHold, RetentionPlan, RetentionPolicy, Snapshot


def validate_snapshot(raw: Mapping, path: tuple = ("retention", "snapshots")) -> Snapshot:
    fields={"snapshot_id","channel","created_at","tags","healthy","size_bytes"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    def txt(k):
        v=raw.get(k)
        if not isinstance(v,str) or not v: raise WorkbenchError("INVALID_FIELD",path+(k,),"invalid string")
        return v
    sid,ch=txt("snapshot_id"),txt("channel"); created=raw.get("created_at"); size=raw.get("size_bytes",0)
    for k,v in (("created_at",created),("size_bytes",size)):
        if isinstance(v,bool) or not isinstance(v,int) or (k=="size_bytes" and v<0): raise WorkbenchError("INVALID_FIELD",path+(k,),"invalid integer")
    tags=raw.get("tags",[])
    if not isinstance(tags,list) or any(not isinstance(x,str) or not x for x in tags) or len(set(tags))!=len(tags): raise WorkbenchError("INVALID_FIELD",path+("tags",),"invalid tags")
    healthy=raw.get("healthy",True)
    if not isinstance(healthy,bool): raise WorkbenchError("INVALID_FIELD",path+("healthy",),"expected bool")
    return Snapshot(sid,ch,created,tuple(sorted(tags)),healthy,size)


def validate_legal_hold(raw: Mapping, path: tuple = ("retention", "holds")) -> LegalHold:
    fields={"snapshot_id","reason"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    sid,reason=raw.get("snapshot_id"),raw.get("reason")
    if not isinstance(sid,str) or not sid: raise WorkbenchError("INVALID_FIELD",path+("snapshot_id",),"invalid string")
    if not isinstance(reason,str) or not reason: raise WorkbenchError("INVALID_FIELD",path+("reason",),"invalid string")
    return LegalHold(sid,reason)


def validate_retention_policy(raw: Mapping, path: tuple = ("retention", "policy")) -> RetentionPolicy:
    fields={"keep_last","max_age","protected_tags"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    kl,ma=raw.get("keep_last"),raw.get("max_age")
    if isinstance(kl,bool) or not isinstance(kl,int) or kl<0: raise WorkbenchError("INVALID_FIELD",path+("keep_last",),"invalid integer")
    if ma is not None and (isinstance(ma,bool) or not isinstance(ma,int) or ma<0): raise WorkbenchError("INVALID_FIELD",path+("max_age",),"invalid integer")
    tags=raw.get("protected_tags",[])
    if not isinstance(tags,list) or any(not isinstance(x,str) or not x for x in tags) or len(set(tags))!=len(tags): raise WorkbenchError("INVALID_FIELD",path+("protected_tags",),"invalid tags")
    return RetentionPolicy(kl,ma,tuple(sorted(tags)))


def apply_retention(snapshots: Sequence, holds: Sequence, policy: Mapping | RetentionPolicy, now: int) -> RetentionPlan:
    if isinstance(now,bool) or not isinstance(now,int): raise WorkbenchError("INVALID_FIELD",("now",),"invalid integer")
    pol=policy if isinstance(policy,RetentionPolicy) else validate_retention_policy(policy)
    vals=[]; by={}
    for i,s in enumerate(snapshots):
        x=validate_snapshot(s,("retention","snapshots",i))
        if x.snapshot_id in by:
            if x!=by[x.snapshot_id]: raise WorkbenchError("DUPLICATE_SNAPSHOT",("retention","snapshots",i),"conflicting duplicate")
            continue
        by[x.snapshot_id]=x; vals.append(x)
    hs={}
    for i,h in enumerate(holds):
        x=validate_legal_hold(h,("retention","holds",i))
        if x.snapshot_id not in by: raise WorkbenchError("MISSING_SNAPSHOT",("retention","holds",i,"snapshot_id"),"missing snapshot")
        if x.snapshot_id in hs and hs[x.snapshot_id]!=x.reason: raise WorkbenchError("DUPLICATE_HOLD",("retention","holds",i),"conflicting hold")
        hs[x.snapshot_id]=x.reason
    keep=set(); reason={}
    for s in vals:
        if s.snapshot_id in hs: keep.add(s.snapshot_id); reason[s.snapshot_id]="LEGAL_HOLD"
        elif set(s.tags)&set(pol.protected_tags): keep.add(s.snapshot_id); reason[s.snapshot_id]="PROTECTED_TAG"
    for ch in {s.channel for s in vals}:
        group=sorted([s for s in vals if s.channel==ch],key=lambda s:(-s.created_at,s.snapshot_id))
        for s in group[:pol.keep_last]:
            keep.add(s.snapshot_id); reason.setdefault(s.snapshot_id,"KEEP_LAST")
    cutoff=now-pol.max_age if pol.max_age is not None else None
    for s in vals:
        if cutoff is None or s.created_at>=cutoff:
            keep.add(s.snapshot_id); reason.setdefault(s.snapshot_id,"WITHIN_AGE")
    for ch in {s.channel for s in vals}:
        healthy=[s for s in vals if s.channel==ch and s.healthy]
        if len(healthy)==1:
            s=healthy[0]
            if s.snapshot_id not in keep and (cutoff is None or s.created_at<cutoff): keep.add(s.snapshot_id); reason[s.snapshot_id]="ONLY_HEALTHY"
    decisions=[]
    for s in sorted(vals,key=lambda s:(s.channel,s.created_at,s.snapshot_id)):
        if s.snapshot_id in keep: decisions.append(__import__(__name__.rsplit('.',1)[0]+'.models',fromlist=['RetentionDecision']).RetentionDecision(s.snapshot_id,"keep",reason[s.snapshot_id]))
        else: decisions.append(__import__(__name__.rsplit('.',1)[0]+'.models',fromlist=['RetentionDecision']).RetentionDecision(s.snapshot_id,"delete","AGE_EXCEEDED"))
    return RetentionPlan(tuple(decisions))

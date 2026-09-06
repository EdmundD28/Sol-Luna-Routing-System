from collections.abc import Mapping, Sequence
from types import MappingProxyType
import re
from functools import cmp_to_key
from ..errors import WorkbenchError
from ..frozen import freeze_json
from ..canonical import clone_json

from .models import ArtifactInventory, ArtifactRecord, ArtifactRequest


def validate_artifact(raw: Mapping, path: tuple = ("artifacts",)) -> ArtifactRecord:
    fields={"artifact_id","version","platform","architecture","features","checksum","size_bytes","metadata"}
    if not isinstance(raw, Mapping): raise WorkbenchError("INVALID_FIELD", path, "record must be an object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD", path+(k,), "unknown field", {"field":k})
    def s(k):
        v=raw.get(k)
        if not isinstance(v,str) or not v: raise WorkbenchError("INVALID_FIELD", path+(k,), "expected non-empty string")
        return v
    aid,ver,plat,arch=(s(k) for k in ("artifact_id","version","platform","architecture"))
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",ver):
        raise WorkbenchError("INVALID_VERSION",path+("version",),"malformed semantic version")
    fs=raw.get("features",[])
    if not isinstance(fs,list) or any(not isinstance(x,str) or not x for x in fs) or len(set(fs))!=len(fs): raise WorkbenchError("INVALID_FIELD",path+("features",),"invalid features")
    chk=raw.get("checksum")
    if chk is not None and (not isinstance(chk,str) or not re.fullmatch(r"[0-9a-f]{64}",chk)): raise WorkbenchError("INVALID_FIELD",path+("checksum",),"invalid checksum")
    size=raw.get("size_bytes",0)
    if isinstance(size,bool) or not isinstance(size,int) or size<0: raise WorkbenchError("INVALID_FIELD",path+("size_bytes",),"invalid size")
    meta=raw.get("metadata",{})
    if not isinstance(meta,Mapping): raise WorkbenchError("INVALID_FIELD",path+("metadata",),"expected object")
    try: meta=freeze_json(clone_json(meta))
    except WorkbenchError as e: raise WorkbenchError("INVALID_FIELD",path+("metadata",),"invalid metadata") from e
    return ArtifactRecord(aid,ver,plat,arch,tuple(sorted(fs)),chk,size,meta)


def validate_artifact_request(raw: Mapping, path: tuple = ("request",)) -> ArtifactRequest:
    fields={"artifact_id","platform","architecture","features","allow_prerelease"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"request must be an object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    vals=[]
    for k in ("artifact_id","platform","architecture"):
        v=raw.get(k)
        if not isinstance(v,str) or not v: raise WorkbenchError("INVALID_FIELD",path+(k,),"expected non-empty string")
        vals.append(v)
    fs=raw.get("features",[])
    if not isinstance(fs,list) or any(not isinstance(x,str) or not x for x in fs) or len(set(fs))!=len(fs): raise WorkbenchError("INVALID_FIELD",path+("features",),"invalid features")
    ap=raw.get("allow_prerelease",False)
    if not isinstance(ap,bool): raise WorkbenchError("INVALID_FIELD",path+("allow_prerelease",),"expected bool")
    return ArtifactRequest(*vals,tuple(sorted(fs)),ap)


def select_artifact(records: Sequence, request: Mapping | ArtifactRequest) -> ArtifactRecord:
    req=request if isinstance(request,ArtifactRequest) else validate_artifact_request(request)
    parsed=[]
    for i,r in enumerate(records): parsed.append((validate_artifact(r,("artifacts",i)),i))
    def verkey(v):
        base,_,pre=v.partition("-"); nums=tuple(int(x) for x in base.split(".")); ids=pre.split(".") if pre else None
        return nums,ids
    def cmp(a,b):
        na,pa=verkey(a.version); nb,pb=verkey(b.version)
        if na!=nb:return (na>nb)-(na<nb)
        if pa is None and pb is not None:return 1
        if pa is not None and pb is None:return -1
        if pa==pb:return 0
        for x,y in zip(pa or (),pb or ()):
            if x==y:continue
            if x.isdigit() and y.isdigit(): return (int(x)>int(y))-(int(x)<int(y))
            if x.isdigit()!=y.isdigit(): return -1 if x.isdigit() else 1
            return (x>y)-(x<y)
        return (len(pa or ())>len(pb or ()))-(len(pa or ())<len(pb or ()))
    candidates=[(r,i) for r,i in parsed if r.artifact_id==req.artifact_id and r.platform==req.platform and r.architecture==req.architecture and set(r.features)>=set(req.features) and (req.allow_prerelease or "-" not in r.version)]
    if not candidates: raise WorkbenchError("NO_COMPATIBLE_ARTIFACT",(),"no compatible artifact",{"versions":tuple(sorted({r.version for r,_ in parsed}))})
    candidates.sort(key=cmp_to_key(lambda x,y: cmp(x[0],y[0]) or ((x[0].size_bytes>y[0].size_bytes)-(x[0].size_bytes<y[0].size_bytes)) or (( (x[0].checksum or "",x[0].artifact_id) < (y[0].checksum or "",y[0].artifact_id)) - ((x[0].checksum or "",x[0].artifact_id) > (y[0].checksum or "",y[0].artifact_id)))), reverse=True)
    chosen,idx=candidates[0]
    if chosen.checksum is None: raise WorkbenchError("MISSING_CHECKSUM",("artifacts",idx,"checksum"),"checksum required")
    return chosen


def build_inventory(records: Sequence) -> ArtifactInventory:
    parsed=[]; seen={}
    for i,r in enumerate(records):
        a=validate_artifact(r,("artifacts",i)); ident=(a.artifact_id,a.version,a.platform,a.architecture,a.features)
        if ident in seen:
            if a!=seen[ident]: raise WorkbenchError("DUPLICATE_ARTIFACT",("artifacts",i),"conflicting duplicate",{"identity":ident})
            continue
        seen[ident]=a; parsed.append(a)
    def vk(a):
        nums=tuple(int(x) for x in a.version.split("-",1)[0].split(".")); pre=a.version.split("-",1)[1] if "-" in a.version else "~"; return (a.artifact_id,tuple(-x for x in nums),pre,a.platform,a.architecture,a.features,a.checksum or "")
    parsed.sort(key=vk)
    bp={}
    for a in parsed: bp.setdefault(a.platform,[]).append(a.artifact_id)
    return ArtifactInventory(tuple(parsed),MappingProxyType({k:tuple(sorted(set(v))) for k,v in sorted(bp.items())}))

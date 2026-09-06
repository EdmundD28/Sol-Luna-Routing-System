from collections.abc import Mapping, Sequence
from ..errors import WorkbenchError

from .models import PatchGraph, PatchPlan, PatchRecord


def validate_patch(raw: Mapping, path: tuple = ("patches",)) -> PatchRecord:
    fields={"patch_id","file","start","end","replacement","depends_on"}
    if not isinstance(raw,Mapping): raise WorkbenchError("INVALID_FIELD",path,"expected object")
    for k in raw:
        if k not in fields: raise WorkbenchError("UNKNOWN_FIELD",path+(k,),"unknown field",{"field":k})
    def text(k):
        v=raw.get(k)
        if not isinstance(v,str) or not v: raise WorkbenchError("INVALID_FIELD",path+(k,),"invalid string")
        return v
    pid,file,repl=text("patch_id"),text("file"),raw.get("replacement")
    if not isinstance(repl,str): raise WorkbenchError("INVALID_FIELD",path+("replacement",),"invalid string")
    def num(k):
        v=raw.get(k)
        if isinstance(v,bool) or not isinstance(v,int) or v<0: raise WorkbenchError("INVALID_FIELD",path+(k,),"invalid offset")
        return v
    start,end=num("start"),num("end")
    if end<start: raise WorkbenchError("INVALID_FIELD",path+("end",),"reverse range")
    dep=raw.get("depends_on",[])
    if not isinstance(dep,list) or any(not isinstance(x,str) or not x for x in dep) or len(set(dep))!=len(dep): raise WorkbenchError("INVALID_FIELD",path+("depends_on",),"invalid dependencies")
    return PatchRecord(pid,file,start,end,repl,tuple(dep))


def build_patch_graph(patches: Sequence) -> PatchGraph:
    vals=[]; by={}
    for i,p in enumerate(patches):
        x=validate_patch(p,("patches",i))
        if x.patch_id in by:
            if x!=by[x.patch_id]: raise WorkbenchError("DUPLICATE_PATCH",("patches",i),"conflicting duplicate")
            continue
        by[x.patch_id]=x; vals.append(x)
    for x in vals:
        for j,d in enumerate(x.depends_on):
            if d not in by: raise WorkbenchError("MISSING_DEPENDENCY",("patches",vals.index(x),"depends_on",j),"missing dependency")
    visiting=[]; done=set()
    def visit(k):
        if k in visiting:
            members=tuple(sorted(visiting[visiting.index(k):])); raise WorkbenchError("DEPENDENCY_CYCLE",("patches","dependencies"),"dependency cycle",{"members":members})
        if k in done:return
        visiting.append(k)
        for d in by[k].depends_on: visit(d)
        visiting.pop(); done.add(k)
    for k in by:visit(k)
    conflicts=[]
    sv=sorted(vals,key=lambda p:p.patch_id)
    for i,a in enumerate(sv):
        for b in sv[i+1:]:
            if a.file!=b.file:continue
            overlap=(a.start<b.end and b.start<a.end) if a.start<a.end and b.start<b.end else (a.start==b.start if a.start==a.end and b.start==b.end else (a.start>b.start and a.start<b.end) or (b.start>a.start and b.start<a.end))
            if overlap:
                code="PATCH_DUPLICATE_BOUNDARY" if a.start==a.end==b.start==b.end else "PATCH_OVERLAP"
                raise WorkbenchError(code,("patches",b.patch_id,"range"),"conflicting ranges",{"patches":(a.patch_id,b.patch_id)})
    deps=tuple(sorted((d,x.patch_id) for x in vals for d in x.depends_on))
    return PatchGraph(tuple(sv),deps,tuple(conflicts))


def plan_patch_waves(patches: Sequence) -> PatchPlan:
    graph=build_patch_graph(patches); by={p.patch_id:p for p in graph.nodes}; remaining=set(by); done=set(); waves=[]
    while remaining:
        eligible=sorted(k for k in remaining if set(by[k].depends_on)<=done)
        wave=[]; files=set()
        for k in eligible:
            if by[k].file not in files: wave.append(k); files.add(by[k].file)
        if not wave: break
        waves.append(tuple(wave)); done.update(wave); remaining-=set(wave)
    return PatchPlan(tuple(waves))

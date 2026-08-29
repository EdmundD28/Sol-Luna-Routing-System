#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline, descriptive communication metrics; never a routing or billing oracle."""
from __future__ import annotations
import argparse, contextlib, hashlib, io, json, math, sys, unicodedata
from collections.abc import Mapping
from typing import Any

class AuditError(ValueError): pass
ProtocolError = AuditError
SCHEMA_VERSION = 1
_ROOT = {"schema_version","arm_id","protocol","task_digest","acceptance_digest","candidate_digest","controller_model","controller_effort","luna_model","luna_effort","messages","controller_noncached_input_tokens","controller_token_source","controller_full_reread","controller_reimplemented","elapsed_seconds","quality"}
_MESSAGE = {"message_id","direction","content","measured_tokens","token_source"}
_DIRECTIONS = ("SOL_TO_LUNA_MANIFEST","SOL_TO_LUNA_INITIAL","LUNA_TO_SOL_RECEIPT","SOL_TO_LUNA_REPAIR")
_SOURCES = {"provider_exact","external_estimate","unavailable"}

def _constant(v: str) -> Any: raise AuditError("non-finite JSON value")
def _pairs(pairs):
    d = {}
    for k,v in pairs:
        if k in d: raise AuditError("duplicate JSON key")
        d[k] = v
    return d
def load_json_strict(text: str) -> Any:
    try: return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except AuditError: raise
    except (json.JSONDecodeError, TypeError) as e: raise AuditError("invalid JSON") from e
def load_input(path: str) -> dict[str,Any]:
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return validate_arm(load_json_strict(handle.read()))
    except OSError as e: raise AuditError("cannot read input") from e
def _safe(v, field, *, compact=False, allow_controls=False):
    if not isinstance(v,str) or not v or (not allow_controls and any(ord(c)<32 or ord(c)==127 for c in v)): raise AuditError(f"{field} must be a non-empty safe string")
    if compact and (len(v)>64 or not v[0].isalnum() or any(not(c.isalnum() or c in "._-") for c in v)): raise AuditError(f"{field} must be compact")
    return v
def _digest(v, field):
    v=_safe(v,field)
    if not (v.startswith("sha256:") and len(v)==71 and v[7:].lower()==v[7:] and all(c in "0123456789abcdef" for c in v[7:])): raise AuditError(f"{field} must be sha256:<64 lowercase hex>")
    return v
def _int(v,field,nullable=False):
    if v is None and nullable:return None
    if isinstance(v,bool) or not isinstance(v,int) or v<0: raise AuditError(f"{field} must be a non-negative integer or null")
    return v
def _measurement(v, source, field):
    if source not in _SOURCES: raise AuditError(f"{field}.token_source is invalid")
    if source == "unavailable" and v is not None: raise AuditError(f"{field} unavailable requires null")
    if source != "unavailable" and (isinstance(v,bool) or not isinstance(v,int) or v<0): raise AuditError(f"{field} measured_tokens required")
    return v
def validate_arm(raw: Any) -> dict[str,Any]:
    if not isinstance(raw,Mapping) or set(raw)!=_ROOT: raise AuditError("arm has unknown or missing fields")
    if isinstance(raw["schema_version"],bool) or not isinstance(raw["schema_version"],int) or raw["schema_version"]!=1: raise AuditError("schema_version must be integer 1")
    out={"schema_version":1,"arm_id":_safe(raw["arm_id"],"arm_id",compact=True),"protocol":raw["protocol"]}
    if out["protocol"] not in {"natural","compact"}: raise AuditError("protocol is invalid")
    for f in ("task_digest","acceptance_digest","candidate_digest"): out[f]=_digest(raw[f],f)
    for f in ("controller_model","controller_effort","luna_model","luna_effort"): out[f]=_safe(raw[f],f)
    msgs=raw["messages"]
    if not isinstance(msgs,list) or not msgs: raise AuditError("messages must be non-empty")
    outmsgs=[]; ids=set()
    for i,m in enumerate(msgs):
        if not isinstance(m,Mapping) or set(m)!=_MESSAGE: raise AuditError(f"messages[{i}] has unknown or missing fields")
        mid=_safe(m["message_id"],f"messages[{i}].message_id",compact=True)
        if mid.casefold() in ids: raise AuditError("duplicate message_id")
        ids.add(mid.casefold()); direction=m["direction"]
        if direction not in _DIRECTIONS: raise AuditError("invalid message direction")
        content=_safe(m["content"],f"messages[{i}].content",allow_controls=True)
        source=m["token_source"]; measured=_measurement(m["measured_tokens"],source,f"messages[{i}]")
        outmsgs.append({"message_id":mid,"direction":direction,"content":content,"measured_tokens":measured,"token_source":source})
    out["messages"]=outmsgs
    out["controller_noncached_input_tokens"]=_int(raw["controller_noncached_input_tokens"],"controller_noncached_input_tokens",True)
    _measurement(out["controller_noncached_input_tokens"],raw["controller_token_source"],"controller")
    out["controller_token_source"] = raw["controller_token_source"]
    for f in ("controller_full_reread","controller_reimplemented"):
        if not isinstance(raw[f],bool): raise AuditError(f"{f} must be boolean")
        out[f]=raw[f]
    elapsed=raw["elapsed_seconds"]
    if isinstance(elapsed,bool) or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<0: raise AuditError("elapsed_seconds must be finite and non-negative")
    out["elapsed_seconds"]=elapsed
    q=raw["quality"]
    if not isinstance(q,Mapping) or set(q)!={"passed","total","defects"}: raise AuditError("quality must have exact fields")
    for f in q:
        _int(q[f],f)
    if q["total"]<=0 or q["passed"]>q["total"]: raise AuditError("quality counts are invalid")
    out["quality"]={f:q[f] for f in ("passed","total","defects")}
    dirs=[m["direction"] for m in outmsgs]
    if "SOL_TO_LUNA_INITIAL" not in dirs or "LUNA_TO_SOL_RECEIPT" not in dirs: raise AuditError("initial and receipt messages required")
    if dirs.index("LUNA_TO_SOL_RECEIPT") < dirs.index("SOL_TO_LUNA_INITIAL"): raise AuditError("receipt must follow initial message")
    if out["protocol"]=="compact":
        first=dirs.index("SOL_TO_LUNA_INITIAL")
        if dirs[:first].count("SOL_TO_LUNA_MANIFEST")!=1 or any(d=="SOL_TO_LUNA_MANIFEST" for d in dirs[first:]): raise AuditError("compact requires exactly one manifest before first initial")
    elif "SOL_TO_LUNA_MANIFEST" in dirs: raise AuditError("natural cannot contain manifest")
    return out

def lexical_units(text: str) -> list[str]:
    text=unicodedata.normalize("NFC",text).casefold(); result=[]; buf=[]
    def flush():
        if buf: result.append("".join(buf)); buf.clear()
    for c in text:
        name=unicodedata.name(c,""); cat=unicodedata.category(c)
        if "CJK UNIFIED IDEOGRAPH" in name or "CJK COMPATIBILITY IDEOGRAPH" in name or 0x3400<=ord(c)<=0x4DBF:
            flush(); result.append(c)
        elif cat[0] in "LN" or cat.startswith("M"):
            buf.append(c)
        else: flush()
    flush(); return result
def _repetition(msgs):
    seen=set(); per=[]; total_rep=total_units=0
    for i,m in enumerate(msgs):
        units=lexical_units(m["content"]); total_units += len(units)
        rep=0
        if i:
            covered=set()
            for j in range(max(0,len(units)-4)):
                if tuple(units[j:j+5]) in seen: covered.update(range(j,j+5))
            rep=len(covered)
        if i: per.append({"message_id":m["message_id"],"repeated_lexical_units":rep,"total_lexical_units":len(units),"ratio":rep/len(units) if units else 0.0})
        for j in range(max(0,len(units)-4)): seen.add(tuple(units[j:j+5]))
        total_rep += rep
    return {"repeated_lexical_units":total_rep,"total_lexical_units":total_units,"ratio":total_rep/total_units if total_units else 0.0,"per_later_message":per}
def _aggregate(msgs, directions):
    selected=[m for m in msgs if m["direction"] in directions]; vals=[m["measured_tokens"] for m in selected]; sources={m["token_source"] for m in selected}
    return {"messages":len(selected),"bytes":sum(len(m["content"].encode("utf-8")) for m in selected),"lexical_units":sum(len(lexical_units(m["content"])) for m in selected),"measured_tokens":sum(vals) if vals and len(sources)==1 and "unavailable" not in sources else None,"measurement_source":next(iter(sources)) if len(sources)==1 else ("mixed" if sources else "unavailable"),"measurement_uncertain":not(vals and len(sources)==1 and "unavailable" not in sources)}
def audit(raw: Mapping[str,Any]) -> dict[str,Any]:
    arm=validate_arm(raw); msgs=arm["messages"]
    groups={"sol_to_luna_initial_handoff":("SOL_TO_LUNA_MANIFEST","SOL_TO_LUNA_INITIAL"),"luna_to_sol_receipts":("LUNA_TO_SOL_RECEIPT",),"sol_to_luna_repairs":("SOL_TO_LUNA_REPAIR",),"total_communication":_DIRECTIONS}
    return {"schema_version":1,"arm_id":arm["arm_id"],"protocol":arm["protocol"],"message_metrics":[{"message_id":m["message_id"],"direction":m["direction"],"bytes":len(m["content"].encode("utf-8")),"lexical_units":len(lexical_units(m["content"]))} for m in msgs],"aggregates":{k:_aggregate(msgs,v) for k,v in groups.items()},"repetition":_repetition(msgs),"controller_noncached_input_tokens":arm["controller_noncached_input_tokens"],"controller_token_source":arm["controller_token_source"],"controller_full_reread":arm["controller_full_reread"],"controller_reimplemented":arm["controller_reimplemented"],"elapsed_seconds":arm["elapsed_seconds"],"quality":arm["quality"],"included_plan_conclusion_allowed":False}

def compare(natural: Mapping[str,Any], compact: Mapping[str,Any]) -> dict[str,Any]:
    n=validate_arm(natural); c=validate_arm(compact)
    for f in ("task_digest","acceptance_digest","controller_model","controller_effort","luna_model","luna_effort"):
        if n[f]!=c[f]: raise AuditError(f"matched identity mismatch: {f}")
    if n["protocol"]!="natural" or c["protocol"]!="compact": raise AuditError("compare requires natural then compact arms")
    na,ca=audit(n),audit(c); nb,cb=na["aggregates"]["total_communication"]["bytes"],ca["aggregates"]["total_communication"]["bytes"]
    nu,cu=na["aggregates"]["total_communication"]["lexical_units"],ca["aggregates"]["total_communication"]["lexical_units"]
    red=lambda x,y: (x-y)/x if x else 0.0
    quality_ok=c["quality"]["passed"]>=n["quality"]["passed"] and c["quality"]["defects"]<=n["quality"]["defects"]
    reasons=[]
    if red(nu,cu)<.70: reasons.append("compact lexical communication reduction is below 70%")
    if not quality_ok: reasons.append("compact quality is worse")
    if c["elapsed_seconds"]>n["elapsed_seconds"]: reasons.append("compact elapsed time is greater")
    if c["controller_full_reread"] or c["controller_reimplemented"]: reasons.append("compact controller reread or reimplemented")
    exact=all(m["token_source"]=="provider_exact" and m["measured_tokens"] is not None for m in n["messages"]+c["messages"]) and n["controller_token_source"]==c["controller_token_source"]=="provider_exact" and n["controller_noncached_input_tokens"] is not None and c["controller_noncached_input_tokens"] is not None
    provider_reasons=[]
    if not exact: provider_reasons.append("comparable provider_exact message and controller evidence is missing")
    else:
        if ca["aggregates"]["total_communication"]["measured_tokens"]>=na["aggregates"]["total_communication"]["measured_tokens"]: provider_reasons.append("compact measured communication tokens did not decrease")
        if c["controller_noncached_input_tokens"]>=n["controller_noncached_input_tokens"]: provider_reasons.append("compact controller tokens did not decrease")
    nmt=na["aggregates"]["total_communication"]["measured_tokens"]; cmt=ca["aggregates"]["total_communication"]["measured_tokens"]
    return {"natural":na,"compact":ca,"reductions":{"bytes":nb-cb,"lexical_units":nu-cu,"bytes_ratio":red(nb,cb),"lexical_units_ratio":red(nu,cu),"repeated_lexical_units":na["repetition"]["repeated_lexical_units"]-ca["repetition"]["repeated_lexical_units"],"repeated_lexical_units_ratio_change":ca["repetition"]["ratio"]-na["repetition"]["ratio"],"measured_tokens":nmt-cmt if exact else None,"controller_noncached_input_tokens":n["controller_noncached_input_tokens"]-c["controller_noncached_input_tokens"] if exact else None,"controller_full_reread_changed":n["controller_full_reread"] != c["controller_full_reread"],"controller_reimplemented_changed":n["controller_reimplemented"] != c["controller_reimplemented"],"elapsed_seconds":n["elapsed_seconds"]-c["elapsed_seconds"],"quality_passed":c["quality"]["passed"]-n["quality"]["passed"],"quality_defects":c["quality"]["defects"]-n["quality"]["defects"]},"mechanism_gate_passed":not reasons,"mechanism_gate_reasons":reasons,"provider_gate_passed":(not reasons) and exact and not provider_reasons,"provider_gate_reasons":provider_reasons if not reasons else reasons[:1]+provider_reasons,"included_plan_conclusion_allowed":False}

def _json(v): return json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)
def main(argv=None):
    p=argparse.ArgumentParser(add_help=False); sub=p.add_subparsers(dest="cmd",required=True); a=sub.add_parser("audit",add_help=False); a.add_argument("--input",required=True); q=sub.add_parser("compare",add_help=False); q.add_argument("--natural",required=True); q.add_argument("--compact",required=True)
    try:
        with contextlib.redirect_stderr(io.StringIO()): x=p.parse_args(argv)
        out=audit(load_input(x.input)) if x.cmd=="audit" else compare(load_input(x.natural),load_input(x.compact)); sys.stdout.write(_json(out)+"\n"); return 0
    except (AuditError, OSError, argparse.ArgumentError, SystemExit) as e: sys.stderr.write("communication_audit: invalid arguments or input\n"); return 2
if __name__=="__main__": raise SystemExit(main())

"""Validation and normalization boundary."""
from typing import Any
from collections.abc import Mapping
import re
from .model import *
from .conditions import normalize_condition
NAME=re.compile(r'^[a-z][a-z0-9_-]*$'); ID=re.compile(r'^[A-Z][A-Z0-9_]*$')
def err(code,path): raise PolicyError(code,path)
def scalar(v): return type(v) in (str,int,bool) or v is None
def attrs(v,path):
    if not isinstance(v,Mapping): err('INVALID_TYPE',path)
    out={}
    for k in sorted(v):
        if not isinstance(k,str) or not NAME.fullmatch(k): err('INVALID_NAME',path+(k,))
        x=v[k]
        if isinstance(x,Mapping): out[k]=attrs(x,path+(k,))
        elif scalar(x): out[k]=x
        else: err('INVALID_SCALAR',path+(k,))
    return out
def amap(t): return dict(t)
def seq_names(v,path):
    if not isinstance(v,(list,tuple)): err('INVALID_TYPE',path)
    out=[]
    for i,x in enumerate(v):
        if not isinstance(x,str) or not NAME.fullmatch(x): err('INVALID_NAME',path+(i,))
        if x in out: err('DUPLICATE_VALUE',path+(i,))
        out.append(x)
    return tuple(sorted(out))
def ids(v,path):
    if not isinstance(v,(list,tuple)): err('INVALID_TYPE',path)
    out=[]
    for i,x in enumerate(v):
        if not isinstance(x,str) or not ID.fullmatch(x): err('INVALID_ID',path+(i,))
        if x in out: err('DUPLICATE_VALUE',path+(i,))
        out.append(x)
    return tuple(sorted(out))
def selector(v,path,resource=False):
    if not isinstance(v,Mapping): err('INVALID_TYPE',path)
    req=('ids','kinds','tags') if resource else ('ids','roles','groups')
    for k in req:
        if k not in v: err('MISSING_FIELD',path+(k,))
    u=sorted(set(v)-set(req))
    if u: err('UNKNOWN_FIELD',path+(u[0],))
    if resource:
        tags=v['tags']
        if not isinstance(tags,Mapping): err('INVALID_TYPE',path+('tags',))
        td={}
        for k in sorted(tags):
            if not isinstance(k,str) or not NAME.fullmatch(k): err('INVALID_NAME',path+('tags',k))
            vals=tags[k]
            if not isinstance(vals,(list,tuple)) or not vals: err('INVALID_TYPE',path+('tags',k))
            arr=[]
            for i,x in enumerate(vals):
                if not scalar(x): err('INVALID_SCALAR',path+('tags',k,i))
                if any(type(x)==type(y) and x==y for y in arr): err('DUPLICATE_VALUE',path+('tags',k,i))
                arr.append(x)
            td[k]=tuple(sorted(arr,key=lambda x:(type(x).__name__,repr(x))))
        return ResourceSelector(ids(v['ids'],path+('ids',)),seq_names(v['kinds'],path+('kinds',)),tuple((k,td[k]) for k in td))
    return Selector(ids(v['ids'],path+('ids',)),seq_names(v['roles'],path+('roles',)),seq_names(v['groups'],path+('groups',)))
def normalize_rules(raw_rules: Any):
    if not isinstance(raw_rules,(list,tuple)): err('INVALID_TYPE',('rules',))
    out=[]; seen=set()
    for i,r in enumerate(raw_rules):
        p=('rules',i)
        if not isinstance(r,Mapping): err('INVALID_TYPE',p)
        fields=('id','effect','priority','subject','resource','actions','when')
        for k in fields:
            if k not in r: err('MISSING_FIELD',p+(k,))
        u=sorted(set(r)-set(fields))
        if u: err('UNKNOWN_FIELD',p+(u[0],))
        rid=r['id'];
        if not isinstance(rid,str) or not ID.fullmatch(rid): err('INVALID_ID',p+('id',))
        if rid in seen: err('DUPLICATE_ID',p+('id',))
        seen.add(rid)
        if r['effect'] not in ('allow','deny'): err('INVALID_EFFECT',p+('effect',))
        if type(r['priority']) is not int or not 0<=r['priority']<=1000: err('INVALID_INTEGER',p+('priority',))
        acts=r['actions']
        if not isinstance(acts,(list,tuple)) or not acts: err('INVALID_ACTION',p+('actions',))
        aa=[]
        for j,a in enumerate(acts):
            if not isinstance(a,str) or a=='': err('INVALID_ACTION',p+('actions',j))
            if a!='*':
                parts=a.split(':'); prefix=parts[-1]=='*'
                if prefix: parts=parts[:-1]
                if not parts or any(not NAME.fullmatch(x) for x in parts): err('INVALID_ACTION',p+('actions',j))
                if prefix and a.endswith(':*') is False: err('INVALID_ACTION',p+('actions',j))
            if a in aa: err('DUPLICATE_VALUE',p+('actions',j))
            aa.append(a)
        when=r['when']
        out.append(NormalizedRule(rid,r['effect'],r['priority'],selector(r['subject'],p+('subject',)),selector(r['resource'],p+('resource',),True),tuple(sorted(aa)),None if when is None else normalize_condition(when,p+('when',))))
    return tuple(sorted(out,key=lambda x:x.id))
def normalize_request(raw_request: Any):
    p=('request',)
    if not isinstance(raw_request,Mapping): err('INVALID_TYPE',p)
    fields=('subject','resource','action','context')
    for k in fields:
        if k not in raw_request: err('MISSING_FIELD',p+(k,))
    u=sorted(set(raw_request)-set(fields))
    if u: err('UNKNOWN_FIELD',p+(u[0],))
    s=raw_request['subject']; rp=p+('subject',)
    if not isinstance(s,Mapping): err('INVALID_TYPE',rp)
    for k in ('id','roles','groups','attrs'):
        if k not in s: err('MISSING_FIELD',rp+(k,))
    u=sorted(set(s)-{'id','roles','groups','attrs'});
    if u: err('UNKNOWN_FIELD',rp+(u[0],))
    if not isinstance(s['id'],str) or not ID.fullmatch(s['id']): err('INVALID_ID',rp+('id',))
    rs=raw_request['resource']; qp=p+('resource',)
    if not isinstance(rs,Mapping): err('INVALID_TYPE',qp)
    for k in ('id','kind','tags','attrs'):
        if k not in rs: err('MISSING_FIELD',qp+(k,))
    u=sorted(set(rs)-{'id','kind','tags','attrs'});
    if u: err('UNKNOWN_FIELD',qp+(u[0],))
    if not isinstance(rs['id'],str) or not ID.fullmatch(rs['id']): err('INVALID_ID',qp+('id',))
    if not isinstance(rs['kind'],str) or not NAME.fullmatch(rs['kind']): err('INVALID_NAME',qp+('kind',))
    tags=rs['tags'];
    if not isinstance(tags,Mapping): err('INVALID_TYPE',qp+('tags',))
    td={}
    for k in sorted(tags):
        if not isinstance(k,str) or not NAME.fullmatch(k): err('INVALID_NAME',qp+('tags',k))
        if not scalar(tags[k]): err('INVALID_SCALAR',qp+('tags',k))
        td[k]=tags[k]
    a=raw_request['action']; parts=a.split(':') if isinstance(a,str) else []
    if not parts or any(not NAME.fullmatch(x) for x in parts): err('INVALID_ACTION',p+('action',))
    return Request(RequestSubject(s['id'],seq_names(s['roles'],rp+('roles',)),seq_names(s['groups'],rp+('groups',)),amap(attrs(s['attrs'],rp+('attrs',)))),RequestResource(rs['id'],rs['kind'],td,amap(attrs(rs['attrs'],qp+('attrs',)))),a,amap(attrs(raw_request['context'],p+('context',))))

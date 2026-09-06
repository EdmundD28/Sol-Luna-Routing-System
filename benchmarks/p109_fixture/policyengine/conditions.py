"""Recursive condition boundary."""
from .model import Condition, PolicyError
from .attributes import lookup_attribute, MISSING
from collections.abc import Mapping
import re
NAME=re.compile(r'^[a-z][a-z0-9_-]*$'); OPS={'eq','ne','in','not_in','contains','lt','le','gt','ge','exists'}
def _scalar(v): return type(v) in (str,int,bool) or v is None
def _lit(v): return (type(v).__name__,repr(v))
def _key(c):
    if c.kind in ('all','any'): return (0 if c.kind=='all' else 1, tuple(sorted((_key(x) for x in c.data))))
    if c.kind=='not': return (2,_key(c.data))
    path,op,val=c.data; return (3,tuple(path),op,(2,) if op=='exists' else (1,tuple(_lit(x) for x in val)) if op in ('in','not_in') else (0,)+_lit(val))
def normalize_condition(raw_condition,path=(),depth=1,counter=None):
    if counter is None: counter=[0]
    if depth>8: raise PolicyError('CONDITION_DEPTH',path)
    counter[0]+=1
    if counter[0]>64: raise PolicyError('CONDITION_SIZE',path)
    if not isinstance(raw_condition,Mapping): raise PolicyError('INVALID_TYPE',path)
    keys=set(raw_condition); forms=[k for k in ('all','any','not','path') if k in keys]
    if len(forms)!=1: raise PolicyError('INVALID_CONDITION',path)
    form=forms[0]
    allowed={'all'} if form=='all' else {'any'} if form=='any' else {'not'} if form=='not' else {'path','op','value'}
    if form=='path' and raw_condition.get('op')=='exists': allowed={'path','op'}
    unknown=sorted(keys-allowed)
    if unknown: raise PolicyError('UNKNOWN_FIELD',path+(unknown[0],))
    if form in ('all','any'):
        xs=raw_condition[form]
        if not isinstance(xs,(list,tuple)) or not xs: raise PolicyError('INVALID_CONDITION',path+(form,))
        vals=[normalize_condition(x,path+(form,i),depth+1,counter) for i,x in enumerate(xs)]
        return Condition(form,tuple(sorted(vals,key=_key)))
    if form=='not': return Condition('not',normalize_condition(raw_condition['not'],path+('not',),depth+1,counter))
    if 'op' not in raw_condition: raise PolicyError('MISSING_FIELD',path+('op',))
    op=raw_condition['op']
    if op not in OPS: raise PolicyError('INVALID_OPERATOR',path+('op',))
    if 'value' not in raw_condition and op!='exists': raise PolicyError('MISSING_FIELD',path+('value',))
    p=raw_condition['path']
    if not isinstance(p,(list,tuple)) or len(p)<2: raise PolicyError('INVALID_PATH',path+('path',))
    if p[0] not in ('subject','resource','context'): raise PolicyError('INVALID_PATH',path+('path',))
    start=2 if p[0] in ('subject','resource') else 1
    if p[0] in ('subject','resource') and len(p)<3 or len(p)<=start: raise PolicyError('INVALID_PATH',path+('path',))
    for i,x in enumerate(p):
        if not isinstance(x,str) or (i>=start and not NAME.fullmatch(x)): raise PolicyError('INVALID_PATH',path+('path',i))
    if p[0] in ('subject','resource') and p[1]!='attrs': raise PolicyError('INVALID_PATH',path+('path',1))
    if op in ('in','not_in'):
        v=raw_condition['value']
        if not isinstance(v,(list,tuple)) or not v: raise PolicyError('INVALID_SCALAR',path+('value',))
        out=[]
        for i,x in enumerate(v):
            if not _scalar(x): raise PolicyError('INVALID_SCALAR',path+('value',i))
            if any(type(x)==type(y) and x==y for y in out): raise PolicyError('DUPLICATE_VALUE',path+('value',i))
            out.append(x)
        v=tuple(sorted(out,key=_lit))
    elif op!='exists':
        v=raw_condition['value']
        if not _scalar(v): raise PolicyError('INVALID_SCALAR',path+('value',))
    else: v=None
    return Condition('leaf',(tuple(p),op,v))
def evaluate_condition(c,request):
    if c.kind=='all': return all(evaluate_condition(x,request) for x in c.data)
    if c.kind=='any': return any(evaluate_condition(x,request) for x in c.data)
    if c.kind=='not': return not evaluate_condition(c.data,request)
    p,op,v=c.data; root={'subject':request.subject,'resource':request.resource,'context':request.context}[p[0]]
    val=lookup_attribute(root,p[1:] if p[0]=='context' else p[1:])
    if op=='exists': return val is not MISSING
    if val is MISSING: return False
    if op=='eq': return type(val)==type(v) and val==v
    if op=='ne': return type(val)!=type(v) or val!=v
    if op in ('in','not_in'):
        yes=any(type(val)==type(x) and val==x for x in v); return yes if op=='in' else not yes
    if op=='contains': return isinstance(val,str) and isinstance(v,str) and v in val
    if op in ('lt','le','gt','ge'):
        if type(val) is not int or type(v) is not int:return False
        return {'lt':val<v,'le':val<=v,'gt':val>v,'ge':val>=v}[op]

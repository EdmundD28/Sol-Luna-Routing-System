"""Priority, specificity, deny override, and winner boundary."""
from .selectors import matches_action
def specificity(rule, request):
    ok,exact,prefix=matches_action(rule.actions,request.action)
    return (bool(rule.subject.ids),bool(rule.resource.ids),exact,prefix,bool(rule.resource.kinds),len(rule.resource.tags),bool(rule.subject.roles),bool(rule.subject.groups),count(rule.when))
def count(c):
    if c is None:return 0
    if c.kind in ('all','any'):return 1+sum(count(x) for x in c.data)
    if c.kind=='not':return 1+count(c.data)
    return 1
def choose_winner(matched, request):
    if not matched:return (None,(), 'deny','default_deny')
    bestp=max(x.priority for x in matched); cand=[x for x in matched if x.priority==bestp]
    bests=max(specificity(x,request) for x in cand); dec=sorted((x for x in cand if specificity(x,request)==bests),key=lambda x:x.id)
    effect='deny' if any(x.effect=='deny' for x in dec) else 'allow'; winner=next(x.id for x in dec if x.effect==effect)
    return winner,tuple(x.id for x in dec),effect,'explicit_deny' if effect=='deny' else 'allow'

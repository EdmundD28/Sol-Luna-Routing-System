"""The sole public operation."""
from .normalize import normalize_rules,normalize_request
from .selectors import matches_subject,matches_resource,matches_action
from .conditions import evaluate_condition
from .precedence import choose_winner
from .model import Decision
def evaluate_access(raw_rules,raw_request):
    rules=normalize_rules(raw_rules); req=normalize_request(raw_request)
    matched=[]
    for r in rules:
        if matches_subject(r.subject,req.subject) and matches_resource(r.resource,req.resource) and matches_action(r.actions,req.action)[0] and (r.when is None or evaluate_condition(r.when,req)): matched.append(r)
    winner,dec,effect,reason=choose_winner(matched,req)
    return Decision(effect,winner,tuple(x.id for x in matched),dec,reason)

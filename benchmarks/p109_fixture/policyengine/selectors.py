"""Subject, resource, and action selector boundary."""
def matches_subject(selector, subject):
    return (not selector.ids or subject.id in selector.ids) and (not selector.roles or any(x in subject.roles for x in selector.roles)) and (not selector.groups or any(x in subject.groups for x in selector.groups))
def matches_resource(selector, resource):
    return (not selector.ids or resource.id in selector.ids) and (not selector.kinds or resource.kind in selector.kinds) and all(k in resource.tags and any(type(resource.tags[k])==type(v) and resource.tags[k]==v for v in vs) for k,vs in selector.tags)
def matches_action(patterns, action):
    for p in patterns:
        if p=='*':return (True,0,0)
        if p==action:return (True,1,0)
        if p.endswith(':*'):
            pre=p[:-2]
            if action==pre or action.startswith(pre+':'): return (True,0,len(pre))
        elif p==action:return (True,1,0)
    return (False,0,0)

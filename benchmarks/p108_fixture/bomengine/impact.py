from .model import BomError

def _err(code, path):
    raise BomError(code, tuple(path))

def compute_impact(initial, final, changes, removed):
    initial_map = {item.id: item for item in initial}
    final_map = {item.id: item for item in final}
    for component in final:
        for index, dependency in enumerate(component.depends_on):
            if dependency not in final_map:
                _err("MISSING_DEPENDENCY", ("final", component.id, "depends_on", index))
    checked_pairs = set()
    for component in final:
        for other in component.excludes:
            if other in final_map:
                pair = tuple(sorted((component.id, other)))
                if pair not in checked_pairs:
                    checked_pairs.add(pair)
                    owner, peer = pair
                    owner_excludes = tuple(sorted(set(final_map[owner].excludes) | {peer}))
                    _err("EXCLUSION_CONFLICT", ("final", owner, "excludes", owner_excludes.index(peer)))
    reverse_initial = {item.id: [] for item in initial}
    for item in initial:
        for dependency in item.depends_on:
            reverse_initial[dependency].append(item.id)
    reverse_final = {item.id: [] for item in final}
    for item in final:
        for dependency in item.depends_on:
            reverse_final[dependency].append(item.id)
    mapping = {change.source: change.target for change in changes if change.kind == "replace"}
    direct = {mapping.get(change.source, change.source) for change in changes if change.kind != "remove"}
    impacted = {item for item in direct if item in final_map}
    pending = list(impacted)
    for old in removed:
        pending.extend(reverse_initial.get(old, ()))
    while pending:
        item = pending.pop()
        if item in final_map and item not in impacted:
            impacted.add(item)
        for dependant in reverse_final.get(item, ()):
            if dependant not in impacted:
                impacted.add(dependant)
                pending.append(dependant)
    return tuple(sorted(impacted))

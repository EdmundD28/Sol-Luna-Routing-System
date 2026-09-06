from .model import BomError

def assembly_waves(components):
    by_id = {component.id: component for component in components}
    indegree = {component.id: len(component.depends_on) for component in components}
    dependants = {component.id: [] for component in components}
    for component in components:
        for dependency in component.depends_on:
            if dependency not in by_id:
                raise BomError("MISSING_DEPENDENCY", ("final", component.id, "depends_on", component.depends_on.index(dependency)))
            dependants[dependency].append(component.id)
    remaining = set(by_id)
    waves = []
    while remaining:
        ready = tuple(sorted(item for item in remaining if indegree[item] == 0))
        if not ready:
            raise BomError("CYCLE", ("final", "depends_on"))
        waves.append(ready)
        for item in ready:
            remaining.remove(item)
            for dependant in dependants[item]:
                indegree[dependant] -= 1
    return tuple(waves)

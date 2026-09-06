from typing import Iterable

from ..errors import WorkbenchError
from .models import Job, SchedulePlan


def _err(code, path, message, details=None):
    raise WorkbenchError(code, tuple(path), message, details)


def validate_graph(raw_jobs: Iterable[Job | dict]) -> tuple[Job, ...]:
    try: items = list(raw_jobs)
    except TypeError: _err("INVALID_JOBS", ("jobs",), "jobs must be iterable")
    parsed = []
    for i, raw in enumerate(items):
        if isinstance(raw, Job):
            job = Job(raw.job_id, tuple(sorted(raw.depends_on)), tuple(sorted(raw.resources)), bool(raw.disabled))
        else:
            if not isinstance(raw, dict): _err("INVALID_JOB", ("jobs", i), "job must be an object")
            for key in raw:
                if key not in ("id", "depends_on", "resources", "disabled"):
                    _err("UNKNOWN_FIELD", ("jobs", i, key), "unknown field")
            if "id" not in raw: _err("MISSING_FIELD", ("jobs", i, "id"), "missing field")
            ident = raw["id"]
            if not isinstance(ident, str) or not ident: _err("INVALID_ID", ("jobs", i, "id"), "invalid id")
            deps = raw.get("depends_on", [])
            resources = raw.get("resources", [])
            disabled = raw.get("disabled", False)
            if not isinstance(deps, list) or any(not isinstance(x, str) or not x for x in deps): _err("INVALID_DEPENDENCIES", ("jobs", i, "depends_on"), "invalid dependencies")
            if len(set(deps)) != len(deps): _err("DUPLICATE_DEPENDENCY", ("jobs", i, "depends_on"), "duplicate dependency")
            if not isinstance(resources, list) or any(not isinstance(x, str) or not x for x in resources): _err("INVALID_RESOURCES", ("jobs", i, "resources"), "invalid resources")
            if len(set(resources)) != len(resources): _err("DUPLICATE_RESOURCE", ("jobs", i, "resources"), "duplicate resource")
            if not isinstance(disabled, bool): _err("INVALID_DISABLED", ("jobs", i, "disabled"), "disabled must be boolean")
            job = Job(ident, tuple(sorted(deps)), tuple(sorted(resources)), disabled)
        parsed.append(job)
    ids = {j.job_id for j in parsed}
    seen_ids = set()
    for index, job in enumerate(parsed):
        if job.job_id in seen_ids: _err("DUPLICATE_JOB", ("jobs", index, "id"), "duplicate job id")
        seen_ids.add(job.job_id)
        for dep in job.depends_on:
            if dep not in ids: _err("UNKNOWN_DEPENDENCY", ("jobs", job.job_id, "depends_on", dep), "unknown dependency")
            if dep == job.job_id: _err("SELF_DEPENDENCY", ("jobs", job.job_id, "depends_on", dep), "self dependency")
    # Detect cycles with deterministic member reporting.
    state, stack, cycles = {}, [], set()
    by_id = {j.job_id: j for j in parsed}
    def visit(n):
        state[n] = 1; stack.append(n)
        for dep in by_id[n].depends_on:
            if state.get(dep) == 1:
                k = stack.index(dep); cycles.update(stack[k:])
            elif not state.get(dep): visit(dep)
        stack.pop(); state[n] = 2
    for n in sorted(by_id):
        if not state.get(n): visit(n)
    if cycles: _err("DEPENDENCY_CYCLE", ("jobs",), "dependency cycle", {"members": tuple(sorted(cycles))})
    return tuple(sorted(parsed, key=lambda j: j.job_id))


def build_schedule(raw_jobs: Iterable[Job | dict], max_parallel: int = 1) -> SchedulePlan:
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or max_parallel <= 0:
        _err("INVALID_LIMIT", ("max_parallel",), "max_parallel must be positive integer")
    jobs = validate_graph(raw_jobs)
    by_id = {j.job_id: j for j in jobs}
    blocked = {j.job_id for j in jobs if j.disabled}
    changed = True
    while changed:
        changed = False
        for j in jobs:
            if j.job_id not in blocked and any(d in blocked for d in j.depends_on): blocked.add(j.job_id); changed = True
    remaining = set(by_id) - blocked
    waves = []
    while remaining:
        ready = sorted(n for n in remaining if all(d not in remaining for d in by_id[n].depends_on))
        if not ready: break
        wave, used = [], set()
        for n in ready:
            resources = set(by_id[n].resources)
            if len(wave) < max_parallel and not resources.intersection(used):
                wave.append(n); used.update(resources)
        if not wave: wave = [ready[0]]
        waves.append(tuple(wave)); remaining.difference_update(wave)
    return SchedulePlan(tuple(waves), tuple(sorted(blocked)))

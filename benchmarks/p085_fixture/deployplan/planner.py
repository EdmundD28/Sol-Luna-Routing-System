from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import hashlib
import json
from typing import Any

from .diff import diff_services
from .impact import diff_with_impact
from .overlay import apply_profile
from .graph import dependency_closure, dependency_order
from .model import Operation, Plan, ProfiledPlan, Service
from .waves import build_waves
from .normalize import parse_manifest


def _service(item: Service | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "name": item.name,
        "image": item.image,
        "depends_on": list(item.depends_on),
        "env": dict(item.env),
        "tags": list(item.tags),
        "replicas": item.replicas,
    }


def _operation(item: Operation) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "name": item.name,
        "before": _service(item.before),
        "after": _service(item.after),
    }


def _payload(services: tuple[Service, ...], operations: tuple[Operation, ...]) -> dict[str, Any]:
    return {
        "services": [_service(item) for item in services],
        "operations": [_operation(item) for item in operations],
    }


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compile_plan(
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
    *,
    roots: tuple[str, ...] | None = None,
) -> Plan:
    current_items = parse_manifest(current)
    desired_items = parse_manifest(desired)
    dependency_order(current_items)
    ordered_desired = dependency_order(desired_items)
    if roots is None:
        selected_desired = ordered_desired
        selected_current = current_items
    else:
        selected_desired = dependency_closure(desired_items, roots)
        selected_names = {item.name for item in selected_desired}
        selected_current = tuple(item for item in current_items if item.name in selected_names)
    operations = diff_services(selected_current, selected_desired)
    payload = _payload(selected_desired, operations)
    digest = "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return Plan(selected_desired, operations, digest)


def render_plan(plan: Plan) -> str:
    """Return canonical UTF-8-safe JSON with a trailing newline."""
    body = _payload(plan.services, plan.operations)
    body["digest"] = plan.digest
    return _canonical(body) + "\n"

def compile_profiled_plan(current: Mapping[str, Any], desired: Mapping[str, Any], profile: Mapping[str, Any], *, roots: tuple[str, ...] | None = None, max_parallel: int = 1) -> ProfiledPlan:
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or max_parallel <= 0:
        raise __import__("benchmarks.p085_fixture.deployplan.errors", fromlist=["ManifestError"]).ManifestError("BAD_PARALLELISM", "max_parallel", "max_parallel must be a positive integer")
    current_items=parse_manifest(current); profiled=apply_profile(desired, profile)
    if roots is None: selected=profiled; selected_current=current_items
    else:
        selected=dependency_closure(profiled, roots); names={s.name for s in selected}; selected_current=tuple(s for s in current_items if s.name in names)
    operations=diff_with_impact(selected_current, selected); waves=build_waves(operations, selected_current, selected, max_parallel)
    payload={"services":[_service(s) for s in selected],"operations":[_operation(o) for o in operations],"waves":[[_operation(o) for o in w] for w in waves]}
    digest="sha256:"+hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return ProfiledPlan(selected, operations, waves, digest)

def render_profiled_plan(plan: ProfiledPlan) -> str:
    body={"services":[_service(s) for s in plan.services],"operations":[_operation(o) for o in plan.operations],"waves":[[_operation(o) for o in w] for w in plan.waves]}; body["digest"]="sha256:"+hashlib.sha256(_canonical({k:v for k,v in body.items() if k!="digest"}).encode("utf-8")).hexdigest()
    return _canonical(body)+"\n"

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from .diff import _diff_ordered
from .graph import dependency_closure, dependency_order
from .model import Plan, ProfiledPlan
from .normalize import parse_manifest
from .overlay import apply_profile
from .diff import diff_services
from .impact import with_restarts
from .waves import make_waves


def compile_plan(
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
    *,
    roots: tuple[str, ...] | None = None,
) -> Plan:
    current_items = parse_manifest(current)
    desired_items = parse_manifest(desired)
    # Validate both complete graphs before any root-based selection.
    current_order = dependency_order(current_items)
    desired_order = dependency_order(desired_items)
    if roots is None:
        selected = desired_order
        operations = _diff_ordered(current_order, desired_order)
    else:
        selected = dependency_closure(desired_order, roots)
        selected_names = {service.name for service in selected}
        operations = _diff_ordered(current_order, selected, scope=selected_names)
    return Plan(tuple(selected), tuple(operations), _digest_for(tuple(selected), tuple(operations)))


def render_plan(plan: Plan) -> str:
    """Return canonical UTF-8-safe JSON with a trailing newline."""
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    body = _plan_body(plan.services, plan.operations)
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    rendered = {"digest": digest, "operations": body["operations"], "services": body["services"]}
    return json.dumps(rendered, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _service_body(service: Any) -> dict[str, Any]:
    return {
        "name": service.name,
        "image": service.image,
        "depends_on": list(service.depends_on),
        "env": {key: value for key, value in service.env},
        "tags": list(service.tags),
        "replicas": service.replicas,
    }


def _operation_body(operation: Any) -> dict[str, Any]:
    return {
        "kind": operation.kind,
        "name": operation.name,
        "before": None if operation.before is None else _service_body(operation.before),
        "after": None if operation.after is None else _service_body(operation.after),
    }


def _plan_body(services: tuple[Any, ...], operations: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "operations": [_operation_body(operation) for operation in operations],
        "services": [_service_body(service) for service in services],
    }


def _digest_for(services: tuple[Any, ...], operations: tuple[Any, ...]) -> str:
    payload = json.dumps(_plan_body(services, operations), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compile_profiled_plan(
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    roots: tuple[str, ...] | None = None,
    max_parallel: int = 1,
) -> ProfiledPlan:
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or max_parallel <= 0:
        from .errors import ManifestError
        raise ManifestError("BAD_PARALLELISM", "max_parallel", "max_parallel must be a positive integer")
    current_items = parse_manifest(current)
    current_order = dependency_order(current_items)
    final_desired = apply_profile(desired, profile)
    if roots is None:
        selected = final_desired
        ordinary = diff_services(current_order, final_desired)
    else:
        selected = dependency_closure(final_desired, roots)
        selected_names = {service.name for service in selected}
        ordinary = tuple(operation for operation in diff_services(current_order, final_desired) if operation.name in selected_names)
    operations = with_restarts(current_order, selected, ordinary)
    waves = make_waves(operations, current_order, selected, max_parallel)
    return ProfiledPlan(tuple(selected), tuple(operations), waves, _profiled_digest(tuple(selected), tuple(operations), waves))


def _profiled_body(services: tuple[Any, ...], operations: tuple[Any, ...], waves: tuple[tuple[Any, ...], ...]) -> dict[str, Any]:
    return {"operations": [_operation_body(operation) for operation in operations], "services": [_service_body(service) for service in services], "waves": [[_operation_body(operation) for operation in wave] for wave in waves]}


def _profiled_digest(services: tuple[Any, ...], operations: tuple[Any, ...], waves: tuple[tuple[Any, ...], ...]) -> str:
    payload = json.dumps(_profiled_body(services, operations, waves), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def render_profiled_plan(plan: ProfiledPlan) -> str:
    if not isinstance(plan, ProfiledPlan):
        raise TypeError("plan must be a ProfiledPlan")
    body = _profiled_body(plan.services, plan.operations, plan.waves)
    digest = "sha256:" + hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    rendered = {"digest": digest, "operations": body["operations"], "services": body["services"], "waves": body["waves"]}
    return json.dumps(rendered, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"

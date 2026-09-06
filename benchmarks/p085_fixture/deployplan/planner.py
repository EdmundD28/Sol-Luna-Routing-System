from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from .diff import _diff_ordered
from .graph import dependency_closure, dependency_order
from .model import Plan
from .normalize import parse_manifest


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

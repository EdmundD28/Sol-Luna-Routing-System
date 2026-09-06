from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ManifestError
from .graph import dependency_order
from .model import Service
from .normalize import normalize_name, parse_manifest

_FIELDS = {"name", "image", "depends_on", "env", "tags", "replicas", "remove"}

def _raw(service: Service) -> dict[str, Any]:
    return {"name": service.name, "image": service.image, "depends_on": list(service.depends_on), "env": {key: value for key, value in service.env}, "tags": list(service.tags), "replicas": service.replicas}

def _validate_field(name: str, value: Any, index: int, current: dict[str, Any]) -> Any:
    candidate = copy.deepcopy(current)
    candidate[name] = copy.deepcopy(value)
    try:
        parsed = parse_manifest({"services": [candidate]})
    except ManifestError as error:
        raise ManifestError(error.code, f"services[{index}].{name}", error.message) from error
    service = parsed[0]
    return {"image": service.image, "depends_on": list(service.depends_on), "env": {key: value for key, value in service.env}, "tags": list(service.tags), "replicas": service.replicas}[name]

def apply_profile(base: Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[Service, ...]:
    base_services = parse_manifest(base)
    base_order = dependency_order(base_services)
    by_name = {service.name: service for service in base_order}
    if not isinstance(profile, Mapping):
        raise ManifestError("BAD_PROFILE", "$", "profile must be a mapping")
    unknown = sorted(set(profile) - {"services"})
    if unknown:
        raise ManifestError("UNKNOWN_FIELD", str(unknown[0]), "unknown profile field")
    if not isinstance(profile.get("services"), list):
        raise ManifestError("BAD_PROFILE", "services", "profile services must be a list")
    seen: set[str] = set()
    for index, override in enumerate(profile["services"]):
        path = f"services[{index}]"
        if not isinstance(override, Mapping):
            raise ManifestError("BAD_OVERRIDE", path, "override must be a mapping")
        unknown_fields = sorted(set(override) - _FIELDS)
        if unknown_fields:
            raise ManifestError("UNKNOWN_FIELD", f"{path}.{unknown_fields[0]}", "unknown override field")
        if "name" not in override:
            raise ManifestError("BAD_NAME", f"{path}.name", "name is required")
        name = normalize_name(override["name"], path=f"{path}.name")
        if name in seen:
            raise ManifestError("DUPLICATE_OVERRIDE", f"{path}.name", f"duplicate override {name}")
        seen.add(name)
        remove = override.get("remove", False)
        if not isinstance(remove, bool):
            raise ManifestError("BAD_REMOVE", f"{path}.remove", "remove must be boolean")
        if remove:
            if set(override) - {"name", "remove"}:
                raise ManifestError("BAD_REMOVE", f"{path}.remove", "remove cannot include service fields")
            if name not in by_name:
                raise ManifestError("UNKNOWN_OVERRIDE", f"{path}.name", f"unknown service {name}")
            del by_name[name]
            continue
        existing = by_name.get(name)
        current = _raw(existing) if existing is not None else {"name": name, "image": None, "depends_on": [], "env": {}, "tags": [], "replicas": 1}
        current["name"] = name
        if existing is None and "image" not in override:
            raise ManifestError("BAD_IMAGE", f"{path}.image", "image is required for new service")
        for field in ("image", "depends_on", "env", "tags", "replicas"):
            if field in override:
                current[field] = _validate_field(field, override[field], index, current)
        if existing is None:
            # Image was checked above; parse also supplies the canonical model.
            pass
        by_name[name] = parse_manifest({"services": [current]})[0]
    result = dependency_order(tuple(by_name.values()))
    return tuple(copy.deepcopy(result))


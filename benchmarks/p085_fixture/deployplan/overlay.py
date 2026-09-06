from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from .errors import ManifestError
from .graph import dependency_order
from .model import Service
from .normalize import parse_manifest, normalize_name, _dependencies, _environment, _tags

_FIELDS = {"name", "image", "depends_on", "env", "tags", "replicas", "remove"}

def apply_profile(base: Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[Service, ...]:
    base_items = parse_manifest(base)
    dependency_order(base_items)
    if not isinstance(profile, Mapping):
        raise ManifestError("BAD_PROFILE", "$", "profile must be a mapping")
    unknown = sorted(set(profile) - {"services"}, key=str)
    if unknown:
        raise ManifestError("UNKNOWN_FIELD", str(unknown[0]), "unknown profile field")
    if "services" not in profile or not isinstance(profile["services"], list):
        raise ManifestError("BAD_PROFILE", "services", "services must be a list")
    items = {s.name: s for s in base_items}; seen: set[str] = set()
    for i, raw in enumerate(profile["services"]):
        path = f"services[{i}]"
        if not isinstance(raw, Mapping): raise ManifestError("BAD_OVERRIDE", path, "override must be a mapping")
        extra = sorted(set(raw) - _FIELDS, key=str)
        if extra: raise ManifestError("UNKNOWN_FIELD", f"{path}.{extra[0]}", "unknown override field")
        name = normalize_name(raw.get("name"), path=f"{path}.name")
        if name in seen: raise ManifestError("DUPLICATE_OVERRIDE", f"{path}.name", name)
        seen.add(name); remove = raw.get("remove", False)
        if not isinstance(remove, bool): raise ManifestError("BAD_REMOVE", f"{path}.remove", "remove must be boolean")
        if remove:
            if set(raw) - {"name", "remove"}: raise ManifestError("BAD_REMOVE", f"{path}.remove", "remove overrides cannot include service fields")
            if name not in items: raise ManifestError("UNKNOWN_OVERRIDE", f"{path}.name", name)
            del items[name]; continue
        old = items.get(name); vals: dict[str, Any] = {"name": name}
        if old is not None: vals.update(image=old.image, depends_on=list(old.depends_on), env=dict(old.env), tags=list(old.tags), replicas=old.replicas)
        for field in ("image", "depends_on", "env", "tags", "replicas"):
            if field not in raw:
                if old is None and field == "image": raise ManifestError("BAD_IMAGE", f"{path}.image", "image must be a non-empty string")
                continue
            fp = f"{path}.{field}"; value = raw[field]
            if field == "image":
                if not isinstance(value, str) or not value.strip(): raise ManifestError("BAD_IMAGE", fp, "image must be a non-empty string")
                vals[field] = value.strip()
            elif field == "depends_on": vals[field] = list(_dependencies(value, path=fp))
            elif field == "env": vals[field] = dict(_environment(value, path=fp))
            elif field == "tags": vals[field] = list(_tags(value, path=fp))
            else:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise ManifestError("BAD_REPLICAS", fp, "replicas must be a non-negative integer")
                vals[field] = value
        items[name] = parse_manifest({"services": [vals]})[0]
    return dependency_order(tuple(items.values()))

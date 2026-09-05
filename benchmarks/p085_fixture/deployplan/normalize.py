from __future__ import annotations

from collections.abc import Mapping
import json
import math
import re
from typing import Any

from .errors import ManifestError
from .model import Service


_NAME = re.compile(r"[a-z][a-z0-9-]*")
_SERVICE_FIELDS = {"name", "image", "depends_on", "env", "tags", "replicas"}


def normalize_name(value: object, *, path: str = "name") -> str:
    if not isinstance(value, str):
        raise ManifestError("BAD_NAME", path, "expected a string name")
    normalized = value.strip().lower()
    if not _NAME.fullmatch(normalized):
        raise ManifestError("BAD_NAME", path, "name must match [a-z][a-z0-9-]*")
    return normalized


def _sequence(value: object, *, code: str, path: str) -> list[object] | tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ManifestError(code, path, "expected a list or tuple")
    return value


def _environment(value: object, *, path: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ManifestError("BAD_ENV", path, "expected a mapping")
    pairs: list[tuple[str, str]] = []
    for key, raw in value.items():
        item_path = f"{path}.{key}"
        if not isinstance(key, str) or not key:
            raise ManifestError("BAD_ENV", path, "environment keys must be non-empty strings")
        if isinstance(raw, str):
            rendered = raw
        elif raw is None or isinstance(raw, bool):
            rendered = json.dumps(raw, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ManifestError("BAD_ENV", item_path, "environment number must be finite")
            rendered = json.dumps(raw, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        else:
            raise ManifestError("BAD_ENV", item_path, "environment value must be scalar")
        pairs.append((key, rendered))
    return tuple(sorted(pairs))


def _tags(value: object, *, path: str) -> tuple[str, ...]:
    items = _sequence(value, code="BAD_TAGS", path=path)
    normalized: set[str] = set()
    for index, item in enumerate(items):
        try:
            normalized.add(normalize_name(item, path=f"{path}[{index}]"))
        except ManifestError as error:
            raise ManifestError("BAD_TAGS", error.path, error.message) from error
    return tuple(sorted(normalized))


def _dependencies(value: object, *, path: str) -> tuple[str, ...]:
    items = _sequence(value, code="BAD_DEPENDENCIES", path=path)
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        try:
            name = normalize_name(item, path=f"{path}[{index}]")
        except ManifestError as error:
            raise ManifestError("BAD_DEPENDENCIES", error.path, error.message) from error
        if name not in seen:
            seen.add(name)
            result.append(name)
    return tuple(result)


def parse_manifest(raw: Mapping[str, Any]) -> tuple[Service, ...]:
    if not isinstance(raw, Mapping):
        raise ManifestError("BAD_MANIFEST", "$", "manifest must be a mapping")
    extra = sorted(set(raw) - {"services"}, key=str)
    if extra:
        raise ManifestError("UNKNOWN_FIELD", str(extra[0]), "unknown manifest field")
    if "services" not in raw or not isinstance(raw["services"], list):
        raise ManifestError("BAD_MANIFEST", "services", "services must be a list")

    result: list[Service] = []
    seen: set[str] = set()
    for index, value in enumerate(raw["services"]):
        base = f"services[{index}]"
        if not isinstance(value, Mapping):
            raise ManifestError("BAD_SERVICE", base, "service must be a mapping")
        unknown = sorted(set(value) - _SERVICE_FIELDS, key=str)
        if unknown:
            raise ManifestError("UNKNOWN_FIELD", f"{base}.{unknown[0]}", "unknown service field")
        name = normalize_name(value.get("name"), path=f"{base}.name")
        if name in seen:
            raise ManifestError("DUPLICATE_SERVICE", f"{base}.name", name)
        seen.add(name)
        image = value.get("image")
        if not isinstance(image, str) or not image.strip():
            raise ManifestError("BAD_IMAGE", f"{base}.image", "image must be a non-empty string")
        replicas = value.get("replicas", 1)
        if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 0:
            raise ManifestError("BAD_REPLICAS", f"{base}.replicas", "replicas must be a non-negative integer")
        result.append(
            Service(
                name=name,
                image=image.strip(),
                depends_on=_dependencies(value.get("depends_on", []), path=f"{base}.depends_on"),
                env=_environment(value.get("env", {}), path=f"{base}.env"),
                tags=_tags(value.get("tags", []), path=f"{base}.tags"),
                replicas=replicas,
            )
        )
    return tuple(result)

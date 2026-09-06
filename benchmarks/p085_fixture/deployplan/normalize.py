from __future__ import annotations

from collections.abc import Mapping
import json
import math
import re
from typing import Any

from .errors import ManifestError
from .model import Service


def normalize_name(value: object, *, path: str = "name") -> str:
    if not isinstance(value, str):
        raise ManifestError("BAD_NAME", path, "name must be a string")
    normalized = value.strip().lower()
    if re.fullmatch(r"[a-z][a-z0-9-]*", normalized) is None:
        raise ManifestError("BAD_NAME", path, "invalid name")
    return normalized


def parse_manifest(raw: Mapping[str, Any]) -> tuple[Service, ...]:
    if not isinstance(raw, Mapping):
        raise ManifestError("BAD_MANIFEST", "<root>", "manifest must be a mapping")
    # Validate top-level shape before inspecting any service fields.
    for key in raw:
        if key != "services":
            raise ManifestError("UNKNOWN_FIELD", str(key), "unknown manifest field")
    if "services" not in raw:
        raise ManifestError("BAD_MANIFEST", "services", "services is required")
    raw_services = raw["services"]
    if not isinstance(raw_services, list):
        raise ManifestError("BAD_MANIFEST", "services", "services must be a list")

    allowed = {"name", "image", "depends_on", "env", "tags", "replicas"}
    parsed: list[Service] = []
    seen: dict[str, int] = {}
    for index, item in enumerate(raw_services):
        base = f"services[{index}]"
        if not isinstance(item, Mapping):
            raise ManifestError("BAD_SERVICE", base, "service must be a mapping")
        for key in item:
            if key not in allowed:
                raise ManifestError("UNKNOWN_FIELD", f"{base}.{key}", "unknown service field")
        if "name" not in item:
            raise ManifestError("BAD_NAME", f"{base}.name", "name is required")
        name = normalize_name(item["name"], path=f"{base}.name")
        if name in seen:
            raise ManifestError("DUPLICATE_SERVICE", f"{base}.name", "duplicate service name")
        seen[name] = index
        if "image" not in item:
            raise ManifestError("BAD_IMAGE", f"{base}.image", "image is required")
        image = item["image"]
        if not isinstance(image, str) or not image.strip():
            raise ManifestError("BAD_IMAGE", f"{base}.image", "image must be a non-empty string")
        image = image.strip()

        depends_on: list[str] = []
        if "depends_on" in item:
            value = item["depends_on"]
            if not isinstance(value, (list, tuple)):
                raise ManifestError("BAD_DEPENDENCIES", f"{base}.depends_on", "depends_on must be a list or tuple")
            for dependency in value:
                try:
                    normalized = normalize_name(dependency, path=f"{base}.depends_on")
                except ManifestError as error:
                    raise ManifestError("BAD_DEPENDENCIES", f"{base}.depends_on", error.message) from error
                if normalized not in depends_on:
                    depends_on.append(normalized)

        env_items: list[tuple[str, str]] = []
        if "env" in item:
            value = item["env"]
            if not isinstance(value, Mapping):
                raise ManifestError("BAD_ENV", f"{base}.env", "env must be a mapping")
            for key, env_value in value.items():
                if not isinstance(key, str) or not key:
                    raise ManifestError("BAD_ENV", f"{base}.env", "environment keys must be non-empty strings")
                if isinstance(env_value, str):
                    canonical = env_value
                elif env_value is None:
                    canonical = "null"
                elif isinstance(env_value, bool):
                    canonical = "true" if env_value else "false"
                elif isinstance(env_value, (int, float)):
                    if isinstance(env_value, float) and not math.isfinite(env_value):
                        raise ManifestError("BAD_ENV", f"{base}.env.{key}", "environment number must be finite")
                    try:
                        canonical = json.dumps(
                            env_value,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        )
                    except (TypeError, ValueError) as error:
                        raise ManifestError("BAD_ENV", f"{base}.env.{key}", "invalid environment value") from error
                else:
                    raise ManifestError("BAD_ENV", f"{base}.env.{key}", "unsupported environment value")
                env_items.append((key, canonical))
            env_items.sort(key=lambda pair: pair[0])

        tags: list[str] = []
        if "tags" in item:
            value = item["tags"]
            if not isinstance(value, (list, tuple)):
                raise ManifestError("BAD_TAGS", f"{base}.tags", "tags must be a list or tuple")
            for tag in value:
                try:
                    normalized = normalize_name(tag, path=f"{base}.tags")
                except ManifestError as error:
                    raise ManifestError("BAD_TAGS", f"{base}.tags", error.message) from error
                if normalized not in tags:
                    tags.append(normalized)
            tags.sort()

        replicas = item.get("replicas", 1)
        if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 0:
            raise ManifestError("BAD_REPLICAS", f"{base}.replicas", "replicas must be a non-negative integer")
        parsed.append(Service(name, image, tuple(depends_on), tuple(env_items), tuple(tags), replicas))
    return tuple(parsed)

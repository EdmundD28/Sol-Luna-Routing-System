from dataclasses import dataclass
from typing import Any
from types import MappingProxyType


def freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: freeze_json(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze_json(v) for v in value)
    if isinstance(value, tuple):
        return tuple(freeze_json(v) for v in value)
    return value


@dataclass(frozen=True)
class SourceRef:
    layer_id: str
    path: tuple[str | int, ...]


@dataclass(frozen=True)
class JsonDocument:
    value: Any

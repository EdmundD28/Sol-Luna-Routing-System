from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceRef:
    layer_id: str
    path: tuple[str | int, ...]


@dataclass(frozen=True)
class JsonDocument:
    value: Any

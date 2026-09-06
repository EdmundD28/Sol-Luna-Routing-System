from dataclasses import dataclass
from typing import Any

from ..frozen import SourceRef


@dataclass(frozen=True)
class ConfigLayer:
    layer_id: str
    data: dict[str, Any]


@dataclass(frozen=True)
class MergedConfig:
    data: dict[str, Any]
    sources: tuple[SourceRef, ...]

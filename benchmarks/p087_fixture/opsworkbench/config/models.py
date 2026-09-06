from dataclasses import dataclass
from typing import Any

from ..frozen import SourceRef, freeze_json


@dataclass(frozen=True)
class ConfigLayer:
    layer_id: str
    data: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", freeze_json(self.data))


@dataclass(frozen=True)
class MergedConfig:
    data: dict[str, Any]
    sources: tuple[SourceRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", freeze_json(self.data))
        object.__setattr__(self, "sources", tuple(self.sources))

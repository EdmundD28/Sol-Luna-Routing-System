from dataclasses import dataclass
from typing import Any
from types import MappingProxyType


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class WorkbenchError(Exception):
    code: str
    path: tuple[str | int, ...]
    message: str
    details: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", tuple(self.path))
        object.__setattr__(self, "details", _freeze(self.details))
        Exception.__init__(self, self.message)

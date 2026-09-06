from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkbenchError(Exception):
    code: str
    path: tuple[str | int, ...]
    message: str
    details: Any = None

    def __post_init__(self) -> None:
        raise NotImplementedError

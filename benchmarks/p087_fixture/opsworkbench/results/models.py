from dataclasses import dataclass
from typing import Any
from types import MappingProxyType


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    attempt: int
    status: str
    duration_ms: int | float
    finished_at: str


@dataclass(frozen=True)
class ResultSnapshot:
    cases: tuple[CaseResult, ...]
    counts: dict[str, int]
    total_duration_ms: int | float

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))


@dataclass(frozen=True)
class Regression:
    case_id: str
    before_status: str | None
    after_status: str
    delta_duration_ms: int | float

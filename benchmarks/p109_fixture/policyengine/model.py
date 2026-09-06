"""Frozen public records for the P109 fixture."""
from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class PolicyError(Exception):
    code: str
    path: Tuple[object, ...]

    def __str__(self) -> str:
        return f"{self.code} at {self.path!r}"


@dataclass(frozen=True)
class Decision:
    effect: str
    winner: Optional[str]
    matched: Tuple[Any, ...]
    decisive: Tuple[Any, ...]
    reason: str


@dataclass(frozen=True)
class NormalizedRule:
    id: str
    effect: str
    priority: int
    subject: Any
    resource: Any
    actions: Tuple[Any, ...]
    when: Any


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

@dataclass(frozen=True)
class Selector:
    ids: Tuple[str, ...]; roles: Tuple[str, ...]; groups: Tuple[str, ...]

@dataclass(frozen=True)
class ResourceSelector:
    ids: Tuple[str, ...]; kinds: Tuple[str, ...]; tags: Tuple[Tuple[str, Tuple[Any, ...]], ...]

@dataclass(frozen=True)
class RequestSubject:
    id: str; roles: Tuple[str, ...]; groups: Tuple[str, ...]; attrs: Any

@dataclass(frozen=True)
class RequestResource:
    id: str; kind: str; tags: Any; attrs: Any

@dataclass(frozen=True)
class Request:
    subject: RequestSubject; resource: RequestResource; action: str; context: Any

@dataclass(frozen=True)
class Condition:
    kind: str; data: Any

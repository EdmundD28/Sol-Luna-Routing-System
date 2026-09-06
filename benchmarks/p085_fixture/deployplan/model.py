from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Service:
    name: str
    image: str
    depends_on: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    tags: tuple[str, ...] = ()
    replicas: int = 1


@dataclass(frozen=True, slots=True)
class Operation:
    kind: str
    name: str
    before: Service | None
    after: Service | None


@dataclass(frozen=True, slots=True)
class Plan:
    services: tuple[Service, ...]
    operations: tuple[Operation, ...]
    digest: str

@dataclass(frozen=True, slots=True)
class ProfiledPlan:
    services: tuple[Service, ...]
    operations: tuple[Operation, ...]
    waves: tuple[tuple[Operation, ...], ...]
    digest: str

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RolloutTarget:
    target_id: str
    region: str
    ring: int
    eligible: bool = True
    enabled: bool = True
    anti_affinity: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class RolloutRequest:
    rings: tuple[int, ...]
    max_per_wave: int
    regional_quota: Mapping[str, int]
    allow_spillover: bool = True


@dataclass(frozen=True)
class RolloutWave:
    ring: int
    index: int
    target_ids: tuple[str, ...]


@dataclass(frozen=True)
class BlockedTarget:
    target_id: str
    reason: str


@dataclass(frozen=True)
class RolloutPlan:
    waves: tuple[RolloutWave, ...]
    blocked: tuple[BlockedTarget, ...]

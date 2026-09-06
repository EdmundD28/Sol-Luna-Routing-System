from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    channel: str
    created_at: int
    tags: tuple[str, ...] = ()
    healthy: bool = True
    size_bytes: int = 0


@dataclass(frozen=True)
class LegalHold:
    snapshot_id: str
    reason: str


@dataclass(frozen=True)
class RetentionPolicy:
    keep_last: int
    max_age: int | None
    protected_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetentionDecision:
    snapshot_id: str
    action: str
    reason: str


@dataclass(frozen=True)
class RetentionPlan:
    decisions: tuple[RetentionDecision, ...]

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CacheEntry:
    key: str
    value: Any
    created_at: int
    expires_at: int | None
    size_bytes: int
    dependencies: tuple[str, ...] = ()
    last_access: int = 0
    pinned: bool = False


@dataclass(frozen=True)
class CacheRequest:
    key: str
    now: int
    allow_prefix: bool = True


@dataclass(frozen=True)
class CacheHit:
    entry: CacheEntry
    match: str


@dataclass(frozen=True)
class EvictionPlan:
    delete_keys: tuple[str, ...]
    retained_keys: tuple[str, ...]
    bytes_freed: int

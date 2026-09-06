from collections.abc import Mapping, Sequence

from .models import CacheEntry, CacheHit, CacheRequest, EvictionPlan


def validate_cache_entry(raw: Mapping, path: tuple = ("cache",)) -> CacheEntry:
    raise NotImplementedError


def validate_cache_request(raw: Mapping, path: tuple = ("request",)) -> CacheRequest:
    raise NotImplementedError


def resolve_cache(entries: Sequence, request: Mapping | CacheRequest) -> CacheHit | None:
    raise NotImplementedError


def plan_eviction(entries: Sequence, byte_budget: int, now: int) -> EvictionPlan:
    raise NotImplementedError

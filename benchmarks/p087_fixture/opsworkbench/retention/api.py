from collections.abc import Mapping, Sequence

from .models import LegalHold, RetentionPlan, RetentionPolicy, Snapshot


def validate_snapshot(raw: Mapping, path: tuple = ("retention", "snapshots")) -> Snapshot:
    raise NotImplementedError


def validate_legal_hold(raw: Mapping, path: tuple = ("retention", "holds")) -> LegalHold:
    raise NotImplementedError


def validate_retention_policy(raw: Mapping, path: tuple = ("retention", "policy")) -> RetentionPolicy:
    raise NotImplementedError


def apply_retention(snapshots: Sequence, holds: Sequence, policy: Mapping | RetentionPolicy, now: int) -> RetentionPlan:
    raise NotImplementedError

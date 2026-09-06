from collections.abc import Mapping, Sequence

from .models import RolloutPlan, RolloutRequest, RolloutTarget


def validate_target(raw: Mapping, path: tuple = ("rollout", "targets")) -> RolloutTarget:
    raise NotImplementedError


def validate_rollout_request(raw: Mapping, path: tuple = ("rollout", "request")) -> RolloutRequest:
    raise NotImplementedError


def assign_rollout(targets: Sequence, request: Mapping | RolloutRequest) -> RolloutPlan:
    raise NotImplementedError

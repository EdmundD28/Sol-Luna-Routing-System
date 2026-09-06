from collections.abc import Mapping, Sequence

from .models import PatchGraph, PatchPlan, PatchRecord


def validate_patch(raw: Mapping, path: tuple = ("patches",)) -> PatchRecord:
    raise NotImplementedError


def build_patch_graph(patches: Sequence) -> PatchGraph:
    raise NotImplementedError


def plan_patch_waves(patches: Sequence) -> PatchPlan:
    raise NotImplementedError

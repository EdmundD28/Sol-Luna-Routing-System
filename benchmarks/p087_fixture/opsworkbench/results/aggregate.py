from typing import Iterable

from .models import CaseResult, Regression, ResultSnapshot


def normalize_result(raw: CaseResult | dict, index: int = 0) -> CaseResult:
    raise NotImplementedError


def aggregate_results(raw_results: Iterable[CaseResult | dict]) -> ResultSnapshot:
    raise NotImplementedError


def compare_snapshots(before: ResultSnapshot, after: ResultSnapshot) -> tuple[Regression, ...]:
    raise NotImplementedError

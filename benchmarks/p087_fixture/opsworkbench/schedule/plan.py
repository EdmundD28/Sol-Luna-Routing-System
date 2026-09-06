from typing import Iterable

from .models import Job, SchedulePlan


def validate_graph(raw_jobs: Iterable[Job | dict]) -> tuple[Job, ...]:
    raise NotImplementedError


def build_schedule(raw_jobs: Iterable[Job | dict], max_parallel: int = 1) -> SchedulePlan:
    raise NotImplementedError

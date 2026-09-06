from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    job_id: str
    depends_on: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    disabled: bool = False


@dataclass(frozen=True)
class SchedulePlan:
    waves: tuple[tuple[str, ...], ...]
    blocked: tuple[str, ...]

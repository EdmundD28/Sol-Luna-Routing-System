from dataclasses import dataclass


@dataclass(frozen=True)
class PatchRecord:
    patch_id: str
    file: str
    start: int
    end: int
    replacement: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatchGraph:
    nodes: tuple[PatchRecord, ...]
    dependencies: tuple[tuple[str, str], ...]
    conflicts: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PatchPlan:
    waves: tuple[tuple[str, ...], ...]

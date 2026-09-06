from dataclasses import dataclass

class BomError(Exception):
    def __init__(self, code, path):
        self.code, self.path = code, path
        super().__init__(code, path)

@dataclass(frozen=True)
class Component:
    id: str
    version: int
    quantity: int
    depends_on: tuple[str, ...]
    excludes: tuple[str, ...]

@dataclass(frozen=True)
class NormalizedChange:
    kind: str
    source: str
    target: str | None = None
    value: int | None = None

@dataclass(frozen=True)
class BomResult:
    components: tuple[Component, ...]
    changes: tuple[NormalizedChange, ...]
    impacted: tuple[str, ...]
    removed: tuple[str, ...]
    waves: tuple[tuple[str, ...], ...]

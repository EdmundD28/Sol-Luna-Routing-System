from dataclasses import dataclass

class VaultError(Exception):
    def __init__(self, code, path):
        self.code, self.path = code, path
        super().__init__(code, path)

@dataclass(frozen=True)
class PlanEntry:
    source: str
    target: str
    original_sha256: str
    rewritten_text: str
    rewritten_sha256: str

@dataclass(frozen=True)
class Plan:
    schema_version: int
    entries: tuple[PlanEntry, ...]

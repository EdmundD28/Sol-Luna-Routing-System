from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    version: str
    platform: str
    architecture: str
    features: tuple[str, ...] = ()
    checksum: str | None = None
    size_bytes: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRequest:
    artifact_id: str
    platform: str
    architecture: str
    features: tuple[str, ...] = ()
    allow_prerelease: bool = False


@dataclass(frozen=True)
class ArtifactInventory:
    records: tuple[ArtifactRecord, ...]
    by_platform: Mapping[str, tuple[str, ...]]

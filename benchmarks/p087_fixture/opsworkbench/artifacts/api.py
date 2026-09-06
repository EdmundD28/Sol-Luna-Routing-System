from collections.abc import Mapping, Sequence

from .models import ArtifactInventory, ArtifactRecord, ArtifactRequest


def validate_artifact(raw: Mapping, path: tuple = ("artifacts",)) -> ArtifactRecord:
    raise NotImplementedError


def validate_artifact_request(raw: Mapping, path: tuple = ("request",)) -> ArtifactRequest:
    raise NotImplementedError


def select_artifact(records: Sequence, request: Mapping | ArtifactRequest) -> ArtifactRecord:
    raise NotImplementedError


def build_inventory(records: Sequence) -> ArtifactInventory:
    raise NotImplementedError

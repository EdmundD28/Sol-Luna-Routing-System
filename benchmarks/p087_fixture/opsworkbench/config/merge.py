from typing import Any, Iterable

from .models import ConfigLayer, MergedConfig


def validate_layer(raw: ConfigLayer | dict[str, Any], index: int = 0) -> ConfigLayer:
    raise NotImplementedError


def merge_layers(raw_layers: Iterable[ConfigLayer | dict[str, Any]]) -> MergedConfig:
    raise NotImplementedError

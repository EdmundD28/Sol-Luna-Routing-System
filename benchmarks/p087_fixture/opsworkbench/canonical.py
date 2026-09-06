from typing import Any
import json
import math
from copy import deepcopy
from collections.abc import Mapping

from .errors import WorkbenchError


def _normal(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WorkbenchError("INVALID_JSON", (), "non-finite number")
        return 0.0 if value == 0 else value
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise WorkbenchError("INVALID_JSON", (), "object keys must be strings")
        return {k: _normal(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(v) for v in value]
    raise WorkbenchError("INVALID_JSON", (), "unsupported JSON value")


def canonical_json(value: Any) -> str:
    try:
        normalized = _normal(value)
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except WorkbenchError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WorkbenchError("INVALID_JSON", (), str(exc)) from exc


def clone_json(value: Any) -> Any:
    try:
        return deepcopy(_normal(value))
    except WorkbenchError:
        raise
    except Exception as exc:
        raise WorkbenchError("INVALID_JSON", (), str(exc)) from exc

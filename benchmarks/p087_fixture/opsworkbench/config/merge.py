from typing import Any, Iterable
from collections.abc import Mapping

from ..canonical import clone_json
from ..errors import WorkbenchError
from ..frozen import SourceRef
from .models import ConfigLayer, MergedConfig


def _err(code, path, message, details=None):
    raise WorkbenchError(code, tuple(path), message, details)


def _check_data(value, path):
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                _err("INVALID_KEY", path, "keys must be strings")
            if key.startswith("$"):
                if key == "$delete" and isinstance(value, dict) and len(value) == 1 and child is True:
                    continue
                _err("RESERVED_KEY", path + (key,), "reserved key")
            _check_data(child, path + (key,))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _check_data(child, path + (i,))


def _is_delete(value):
    return isinstance(value, Mapping) and set(value) == {"$delete"} and value["$delete"] is True


def validate_layer(raw: ConfigLayer | dict[str, Any], index: int = 0) -> ConfigLayer:
    base = ("layers", index)
    if isinstance(raw, ConfigLayer):
        return ConfigLayer(raw.layer_id, clone_json(raw.data))
    if not isinstance(raw, dict):
        _err("INVALID_LAYER", base, "layer must be an object")
    for key in raw:
        if key not in ("id", "data"):
            _err("UNKNOWN_FIELD", base + (key,), "unknown field")
    for key in ("id", "data"):
        if key not in raw:
            _err("MISSING_FIELD", base + (key,), "missing field")
    if not isinstance(raw["id"], str) or not raw["id"]:
        _err("INVALID_ID", base + ("id",), "id must be a non-empty string")
    if not isinstance(raw["data"], dict):
        _err("INVALID_DATA", base + ("data",), "data must be an object")
    _check_data(raw["data"], base + ("data",))
    # Lookalike deletion objects are invalid values, even when nested.
    def reject_lookalike(v, p):
        if isinstance(v, Mapping):
            if "$delete" in v and not _is_delete(v):
                _err("INVALID_DELETE", p, "invalid deletion sentinel")
            for k, x in v.items(): reject_lookalike(x, p + (k,))
        elif isinstance(v, list):
            for i, x in enumerate(v): reject_lookalike(x, p + (i,))
    reject_lookalike(raw["data"], base + ("data",))
    return ConfigLayer(raw["id"], clone_json(raw["data"]))


def merge_layers(raw_layers: Iterable[ConfigLayer | dict[str, Any]]) -> MergedConfig:
    try:
        items = list(raw_layers)
    except TypeError as exc:
        _err("INVALID_LAYERS", ("layers",), str(exc))
    result = {}
    sources = {}
    seen = set()
    def purge(path):
        for p in list(sources):
            if p[:len(path)] == path or path[:len(p)] == p:
                sources.pop(p, None)
    def assign(path, value, layer_id):
        nonlocal result
        if _is_delete(value):
            cur = result
            if path:
                for key in path[:-1]:
                    if not isinstance(cur, dict) or key not in cur: cur = None; break
                    cur = cur[key]
                if isinstance(cur, dict): cur.pop(path[-1], None)
            purge(path)
            return
        parent = result
        for key in path[:-1]:
            if key not in parent or not isinstance(parent[key], dict):
                parent[key] = {}
            parent = parent[key]
        if not path: return
        old = parent.get(path[-1])
        if isinstance(value, Mapping) and isinstance(old, Mapping):
            for key, child in value.items(): assign(path + (key,), child, layer_id)
        else:
            purge(path)
            parent[path[-1]] = clone_json(value)
            if isinstance(value, Mapping):
                for key, child in value.items(): assign(path + (key,), child, layer_id)
            else: sources[path] = layer_id
    for index, raw in enumerate(items):
        layer = validate_layer(raw, index)
        if layer.layer_id in seen: _err("DUPLICATE_LAYER", ("layers", index, "id"), "duplicate layer id")
        seen.add(layer.layer_id)
        for key, value in layer.data.items(): assign((key,), value, layer.layer_id)
    refs = tuple(SourceRef(sources[p], p) for p in sorted(sources, key=lambda p: (p, sources[p])))
    return MergedConfig(result, refs)

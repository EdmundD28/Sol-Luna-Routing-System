from __future__ import annotations

import copy
import re
from collections.abc import Mapping

from .model import BomError, Component, NormalizedChange

_FIELDS = ("id", "version", "quantity", "depends_on", "excludes")
_ID = re.compile(r"[A-Z][A-Z0-9_]*\Z")

def _err(code, path):
    raise BomError(code, tuple(path))

def _component(raw, index):
    path = ("components", index)
    if not isinstance(raw, Mapping):
        _err("INVALID_TYPE", path)
    for field in _FIELDS:
        if field not in raw:
            _err("MISSING_FIELD", path + (field,))
    unknown = sorted(set(raw) - set(_FIELDS), key=str)
    if unknown:
        _err("UNKNOWN_FIELD", path + (unknown[0],))
    cid = raw["id"]
    if not isinstance(cid, str) or _ID.fullmatch(cid) is None:
        _err("INVALID_ID", path + ("id",))
    values = []
    for field in ("version", "quantity"):
        value = raw[field]
        if type(value) is not int or value <= 0:
            _err("INVALID_INTEGER", path + (field,))
        values.append(value)
    refs = []
    for field in ("depends_on", "excludes"):
        value = raw[field]
        if not isinstance(value, (list, tuple)):
            _err("INVALID_TYPE", path + (field,))
        seen = set()
        normalized = []
        for ref_index, ref in enumerate(value):
            if not isinstance(ref, str) or _ID.fullmatch(ref) is None:
                _err("INVALID_ID", path + (field, ref_index))
            if ref in seen:
                _err("DUPLICATE_REFERENCE", path + (field, ref_index))
            seen.add(ref); normalized.append(ref)
        refs.append(tuple(sorted(normalized)))
    return Component(cid, values[0], values[1], refs[0], refs[1])

def _change(raw, index):
    path = ("changes", index)
    if not isinstance(raw, Mapping):
        _err("INVALID_TYPE", path)
    if "kind" not in raw:
        _err("MISSING_FIELD", path + ("kind",))
    if "source" not in raw:
        _err("MISSING_FIELD", path + ("source",))
    unknown = sorted(set(raw) - {"kind", "source", "quantity", "version", "target"}, key=str)
    if unknown:
        _err("UNKNOWN_FIELD", path + (unknown[0],))
    kind = raw["kind"]
    if kind not in {"set_quantity", "set_version", "replace", "remove"}:
        _err("INVALID_CHANGE", path + ("kind",))
    source = raw["source"]
    if not isinstance(source, str) or _ID.fullmatch(source) is None:
        _err("INVALID_ID", path + ("source",))
    if kind == "set_quantity":
        if "quantity" not in raw:
            _err("MISSING_FIELD", path + ("quantity",))
        if set(raw) != {"kind", "source", "quantity"}:
            _err("UNKNOWN_FIELD", path + (sorted(set(raw) - {"kind", "source", "quantity"})[0],))
        if type(raw["quantity"]) is not int or raw["quantity"] <= 0:
            _err("INVALID_INTEGER", path + ("quantity",))
        return NormalizedChange(kind, source, None, raw["quantity"])
    if kind == "set_version":
        if "version" not in raw:
            _err("MISSING_FIELD", path + ("version",))
        if set(raw) != {"kind", "source", "version"}:
            _err("UNKNOWN_FIELD", path + (sorted(set(raw) - {"kind", "source", "version"})[0],))
        if type(raw["version"]) is not int or raw["version"] <= 0:
            _err("INVALID_INTEGER", path + ("version",))
        return NormalizedChange(kind, source, None, raw["version"])
    if kind == "remove":
        if set(raw) != {"kind", "source"}:
            _err("UNKNOWN_FIELD", path + (sorted(set(raw) - {"kind", "source"})[0],))
        return NormalizedChange(kind, source, None, None)
    if "target" not in raw:
        _err("MISSING_FIELD", path + ("target",))
    allowed = {"kind", "source", "target", "version"}
    if set(raw) - allowed:
        _err("UNKNOWN_FIELD", path + (sorted(set(raw) - allowed)[0],))
    target = raw["target"]
    if not isinstance(target, str) or _ID.fullmatch(target) is None:
        _err("INVALID_ID", path + ("target",))
    version = raw.get("version")
    if "version" in raw and (type(version) is not int or version <= 0):
        _err("INVALID_INTEGER", path + ("version",))
    return NormalizedChange(kind, source, target, version)

def normalize_inputs(raw_components, raw_changes):
    if not isinstance(raw_components, (list, tuple)):
        _err("INVALID_TYPE", ("components",))
    initial = tuple(_component(raw, index) for index, raw in enumerate(raw_components))
    ids = [item.id for item in initial]
    seen_ids = set()
    for index, cid in enumerate(ids):
        if cid in seen_ids:
            _err("DUPLICATE_ID", ("components", index, "id"))
        seen_ids.add(cid)
    by_id = {item.id: item for item in initial}
    for index, item in enumerate(initial):
        for field, values in (("depends_on", item.depends_on), ("excludes", item.excludes)):
            for ref_index, ref in enumerate(values):
                if ref not in by_id:
                    _err("UNKNOWN_REFERENCE", ("components", index, field, ref_index))
                if ref == item.id:
                    _err("SELF_DEPENDENCY" if field == "depends_on" else "SELF_EXCLUSION", ("components", index, field, ref_index))
    if not isinstance(raw_changes, (list, tuple)):
        _err("INVALID_TYPE", ("changes",))
    changes = tuple(_change(raw, index) for index, raw in enumerate(raw_changes))
    for index, change in enumerate(changes):
        if change.source not in by_id:
            _err("UNKNOWN_SOURCE", ("changes", index, "source"))
        if any(previous.source == change.source for previous in changes[:index]):
            _err("DUPLICATE_CHANGE", ("changes", index, "source"))
    replacements = {change.source: change.target for change in changes if change.kind == "replace"}
    targets = set()
    replace_sources = set(replacements)
    for index, change in enumerate(changes):
        if change.kind != "replace":
            continue
        if change.target in targets or (change.target in by_id and change.target not in replace_sources):
            _err("TARGET_CONFLICT", ("changes", index, "target"))
        targets.add(change.target)
    removed = {change.source for change in changes if change.kind == "remove"}
    final_items = []
    for item in initial:
        change = next((entry for entry in changes if entry.source == item.id), None)
        if change is not None and change.kind == "remove":
            continue
        new_id = replacements.get(item.id, item.id)
        version = change.value if change is not None and change.kind == "replace" and change.value is not None else item.version
        deps = tuple(sorted(replacements.get(ref, ref) for ref in item.depends_on))
        excls = tuple(sorted(replacements.get(ref, ref) for ref in item.excludes if ref not in removed))
        if change is not None and change.kind == "set_quantity":
            quantity = change.value
        else:
            quantity = item.quantity
        if change is not None and change.kind == "set_version":
            version = change.value
        final_items.append(Component(new_id, version, quantity, deps, excls))
    return initial, tuple(sorted(changes, key=lambda c: (c.source, c.kind, c.target or "", c.value if c.value is not None else -1))), tuple(sorted(final_items, key=lambda c: c.id)), tuple(sorted(removed))

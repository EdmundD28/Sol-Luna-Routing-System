#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Small, human-auditable RUN/OK/BLOCK projection for frozen handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from typing import Any, Mapping


SCHEMA_VERSION = 1
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
RAW_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PACKAGE_REF_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,63})@([0-9a-f]{12})\Z")
COUNT_RE = re.compile(r"(?:0|[1-9][0-9]{0,6})\Z")
_DEVICE_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_EFFORT_CODES = dict(zip(_EFFORTS, "LMHXZ"))
_CODE_EFFORTS = {value: key for key, value in _EFFORT_CODES.items()}
_MANIFEST_FIELDS = {
    "schema_version", "package_id", "executor_id", "ownership_id", "task_digest", "allocation_digest",
    "luna_effort", "objective", "write_scope", "acceptance_ids", "forbidden_actions", "stop_conditions",
    "context_refs", "manifest_digest",
}
_CONTEXT_FIELDS = {"ref_id", "path", "content_digest", "kind"}
_CONTEXT_KINDS = {"file", "interface", "acceptance"}


class ProtocolError(ValueError):
    """The compact protocol input is unsafe, incomplete, or not canonical."""


def _reject_constant(value: str) -> Any:
    raise ProtocolError(f"non-finite JSON value: {value}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON key")
        result[key] = value
    return result


def load_json_strict(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProtocolError("invalid JSON") from exc


def _string(value: Any, field: str, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ProtocolError(f"{field} must be a non-empty safe string")
    if identifier:
        if not ID_RE.fullmatch(value):
            raise ProtocolError(f"{field} must be a compact identifier")
    return value


def _digest(value: Any, field: str) -> str:
    value = _string(value, field)
    if not DIGEST_RE.fullmatch(value):
        raise ProtocolError(f"{field} must be lowercase sha256")
    return value


def _raw_digest(value: Any, field: str) -> str:
    value = _string(value, field)
    if not RAW_DIGEST_RE.fullmatch(value):
        raise ProtocolError(f"{field} must be 64 lowercase hexadecimal characters")
    return value


def normalize_repo_path(value: Any) -> str:
    value = _string(value, "path")
    if "\\" in value or ":" in value or value.startswith("/") or value.endswith("/"):
        raise ProtocolError("path must be normalized and repository-relative")
    value = unicodedata.normalize("NFC", value)
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ProtocolError("path traversal or empty component")
    for part in parts:
        if part.endswith((".", " ")) or part.split(".", 1)[0].casefold() in _DEVICE_NAMES:
            raise ProtocolError("path uses an unsafe Windows name")
    return value


def _list_of_ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ProtocolError(f"{field} must be a non-empty identifier list")
    result = [_string(item, field, identifier=True) for item in value]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise ProtocolError(f"{field} contains duplicate identifiers")
    return sorted(result)


def _paths(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ProtocolError(f"{field} must be a non-empty path list")
    result = [normalize_repo_path(item) for item in value]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise ProtocolError(f"{field} contains duplicate paths")
    return sorted(result)


def _validate_context(raw: Any, index: int) -> dict[str, str]:
    if not isinstance(raw, Mapping) or set(raw) - _CONTEXT_FIELDS or set(raw) != _CONTEXT_FIELDS:
        raise ProtocolError(f"context_refs[{index}] has unknown or missing fields")
    kind = _string(raw.get("kind"), f"context_refs[{index}].kind")
    if kind not in _CONTEXT_KINDS:
        raise ProtocolError(f"context_refs[{index}] has invalid kind")
    return {
        "ref_id": _string(raw.get("ref_id"), f"context_refs[{index}].ref_id", identifier=True),
        "path": normalize_repo_path(raw.get("path")),
        "content_digest": _digest(raw.get("content_digest"), f"context_refs[{index}].content_digest"),
        "kind": kind,
    }


def validate_manifest(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ProtocolError("manifest must be a JSON object")
    unknown = set(raw) - _MANIFEST_FIELDS
    if unknown:
        raise ProtocolError("manifest has unknown fields")
    if not isinstance(raw.get("schema_version"), int) or isinstance(raw.get("schema_version"), bool) or raw.get("schema_version") != 1:
        raise ProtocolError("schema_version must be integer 1")
    result: dict[str, Any] = {
        "schema_version": 1,
        "package_id": _string(raw.get("package_id"), "package_id", identifier=True),
        "executor_id": _string(raw.get("executor_id"), "executor_id", identifier=True),
        "ownership_id": _string(raw.get("ownership_id"), "ownership_id", identifier=True),
        "task_digest": _digest(raw.get("task_digest"), "task_digest"),
        "allocation_digest": _digest(raw.get("allocation_digest"), "allocation_digest"),
        "luna_effort": _string(raw.get("luna_effort"), "luna_effort"),
        "objective": _string(raw.get("objective"), "objective"),
        "write_scope": _paths(raw.get("write_scope"), "write_scope"),
        "acceptance_ids": _list_of_ids(raw.get("acceptance_ids"), "acceptance_ids"),
        "forbidden_actions": _list_of_ids(raw.get("forbidden_actions"), "forbidden_actions"),
        "stop_conditions": _list_of_ids(raw.get("stop_conditions"), "stop_conditions"),
        "context_refs": [],
    }
    if result["luna_effort"] not in _EFFORTS:
        raise ProtocolError("luna_effort is invalid")
    refs = raw.get("context_refs")
    if not isinstance(refs, list):
        raise ProtocolError("context_refs must be a JSON array")
    result["context_refs"] = sorted((_validate_context(item, i) for i, item in enumerate(refs)), key=lambda item: item["ref_id"])
    ref_ids = [item["ref_id"].casefold() for item in result["context_refs"]]
    ref_paths = [item["path"].casefold() for item in result["context_refs"]]
    if len(ref_ids) != len(set(ref_ids)) or len(ref_paths) != len(set(ref_paths)):
        raise ProtocolError("context_refs contain duplicate identifiers or paths")
    if "manifest_digest" in raw:
        result["manifest_digest"] = _digest(raw["manifest_digest"], "manifest_digest")
    return result


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProtocolError("value cannot be canonically encoded") from exc


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    normalized = validate_manifest(manifest)
    normalized.pop("manifest_digest", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(normalized)).hexdigest()


def freeze_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_manifest(manifest)
    expected = manifest_digest(result)
    if "manifest_digest" in result and result["manifest_digest"] != expected:
        raise ProtocolError("manifest_digest does not match manifest content")
    result["manifest_digest"] = expected
    return result


def package_ref(manifest: Mapping[str, Any]) -> str:
    frozen = freeze_manifest(manifest)
    return f"{frozen['package_id']}@{frozen['manifest_digest'][7:19]}"


def _validate_package_ref(value: str) -> str:
    if not isinstance(value, str) or not PACKAGE_REF_RE.fullmatch(value):
        raise ProtocolError("invalid package reference")
    return value


def run_line(manifest: Mapping[str, Any]) -> str:
    frozen = freeze_manifest(manifest)
    return "|".join(
        (
            "RUN",
            package_ref(frozen),
            f"E={_EFFORT_CODES[frozen['luna_effort']]}",
            f"OWN={frozen['ownership_id']}",
            f"ACC={','.join(frozen['acceptance_ids'])}",
            f"STOP={','.join(frozen['stop_conditions'])}",
        )
    )


def _line_ascii(line: Any) -> str:
    if not isinstance(line, str) or not line or any(ord(char) < 33 or ord(char) > 126 for char in line):
        raise ProtocolError("protocol line must be printable ASCII without whitespace")
    return line


def _fields(line: Any, record: str, count: int) -> list[str]:
    parts = _line_ascii(line).split("|")
    if len(parts) != count or parts[0] != record:
        raise ProtocolError("invalid field count or record type")
    if any(not part for part in parts):
        raise ProtocolError("empty protocol field")
    return parts


def _key_value(value: str, key: str) -> str:
    prefix = key + "="
    if not value.startswith(prefix) or not value[len(prefix):] or "=" in value[len(prefix):]:
        raise ProtocolError("invalid protocol key")
    return value[len(prefix):]


def _list_value(value: str, key: str) -> list[str]:
    result = [_string(item, key, identifier=True) for item in _key_value(value, key).split(",")]
    folded = [item.casefold() for item in result]
    if len(folded) != len(set(folded)):
        raise ProtocolError("duplicate protocol list value")
    return sorted(result)


def _bind_package(ref: str, manifest: Mapping[str, Any] | None) -> None:
    _validate_package_ref(ref)
    if manifest is not None and package_ref(manifest) != ref:
        raise ProtocolError("package reference does not match manifest")


def _parse_run(parts: list[str], manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    package = parts[1]
    _bind_package(package, manifest)
    effort_code = _key_value(parts[2], "E")
    if effort_code not in _CODE_EFFORTS:
        raise ProtocolError("invalid effort code")
    ownership = _string(_key_value(parts[3], "OWN"), "ownership_id", identifier=True)
    acceptance = _list_value(parts[4], "ACC")
    stops = _list_value(parts[5], "STOP")
    if manifest is not None:
        frozen = freeze_manifest(manifest)
        if effort_code != _EFFORT_CODES[frozen["luna_effort"]] or ownership != frozen["ownership_id"] or acceptance != frozen["acceptance_ids"] or stops != frozen["stop_conditions"]:
            raise ProtocolError("RUN line does not match manifest")
    return {"record_type": "RUN", "package_ref": package, "effort": _CODE_EFFORTS[effort_code], "ownership_id": ownership, "acceptance_ids": acceptance, "stop_conditions": stops}


def _count(value: str, field: str) -> int:
    if not COUNT_RE.fullmatch(value):
        raise ProtocolError(f"{field} must be a bounded non-negative integer")
    return int(value)


def _parse_ok(parts: list[str], manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    package = parts[1]
    _bind_package(package, manifest)
    candidate = _raw_digest(_key_value(parts[2], "C"), "candidate_digest")
    path_digest = _raw_digest(_key_value(parts[3], "PD"), "path_set_digest")
    test = _key_value(parts[4], "TEST").split("/")
    if len(test) != 2:
        raise ProtocolError("TEST must be passed/total")
    passed, total = _count(test[0], "passed"), _count(test[1], "total")
    if total == 0 or passed != total:
        raise ProtocolError("OK requires passed == total and total > 0")
    paths = _count(_key_value(parts[5], "PATH"), "path count")
    repairs = _count(_key_value(parts[6], "REPAIR"), "repair count")
    if _key_value(parts[7], "EX") != "0":
        raise ProtocolError("OK requires EX=0")
    return {"record_type": "OK", "package_ref": package, "candidate_digest": "sha256:" + candidate, "path_set_digest": "sha256:" + path_digest, "passed": passed, "total": total, "path_count": paths, "repair_count": repairs, "exceptions": 0}


def _validate_ref(value: str) -> str:
    if ":" in value:
        path, line = value.rsplit(":", 1)
        if not re.fullmatch(r"[0-9]+", line) or int(line) <= 0:
            raise ProtocolError("reference line must be a positive integer")
    else:
        path = value
    normalized = normalize_repo_path(path)
    return normalized + ((":" + line) if ":" in value else "")


def _parse_block(parts: list[str], manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    package = parts[1]
    _bind_package(package, manifest)
    kind = _key_value(parts[2], "K")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", kind):
        raise ProtocolError("invalid BLOCK code")
    reference = _validate_ref(_key_value(parts[3], "REF"))
    options = _list_value(parts[4], "OPT")
    return {"record_type": "BLOCK", "package_ref": package, "code": kind, "reference": reference, "options": options}


def parse_line(line: str, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(line, str):
        raise ProtocolError("protocol line must be a string")
    record = line.split("|", 1)[0] if line else ""
    if record == "RUN":
        return _parse_run(_fields(line, "RUN", 6), manifest)
    if record == "OK":
        return _parse_ok(_fields(line, "OK", 8), manifest)
    if record == "BLOCK":
        return _parse_block(_fields(line, "BLOCK", 5), manifest)
    raise ProtocolError("unknown record type")


def ok_line(manifest: Mapping[str, Any], candidate: str, path_set: str, passed: int, total: int, path_count: int, repair_count: int) -> str:
    frozen = freeze_manifest(manifest)
    package = package_ref(frozen)
    candidate = _raw_digest(candidate[7:] if isinstance(candidate, str) and candidate.startswith("sha256:") else candidate, "candidate_digest")
    path_set = _raw_digest(path_set[7:] if isinstance(path_set, str) and path_set.startswith("sha256:") else path_set, "path_set_digest")
    passed, total = _count(str(passed), "passed"), _count(str(total), "total")
    if total == 0 or passed != total:
        raise ProtocolError("OK requires passed == total and total > 0")
    path_count, repair_count = _count(str(path_count), "path count"), _count(str(repair_count), "repair count")
    return f"OK|{package}|C={candidate}|PD={path_set}|TEST={passed}/{total}|PATH={path_count}|REPAIR={repair_count}|EX=0"


def block_line(manifest: Mapping[str, Any], code: str, reference: str, options: list[str]) -> str:
    package = package_ref(manifest)
    code = _string(code, "code")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
        raise ProtocolError("invalid BLOCK code")
    reference = _validate_ref(reference)
    options = _list_of_ids(options, "options")
    return f"BLOCK|{package}|K={code}|REF={reference}|OPT={','.join(options)}"


parse_manifest = validate_manifest
manifest_reference = package_ref


def validate_binding(line: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Parse a protocol line and require that it binds to the frozen manifest."""
    return parse_line(line, manifest)


def _read_json(path: str) -> Any:
    try:
        text = (sys.stdin.buffer.read().decode("utf-8") if path == "-" else open(path, encoding="utf-8", newline="").read())
        return load_json_strict(text)
    except (OSError, ProtocolError) as exc:
        if isinstance(exc, ProtocolError):
            raise
        raise ProtocolError("cannot read JSON input") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compact_protocol")
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--input", default="-")
    run = sub.add_parser("run")
    run.add_argument("--manifest", required=True)
    parse = sub.add_parser("parse")
    parse.add_argument("--line", required=True)
    parse.add_argument("--manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "freeze":
            result = freeze_manifest(_read_json(args.input))
            print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        elif args.command == "run":
            print(run_line(freeze_manifest(_read_json(args.manifest))))
        else:
            manifest = freeze_manifest(_read_json(args.manifest)) if args.manifest else None
            print(json.dumps(parse_line(args.line, manifest), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 0
    except (ProtocolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

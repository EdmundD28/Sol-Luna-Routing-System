#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Read-only, content-addressed snapshots of a Git working-tree candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import unicodedata
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DEVICE_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_TOP_FIELDS = {"schema_version", "base_commit", "entries", "candidate_digest"}
_ENTRY_FIELDS = {"path", "state", "kind", "mode", "content_digest"}
_STATES = {"added", "modified", "deleted", "type_changed"}
_KINDS = {"file", "symlink", "submodule"}
_MODES = {"100644", "100755", "120000", "160000"}


class SnapshotError(ValueError):
    """A candidate cannot be represented safely or deterministically."""


def _reject_constant(value: str) -> Any:
    raise SnapshotError(f"non-finite JSON value: {value}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(text: str) -> Any:
    """Load JSON while rejecting duplicate keys and non-finite numbers."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise SnapshotError("invalid JSON") from exc


def parse_expected_digest(value: Any) -> str:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise SnapshotError("expected digest must be sha256 followed by 64 lowercase hexadecimal characters")
    return value


def normalize_repo_path(value: Any) -> str:
    """Return a portable, NFC-normalized repository-relative path."""
    if not isinstance(value, str) or not value:
        raise SnapshotError("path must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SnapshotError("path contains a control character")
    if "\\" in value or value.startswith("/") or value.endswith("/"):
        raise SnapshotError("path is not a normalized repository-relative path")
    normalized = unicodedata.normalize("NFC", value)
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SnapshotError("path traversal or empty path component")
    for part in parts:
        if part.endswith((".", " ")):
            raise SnapshotError("path has an unsafe trailing component")
        if part.split(".", 1)[0].casefold() in _DEVICE_NAMES:
            raise SnapshotError("path uses a reserved device name")
    # PurePosixPath is deliberately only an additional lexical check; never resolve
    # a candidate symlink, since its target bytes are part of the candidate.
    if str(PurePosixPath(normalized)) != normalized:
        raise SnapshotError("path is not normalized")
    return normalized


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize an object as strict, deterministic UTF-8 JSON."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SnapshotError("value cannot be canonically encoded") from exc


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotError(f"{field} must be an integer")
    return value


def _validate_entry(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise SnapshotError(f"entries[{index}] must be an object")
    unknown = set(raw) - _ENTRY_FIELDS
    if unknown:
        raise SnapshotError(f"entries[{index}] has unknown fields")
    path = normalize_repo_path(raw.get("path"))
    state = raw.get("state")
    if not isinstance(state, str) or state not in _STATES:
        raise SnapshotError(f"entries[{index}] has invalid state")
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise SnapshotError(f"entries[{index}] has invalid kind")
    mode = raw.get("mode")
    if not isinstance(mode, str) or mode not in _MODES:
        raise SnapshotError(f"entries[{index}] has invalid mode")
    if state == "deleted":
        if "content_digest" not in raw or raw["content_digest"] is not None:
            raise SnapshotError(f"entries[{index}] deleted entry must have null content_digest")
    else:
        if kind == "submodule" or "content_digest" not in raw:
            raise SnapshotError(f"entries[{index}] present entry is incomplete")
        parse_expected_digest(raw["content_digest"])
    return {
        "path": path,
        "state": state,
        "kind": kind,
        "mode": mode,
        "content_digest": raw["content_digest"],
    }


def validate_snapshot(raw: Any, *, require_digest: bool = False) -> dict[str, Any]:
    """Validate and normalize a snapshot object, rejecting unknown fields."""
    if not isinstance(raw, Mapping):
        raise SnapshotError("snapshot must be a JSON object")
    unknown = set(raw) - _TOP_FIELDS
    if unknown:
        raise SnapshotError("snapshot has unknown fields")
    if _require_int(raw.get("schema_version"), "schema_version") != SCHEMA_VERSION:
        raise SnapshotError("unsupported snapshot schema_version")
    base = raw.get("base_commit")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", base):
        raise SnapshotError("base_commit must be a full Git commit id")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise SnapshotError("entries must be a JSON array")
    normalized_entries = [_validate_entry(entry, index) for index, entry in enumerate(entries)]
    paths = [entry["path"] for entry in normalized_entries]
    if len(paths) != len(set(paths)):
        raise SnapshotError("entries contain duplicate paths")
    normalized_entries.sort(key=lambda entry: entry["path"])
    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "base_commit": base, "entries": normalized_entries}
    if "candidate_digest" in raw:
        result["candidate_digest"] = parse_expected_digest(raw["candidate_digest"])
    elif require_digest:
        raise SnapshotError("candidate_digest is missing")
    return result


def candidate_digest(snapshot: Mapping[str, Any]) -> str:
    normalized = validate_snapshot(snapshot)
    normalized.pop("candidate_digest", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(normalized)).hexdigest()


def _git(repo: Path, args: Iterable[str]) -> bytes:
    env = os.environ.copy()
    # Read-only Git commands must not take an index lock or refresh the index.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=true", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )
    except OSError as exc:
        raise SnapshotError("git command failed") from exc
    try:
        stdout = result.stdout.decode("utf-8")
        result.stderr.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotError("Git output is not valid UTF-8") from exc
    if result.returncode:
        raise SnapshotError("git command failed")
    return stdout.encode("utf-8")


def _repo_root(value: str | os.PathLike[str]) -> Path:
    requested = Path(value)
    try:
        root = requested.resolve(strict=True)
    except OSError as exc:
        raise SnapshotError("repository is missing or inaccessible") from exc
    if not root.is_dir():
        raise SnapshotError("repository is missing or inaccessible")
    reported = _git(root, ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
    try:
        actual = Path(reported).resolve(strict=True)
    except OSError as exc:
        raise SnapshotError("invalid repository root") from exc
    if actual != root:
        raise SnapshotError("--repo must name the repository root")
    return root


def _resolve_base(repo: Path, base: str | None) -> str:
    value = "HEAD" if base is None else base
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SnapshotError("invalid base")
    try:
        resolved = _git(repo, ["rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}"])
    except SnapshotError as exc:
        raise SnapshotError("invalid base") from exc
    commit = resolved.decode("utf-8").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise SnapshotError("invalid base")
    return commit.lower()


def _decode_git_path(token: bytes) -> str:
    if not token.startswith(b'"'):
        try:
            return normalize_repo_path(token.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise SnapshotError("Git output is not valid UTF-8") from exc
    if len(token) < 2 or token[-1:] != b'"':
        raise SnapshotError("ambiguous Git status")
    decoded = bytearray()
    index = 1
    while index < len(token) - 1:
        value = token[index]
        if value != ord("\\"):
            decoded.append(value)
            index += 1
            continue
        index += 1
        if index >= len(token) - 1:
            raise SnapshotError("ambiguous Git status")
        escaped = token[index]
        simple = {ord("a"): 7, ord("b"): 8, ord("t"): 9, ord("n"): 10, ord("v"): 11, ord("f"): 12, ord("r"): 13}
        if escaped in simple:
            decoded.append(simple[escaped])
            index += 1
        elif escaped in {ord('\\'), ord('"')}:
            decoded.append(escaped)
            index += 1
        elif ord("0") <= escaped <= ord("7"):
            if index + 2 >= len(token) - 1 or not all(ord("0") <= digit <= ord("7") for digit in token[index : index + 3]):
                raise SnapshotError("ambiguous Git status")
            decoded.append(int(token[index : index + 3], 8))
            index += 3
        else:
            raise SnapshotError("ambiguous Git status")
    try:
        return normalize_repo_path(bytes(decoded).decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SnapshotError("Git output is not valid UTF-8") from exc


def _lines(raw: bytes) -> list[bytes]:
    if not raw:
        return []
    lines = raw.split(b"\n")
    if lines[-1] != b"":
        raise SnapshotError("ambiguous Git status")
    return lines[:-1]


def _parse_diff_paths(raw: bytes) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line in _lines(raw):
        try:
            status_raw, path_raw = line.split(b"\t", 1)
            status = status_raw.decode("ascii")
        except (UnicodeDecodeError, ValueError) as exc:
            raise SnapshotError("ambiguous Git status") from exc
        path = _decode_git_path(path_raw)
        if len(status) != 1 or status not in {"A", "D", "M", "T"}:
            raise SnapshotError("ambiguous Git status")
        found.append((status, path))
    return found


def _parse_untracked_paths(raw: bytes) -> list[str]:
    return [_decode_git_path(line) for line in _lines(raw)]


def _base_tree(repo: Path, base: str) -> dict[str, tuple[str, str, str]]:
    raw = _git(repo, ["ls-tree", "-r", "--full-tree", base])
    result: dict[str, tuple[str, str, str]] = {}
    for record in _lines(raw):
        try:
            header, path_raw = record.split(b"\t", 1)
            mode_raw, kind_raw, object_raw = header.split(b" ", 2)
            path = _decode_git_path(path_raw)
            mode = mode_raw.decode("ascii")
            kind = kind_raw.decode("ascii")
            object_id = object_raw.decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SnapshotError("malformed Git tree") from exc
        if path in result:
            raise SnapshotError("ambiguous Git tree")
        if mode == "160000" or kind == "commit":
            result[path] = ("submodule", mode, object_id)
        elif mode == "120000" or kind == "symlink":
            result[path] = ("symlink", mode, object_id)
        elif mode in {"100644", "100755"} and kind == "blob":
            result[path] = ("file", mode, object_id)
        else:
            raise SnapshotError("unsupported Git tree entry")
    return result


def _current_content(path: Path, object_format: str) -> tuple[str, str, str, str]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise SnapshotError("candidate changed during snapshot")
    except OSError as exc:
        raise SnapshotError("cannot read candidate path") from exc
    mode_bits = info.st_mode
    if stat.S_ISLNK(mode_bits):
        try:
            content = os.fsencode(os.readlink(path))
        except OSError as exc:
            raise SnapshotError("cannot read symlink target") from exc
        return (
            "symlink",
            "120000",
            "sha256:" + hashlib.sha256(content).hexdigest(),
            _git_blob_digest(content, object_format),
        )
    if stat.S_ISREG(mode_bits):
        mode = "100755" if mode_bits & stat.S_IXUSR else "100644"
        digest = hashlib.sha256()
        object_digest = hashlib.new(object_format)
        object_digest.update(f"blob ".encode("ascii"))
        # The raw blob digest includes its exact byte length before the content.
        size = path.stat().st_size
        object_digest = hashlib.new(object_format)
        object_digest.update(f"blob {size}\0".encode("ascii"))
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    object_digest.update(chunk)
        except OSError as exc:
            raise SnapshotError("cannot read candidate file") from exc
        return "file", mode, "sha256:" + digest.hexdigest(), object_digest.hexdigest()
    raise SnapshotError("unsupported candidate file kind")


def _git_blob_digest(content: bytes, object_format: str) -> str:
    digest = hashlib.new(object_format)
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def _safe_candidate_path(root: Path, relative: str) -> Path:
    """Reject ancestor symlinks so a repository path cannot read outside root."""
    path = root.joinpath(*relative.split("/"))
    cursor = root
    for component in relative.split("/")[:-1]:
        cursor = cursor / component
        try:
            if cursor.is_symlink():
                raise SnapshotError("candidate path escapes repository root")
        except OSError as exc:
            raise SnapshotError("cannot inspect candidate path") from exc
    try:
        resolved_parent = path.parent.resolve(strict=False)
        resolved_parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise SnapshotError("candidate path escapes repository root") from exc
    return path


def _capture_snapshot(repo: str | os.PathLike[str], base: str | None = None) -> dict[str, Any]:
    root = _repo_root(repo)
    resolved_base = _resolve_base(root, base)
    object_format = _git(root, ["rev-parse", "--show-object-format"]).decode("utf-8").strip()
    if object_format not in {"sha1", "sha256"}:
        raise SnapshotError("unsupported Git object format")
    tree = _base_tree(root, resolved_base)
    diff = _parse_diff_paths(_git(root, ["diff", "--name-status", "--no-renames", "--no-ext-diff", "--no-textconv", resolved_base, "--"]))
    untracked = _parse_untracked_paths(_git(root, ["ls-files", "--others", "--exclude-standard", "--full-name"]))
    statuses: dict[str, str] = {}
    for status, path in diff:
        if path in statuses:
            raise SnapshotError("ambiguous Git status")
        statuses[path] = status
    for path in untracked:
        if path in statuses:
            raise SnapshotError("ambiguous Git status")
        statuses[path] = "A"
    entries: list[dict[str, Any]] = []
    for path in sorted(statuses):
        full_path = _safe_candidate_path(root, path)
        base_info = tree.get(path)
        if base_info and base_info[0] == "submodule":
            raise SnapshotError("submodule changes are not supported")
        exists = os.path.lexists(full_path)
        if not exists:
            if base_info is None:
                raise SnapshotError("ambiguous Git status")
            entries.append(
                {
                    "path": path,
                    "state": "deleted",
                    "kind": base_info[0],
                    "mode": base_info[1],
                    "content_digest": None,
                }
            )
            continue
        kind, mode, content_digest, object_id = _current_content(full_path, object_format)
        if base_info is not None and base_info[0] == kind and base_info[1] == mode and base_info[2] == object_id:
            # The index may report a staged-only difference; the candidate is the
            # current filesystem state relative to the selected base.
            continue
        if base_info is None:
            state = "added"
        elif base_info[0] != kind:
            state = "type_changed" if base_info[0] != kind else "modified"
        else:
            state = "modified"
        entries.append(
            {
                "path": path,
                "state": state,
                "kind": kind,
                "mode": mode,
                "content_digest": content_digest,
            }
        )
    result = {"schema_version": SCHEMA_VERSION, "base_commit": resolved_base, "entries": entries}
    result["candidate_digest"] = candidate_digest(result)
    return result


def build_snapshot(repo: str | os.PathLike[str], base: str | None = None) -> dict[str, Any]:
    """Capture twice so a changing candidate cannot produce a mixed snapshot."""
    first = _capture_snapshot(repo, base)
    second = _capture_snapshot(repo, base)
    comparable = lambda value: {key: value[key] for key in ("schema_version", "base_commit", "entries")}
    if comparable(first) != comparable(second):
        raise SnapshotError("candidate changed during snapshot")
    return second


snapshot = build_snapshot

def verify_snapshot(repo: str | os.PathLike[str], expected: str, base: str | None = None) -> dict[str, Any]:
    expected = parse_expected_digest(expected)
    result = build_snapshot(repo, base)
    if result["candidate_digest"] != expected:
        raise SnapshotError("candidate digest mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "MATCH",
        "base_commit": result["base_commit"],
        "candidate_digest": result["candidate_digest"],
    }


# Import-friendly aliases kept deliberately small for callers that prefer noun
# or verb naming without adding a second implementation surface.
canonical_json = canonical_bytes
snapshot_digest = candidate_digest
verify = verify_snapshot


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candidate_snapshot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("snapshot", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--repo", required=True)
        sub.add_argument("--base")
        if command == "verify":
            sub.add_argument("--expected", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_snapshot(args.repo, args.base) if args.command == "snapshot" else verify_snapshot(args.repo, args.expected, args.base)
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    # Keep the transport ASCII-only: Windows console/code-page settings must not
    # reinterpret a valid Unicode path after the snapshot has been computed.
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

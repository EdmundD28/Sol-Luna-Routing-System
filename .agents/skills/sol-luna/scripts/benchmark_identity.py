#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Build a redacted host-observed identity index for matched benchmark runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
ROUTES = {"SOL_ONLY", "SOL_LUNA"}
LABEL = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
MANIFEST_FIELDS = {"schema_version", "campaign_id", "runs"}
RUN_FIELDS = {"pair_id", "route", "controller_receipt", "worker_receipts"}
RECEIPT_FIELDS = {
    "schema_version", "status", "thread_ref", "source_ref", "source_kind",
    "invalid_jsonl_lines", "source_warnings", "requested", "host_observed",
    "mismatches", "unknown_identity_fields", "unknown_boundary_fields",
    "self_report_used_as_proof",
}
REQUESTED_FIELDS = {
    "agent", "model", "effort", "sandbox_policy_type", "permission_profile_type",
}
OBSERVED_FIELDS = {
    "agent_role", "agent_path_ref", "model_provider", "model", "effort",
    "sandbox_policy_type", "permission_profile_type", "cwd_ref",
}
CONTROLLER_ROLES = {"default", "worker"}
WRITER_ROLES = {"worker", "luna_worker", "luna_worker_high"}
WINDOWS_DEVICE_NAMES = {
    "con", "prn", "aux", "nul", *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class IdentityError(ValueError):
    """A manifest, runtime receipt, or output violates the identity contract."""


def canonical_bytes(value: Mapping[str, Any] | list[Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def require_exact_fields(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IdentityError(f"{name} must be a JSON object")
    unsupported = set(value) - fields
    missing = fields - set(value)
    if unsupported:
        raise IdentityError(f"{name} has unsupported fields: {sorted(unsupported)}")
    if missing:
        raise IdentityError(f"{name} is missing fields: {sorted(missing)}")
    return value


def require_label(value: Any, name: str) -> str:
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise IdentityError(f"{name} must be a non-sensitive hyphen-case label")
    return value


def load_json_object(path: Path, name: str) -> tuple[Mapping[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityError(f"cannot load {name}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise IdentityError(f"{name} must be a JSON object")
    return value, raw


def safe_receipt_path(manifest: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value or value != value.strip():
        raise IdentityError(f"{name} must be a non-empty relative path")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise IdentityError(f"{name} contains a control character")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise IdentityError(f"{name} must not be absolute or contain a drive")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise IdentityError(f"{name} contains an unsafe path component")
    for part in parts:
        if part.endswith((" ", ".")) or part.split(".", 1)[0].casefold() in WINDOWS_DEVICE_NAMES:
            raise IdentityError(f"{name} contains a Windows device or ambiguous component")
    base = manifest.parent.resolve()
    candidate = base.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise IdentityError(f"{name} does not name an existing receipt") from exc
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise IdentityError(f"{name} escapes the manifest directory") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise IdentityError(f"{name} must name a regular receipt file")
    return resolved


def _validate_requested_field(value: Any, name: str) -> None:
    if not isinstance(value, Mapping):
        raise IdentityError(f"{name} must be an object")
    provenance = value.get("provenance")
    if provenance == "requested":
        require_exact_fields(value, {"value", "provenance"}, name)
        if not isinstance(value["value"], str) or not value["value"]:
            raise IdentityError(f"{name}.value must be a non-empty string")
    elif provenance == "unknown":
        require_exact_fields(value, {"value", "provenance", "issue"}, name)
        if value["value"] is not None or not isinstance(value["issue"], str) or not value["issue"]:
            raise IdentityError(f"{name} has an invalid unknown value")
    else:
        raise IdentityError(f"{name}.provenance must be requested or unknown")


def _host_value(value: Any, name: str) -> str:
    source = require_exact_fields(value, {"value", "provenance"}, name)
    if source["provenance"] != "host_observed":
        raise IdentityError(f"{name} must have host_observed provenance")
    if not isinstance(source["value"], str) or not source["value"]:
        raise IdentityError(f"{name}.value must be a non-empty string")
    return source["value"]


def _validate_optional_observed_field(value: Any, name: str) -> None:
    if not isinstance(value, Mapping):
        raise IdentityError(f"{name} must be an object")
    if value.get("provenance") == "host_observed":
        _host_value(value, name)
        return
    source = require_exact_fields(value, {"value", "provenance", "issue"}, name)
    if (
        source["provenance"] != "unknown" or source["value"] is not None
        or not isinstance(source["issue"], str) or not source["issue"]
    ):
        raise IdentityError(f"{name} has an invalid unknown value")


def validate_receipt(value: Mapping[str, Any], name: str) -> dict[str, str]:
    source = require_exact_fields(value, RECEIPT_FIELDS, name)
    if (
        not isinstance(source["schema_version"], int)
        or isinstance(source["schema_version"], bool)
        or source["schema_version"] != SCHEMA_VERSION
    ):
        raise IdentityError(f"{name} has an unsupported schema_version")
    if source["status"] != "verified" or source["source_kind"] != "explicit_session_jsonl":
        raise IdentityError(f"{name} is not a verified explicit-session receipt")
    if source["self_report_used_as_proof"] is not False:
        raise IdentityError(f"{name} uses self-report as proof")
    if (
        isinstance(source["invalid_jsonl_lines"], bool)
        or not isinstance(source["invalid_jsonl_lines"], int)
        or source["invalid_jsonl_lines"] != 0
    ):
        raise IdentityError(f"{name} contains invalid JSONL lines")
    for field in ("source_warnings", "mismatches", "unknown_identity_fields", "unknown_boundary_fields"):
        if source[field] != []:
            raise IdentityError(f"{name}.{field} must be empty")
    for field in ("thread_ref", "source_ref"):
        if not isinstance(source[field], str) or not source[field]:
            raise IdentityError(f"{name}.{field} must be a non-empty string")
    requested = require_exact_fields(source["requested"], REQUESTED_FIELDS, f"{name}.requested")
    for field in REQUESTED_FIELDS:
        _validate_requested_field(requested[field], f"{name}.requested.{field}")
    observed = require_exact_fields(source["host_observed"], OBSERVED_FIELDS, f"{name}.host_observed")
    required_host_fields = {
        "agent_role", "model_provider", "model", "effort",
        "sandbox_policy_type", "permission_profile_type",
    }
    values = {
        field: _host_value(observed[field], f"{name}.host_observed.{field}")
        for field in required_host_fields
    }
    for field in ("agent_path_ref", "cwd_ref"):
        _validate_optional_observed_field(observed[field], f"{name}.host_observed.{field}")
    return {
        "model": values["model"],
        "effort": values["effort"],
        "role": values["agent_role"],
        "provider": values["model_provider"],
    }


def _identity_output(identity: Mapping[str, str], digest: str) -> dict[str, str]:
    return {
        "model": identity["model"], "effort": identity["effort"],
        "role": identity["role"], "provider": identity["provider"],
        "receipt_sha256": digest,
    }


def _validate_controller(identity: Mapping[str, str], name: str) -> None:
    if (
        identity["model"] != "gpt-5.6-sol" or identity["effort"] != "high"
        or identity["provider"] != "openai" or identity["role"] not in CONTROLLER_ROLES
    ):
        raise IdentityError(f"{name} must be a host-observed gpt-5.6-sol/high OpenAI controller")


def _validate_writer(identity: Mapping[str, str], name: str) -> None:
    if (
        identity["model"] != "gpt-5.6-luna" or identity["effort"] != "high"
        or identity["provider"] != "openai" or identity["role"] not in WRITER_ROLES
    ):
        raise IdentityError(f"{name} must be a host-observed gpt-5.6-luna/high OpenAI writer")


def build_index(manifest: Path) -> dict[str, Any]:
    raw_manifest, _ = load_json_object(manifest, "manifest")
    source = require_exact_fields(raw_manifest, MANIFEST_FIELDS, "manifest")
    if (
        not isinstance(source["schema_version"], int)
        or isinstance(source["schema_version"], bool)
        or source["schema_version"] != SCHEMA_VERSION
    ):
        raise IdentityError("manifest has an unsupported schema_version")
    campaign_id = require_label(source["campaign_id"], "campaign_id")
    if not isinstance(source["runs"], list) or not source["runs"]:
        raise IdentityError("runs must be a non-empty JSON array")
    output_runs: list[dict[str, Any]] = []
    pair_routes: dict[str, set[str]] = {}
    receipt_digests: set[str] = set()
    for index, raw_run in enumerate(source["runs"]):
        run_name = f"runs[{index}]"
        run = require_exact_fields(raw_run, RUN_FIELDS, run_name)
        pair_id = require_label(run["pair_id"], f"{run_name}.pair_id")
        route = run["route"]
        if route not in ROUTES:
            raise IdentityError(f"{run_name}.route must be SOL_ONLY or SOL_LUNA")
        seen_routes = pair_routes.setdefault(pair_id, set())
        if route in seen_routes:
            raise IdentityError(f"duplicate run for {pair_id}:{route}")
        seen_routes.add(route)
        workers = run["worker_receipts"]
        if not isinstance(workers, list) or any(not isinstance(item, str) for item in workers):
            raise IdentityError(f"{run_name}.worker_receipts must be a JSON string array")
        if route == "SOL_ONLY" and workers:
            raise IdentityError("SOL_ONLY must not contain subordinate writers")
        if route == "SOL_LUNA" and not 1 <= len(workers) <= 2:
            raise IdentityError("SOL_LUNA must contain one or two writers")

        def consume(receipt_ref: Any, receipt_name: str) -> tuple[dict[str, str], str]:
            path = safe_receipt_path(manifest, receipt_ref, receipt_name)
            receipt, _ = load_json_object(path, receipt_name)
            digest = sha256_bytes(canonical_bytes(receipt))
            if digest in receipt_digests:
                raise IdentityError("the same logical receipt cannot be reused across runs or roles")
            receipt_digests.add(digest)
            return validate_receipt(receipt, receipt_name), digest

        controller, controller_digest = consume(run["controller_receipt"], f"{run_name}.controller_receipt")
        _validate_controller(controller, f"{run_name}.controller_receipt")
        writer_outputs: list[dict[str, str]] = []
        for worker_index, worker_ref in enumerate(workers):
            identity, digest = consume(worker_ref, f"{run_name}.worker_receipts[{worker_index}]")
            _validate_writer(identity, f"{run_name}.worker_receipts[{worker_index}]")
            writer_outputs.append(_identity_output(identity, digest))
        output_runs.append({
            "pair_id": pair_id,
            "route": route,
            "controller": _identity_output(controller, controller_digest),
            "workers": writer_outputs,
        })
    for pair_id, routes in pair_routes.items():
        if routes != ROUTES:
            raise IdentityError(f"{pair_id} must contain exactly one run for each route")
    output_runs.sort(key=lambda item: (item["pair_id"], item["route"]))
    content: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "runs": output_runs,
        "verification_status": "verified",
    }
    return {**content, "index_sha256": sha256_bytes(canonical_bytes(content))}


def atomic_write(output: Path, value: Mapping[str, Any]) -> None:
    if output.exists():
        raise IdentityError("output already exists; refusing to overwrite it")
    if not output.parent.is_dir():
        raise IdentityError("output parent directory does not exist")
    temporary: Path | None = None
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=output.parent, prefix=output.name + ".", suffix=".tmp"
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if output.exists():
            raise IdentityError("output appeared during the build; refusing to overwrite it")
        os.replace(temporary, output)
        temporary = None
    except IdentityError:
        raise
    except OSError as exc:
        raise IdentityError(f"cannot atomically write output: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise IdentityError(f"cannot clean temporary output: {exc}") from exc


def build(manifest: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise IdentityError("output already exists; refusing to overwrite it")
    index = build_index(manifest)
    atomic_write(output, index)
    return index


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build a redacted benchmark runtime-identity index.")
    commands = result.add_subparsers(dest="command", required=True)
    build_command = commands.add_parser("build")
    build_command.add_argument("--manifest", required=True, type=Path)
    build_command.add_argument("--output", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        index = build(args.manifest, args.output)
    except IdentityError as exc:
        print(f"benchmark identity error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

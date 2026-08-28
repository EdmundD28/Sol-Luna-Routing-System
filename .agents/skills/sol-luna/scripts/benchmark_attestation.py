#!/usr/bin/env python3
"""Build a deterministic, redacted attestation for a completed benchmark."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
ROUTES = {"SOL_ONLY", "SOL_LUNA"}
CONTROLLER_ROLES = {"default", "worker"}
WRITER_ROLES = {"worker", "luna_worker", "luna_worker_low", "luna_worker_medium", "luna_worker_high", "luna_worker_xhigh", "luna_worker_max"}
CONTRACT_FIELDS = {"schema_version", "campaign_id", "benchmark_contract_digest", "task_spec_digest", "acceptance_suite_digest", "policy_fingerprint", "route_revision", "expected_pairs", "expected_batch_size", "expected_sol_luna_effort", "expected_sol_luna_writer_count"}
INDEX_FIELDS = {"schema_version", "campaign_id", "sol_luna_effort", "sol_luna_writer_count", "runs", "verification_status", "index_sha256"}
RUN_FIELDS = {"pair_id", "route", "controller", "workers"}
IDENTITY_FIELDS = {"model", "effort", "role", "provider", "receipt_sha256"}

class AttestationError(ValueError):
    pass

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()

def _load_campaign() -> Any:
    path = Path(__file__).with_name("allowance_campaign.py")
    spec = importlib.util.spec_from_file_location("benchmark_attestation_allowance_campaign", path)
    if spec is None or spec.loader is None:
        raise AttestationError("cannot load allowance_campaign.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

CAMPAIGN = _load_campaign()

def _exact(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AttestationError(f"{name} must be a JSON object")
    if set(value) != fields:
        raise AttestationError(f"{name} must contain exactly the specified fields")
    return value

def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise AttestationError(f"{name} must be a lowercase sha256 digest")
    return value

def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or any(x in value for x in ("/", "\\")):
        raise AttestationError(f"{name} must be a compact non-path identifier")
    return value

def _positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AttestationError(f"{name} must be a positive integer")
    return value

def _load_json(path: Path, name: str) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AttestationError(f"{name} contains duplicate JSON fields")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise AttestationError(f"{name} contains non-finite JSON number")

    try:
        value = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=reject_duplicates, parse_constant=reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttestationError(f"cannot load {name}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise AttestationError(f"{name} must be a JSON object")
    return value

def _safe_input(path: Path, name: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise AttestationError(f"{name} must be a regular non-symlink file")
    return path

def _validate_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    source = _exact(raw, CONTRACT_FIELDS, "contract")
    if isinstance(source["schema_version"], bool) or not isinstance(source["schema_version"], int) or source["schema_version"] != 1:
        raise AttestationError("contract has unsupported schema_version")
    result = {key: _digest(source[key], key) for key in ("benchmark_contract_digest", "task_spec_digest", "acceptance_suite_digest", "policy_fingerprint")}
    result.update({"campaign_id": _id(source["campaign_id"], "campaign_id"), "route_revision": _id(source["route_revision"], "route_revision")})
    result["expected_pairs"] = _positive(source["expected_pairs"], "expected_pairs")
    result["expected_batch_size"] = _positive(source["expected_batch_size"], "expected_batch_size")
    if not isinstance(source["expected_sol_luna_effort"], str) or source["expected_sol_luna_effort"] not in EFFORTS:
        raise AttestationError("expected_sol_luna_effort is invalid")
    result["expected_sol_luna_effort"] = source["expected_sol_luna_effort"]
    if isinstance(source["expected_sol_luna_writer_count"], bool) or not isinstance(source["expected_sol_luna_writer_count"], int) or source["expected_sol_luna_writer_count"] not in {1, 2}:
        raise AttestationError("expected_sol_luna_writer_count must be 1 or 2")
    result["expected_sol_luna_writer_count"] = source["expected_sol_luna_writer_count"]
    return result

def _validate_identity(raw: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    source = _exact(raw, INDEX_FIELDS, "identity index")
    if isinstance(source["schema_version"], bool) or not isinstance(source["schema_version"], int) or source["schema_version"] != 2 or source["verification_status"] != "verified":
        raise AttestationError("identity index is not verified schema 2")
    if source["campaign_id"] != contract["campaign_id"] or source["sol_luna_effort"] != contract["expected_sol_luna_effort"] or source["sol_luna_writer_count"] != contract["expected_sol_luna_writer_count"]:
        raise AttestationError("identity index does not match contract")
    if not isinstance(source["sol_luna_effort"], str) or source["sol_luna_effort"] not in EFFORTS or isinstance(source["sol_luna_writer_count"], bool) or not isinstance(source["sol_luna_writer_count"], int) or source["sol_luna_writer_count"] not in {1, 2}:
        raise AttestationError("identity index effort or writer count is invalid")
    _digest(source["index_sha256"], "index_sha256")
    content = dict(source); digest = content.pop("index_sha256")
    if sha256_bytes(canonical_bytes(content)) != digest:
        raise AttestationError("identity index digest does not match content")
    if not isinstance(source["runs"], list):
        raise AttestationError("identity index runs must be an array")
    seen_receipts: set[str] = set(); runs: list[dict[str, Any]] = []
    for n, item in enumerate(source["runs"]):
        run = _exact(item, RUN_FIELDS, f"identity runs[{n}]")
        pair = _id(run["pair_id"], f"identity runs[{n}].pair_id")
        if not isinstance(run["route"], str) or run["route"] not in ROUTES: raise AttestationError("identity run has invalid route")
        def identity(value: Any, label: str) -> dict[str, Any]:
            obj = _exact(value, IDENTITY_FIELDS, label)
            for key in ("model", "effort", "role", "provider"): _id(obj[key], f"{label}.{key}")
            digest2 = _digest(obj["receipt_sha256"], f"{label}.receipt_sha256")
            if digest2 in seen_receipts: raise AttestationError("receipt digests must be globally unique")
            seen_receipts.add(digest2)
            return dict(obj)
        controller = identity(run["controller"], f"identity runs[{n}].controller")
        if (controller["model"], controller["effort"], controller["provider"]) != ("gpt-5.6-sol", "high", "openai") or controller["role"] not in CONTROLLER_ROLES:
            raise AttestationError("controller identity is not host-observed gpt-5.6-sol/high OpenAI")
        workers = run["workers"]
        if not isinstance(workers, list) or len(workers) != (0 if run["route"] == "SOL_ONLY" else contract["expected_sol_luna_writer_count"]):
            raise AttestationError("identity worker count does not match route")
        out_workers = []
        for j, worker in enumerate(workers):
            value = identity(worker, f"identity runs[{n}].workers[{j}]")
            if (value["model"], value["effort"], value["provider"]) != ("gpt-5.6-luna", contract["expected_sol_luna_effort"], "openai") or value["role"] not in WRITER_ROLES:
                raise AttestationError("worker identity is not host-observed gpt-5.6-luna")
            out_workers.append(value)
        runs.append({"pair_id": pair, "route": run["route"], "controller": controller, "workers": out_workers})
    return {"index_sha256": digest, "runs": runs}

def build_attestation(campaign_ledger: Path, identity_index: Path, contract: Path) -> dict[str, Any]:
    campaign_ledger, identity_index, contract = (_safe_input(Path(p), name) for p, name in ((campaign_ledger, "campaign ledger"), (identity_index, "identity index"), (contract, "contract")))
    spec = _validate_contract(_load_json(contract, "contract"))
    try: state = CAMPAIGN.replay(campaign_ledger)
    except Exception as exc:
        if isinstance(exc, CAMPAIGN.CampaignError): raise AttestationError(str(exc)) from exc
        raise AttestationError(f"cannot replay campaign: {exc}") from exc
    if state["active"] is not None or len(state["records"]) != spec["expected_pairs"] * 2 or state["config"]["batch_size"] != spec["expected_batch_size"] or state["config"]["contract_digest"] != spec["benchmark_contract_digest"]:
        raise AttestationError("campaign is incomplete or does not match contract")
    records = state["records"]
    for record in records:
        if record["route_revision"] != spec["route_revision"] or record["independent_acceptance"] != "PASSED" or record["defects"] != 0 or record["measurement_scope"] != "ROUTE_TASK_INTERVAL_ONLY" or record["contamination_status"] != "NO_OTHER_SHARED_USAGE_OBSERVED":
            raise AttestationError("campaign record violates attestation requirements")
    pair_routes: dict[str, set[str]] = {}
    for record in records: pair_routes.setdefault(record["pair_id"], set()).add(record["route"])
    if len(pair_routes) != spec["expected_pairs"] or any(routes != ROUTES for routes in pair_routes.values()): raise AttestationError("campaign records do not contain exact route pairs")
    index = _validate_identity(_load_json(identity_index, "identity index"), spec)
    identity_pairs = {(run["pair_id"], run["route"]) for run in index["runs"]}
    if identity_pairs != {(record["pair_id"], record["route"]) for record in records} or len(index["runs"]) != len(records): raise AttestationError("identity runs do not match campaign records")
    windows = state["config"]["windows"]
    last_event = state["last_event_sha256"]
    if not isinstance(last_event, str) or not re.fullmatch(r"[0-9a-f]{64}", last_event):
        raise AttestationError("campaign last event digest is malformed")
    output = {"schema_version": 1, "campaign_id": spec["campaign_id"], "route_revision": spec["route_revision"], "benchmark_contract_digest": spec["benchmark_contract_digest"], "task_spec_digest": spec["task_spec_digest"], "acceptance_suite_digest": spec["acceptance_suite_digest"], "policy_fingerprint": spec["policy_fingerprint"], "completed_pairs": spec["expected_pairs"], "arm_count": len(records), "sol_luna_effort": spec["expected_sol_luna_effort"], "sol_luna_writer_count": spec["expected_sol_luna_writer_count"], "five_hour_window_id": windows["five_hour"]["window_id"], "weekly_window_id": windows["weekly"]["window_id"], "campaign_last_event_sha256": "sha256:" + last_event, "identity_index_sha256": index["index_sha256"], "records_sha256": sha256_bytes(canonical_bytes(records)), "verification_status": "verified"}
    output["attestation_sha256"] = sha256_bytes(canonical_bytes(output))
    return output

def write_attestation(campaign_ledger: Path, identity_index: Path, contract: Path, output: Path) -> dict[str, Any]:
    output = Path(output)
    if output.exists() or output.is_symlink(): raise AttestationError("output already exists; refusing to overwrite it")
    if not output.parent.is_dir(): raise AttestationError("output parent directory does not exist")
    for path in (campaign_ledger, identity_index, contract):
        if output.resolve(strict=False) == Path(path).resolve(strict=False): raise AttestationError("output must differ from inputs")
    value = build_attestation(campaign_ledger, identity_index, contract)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, dir=output.parent, prefix=output.name + ".", suffix=".tmp") as handle:
            temporary = Path(handle.name); handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"); handle.flush(); os.fsync(handle.fileno())
        if output.exists() or output.is_symlink(): raise AttestationError("output appeared during the build; refusing to overwrite it")
        os.replace(temporary, output); temporary = None
    except AttestationError: raise
    except OSError as exc: raise AttestationError(f"cannot atomically write output: {exc}") from exc
    finally:
        if temporary is not None:
            try: temporary.unlink()
            except FileNotFoundError: pass
            except OSError: pass
    return value

def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic benchmark attestation")
    commands = parser.add_subparsers(dest="command", required=True); build = commands.add_parser("build")
    for option in ("campaign-ledger", "identity-index", "contract", "output"): build.add_argument("--" + option, required=True, type=Path)
    args = parser.parse_args()
    try: value = write_attestation(args.campaign_ledger, args.identity_index, args.contract, args.output)
    except AttestationError as exc: print(f"benchmark attestation error: {exc}", file=sys.stderr); return 2
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())

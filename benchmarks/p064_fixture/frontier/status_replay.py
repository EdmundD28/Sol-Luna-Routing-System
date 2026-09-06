from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

try:
    from .frontier_schema import FINGERPRINT, IDENTIFIER, REPAIR_FIELDS, STATUSES, TERMINAL_DEPENDENCY_STATUSES, _repair, canonical_plan
    from .frontier_planner import plan
except ImportError:
    _directory = os.path.dirname(__file__)
    if _directory not in sys.path:
        sys.path.insert(0, _directory)
    from frontier_schema import FINGERPRINT, IDENTIFIER, REPAIR_FIELDS, STATUSES, TERMINAL_DEPENDENCY_STATUSES, _repair, canonical_plan
    from frontier_planner import plan

SCHEMA_VERSION = 1
_SESSION_FIELDS = {"schema_version", "ownership_id", "base_plan", "events", "session_fingerprint"}
_EVENT_FIELDS = {"sequence", "kind", "package_id", "ownership_id"}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

class StatusReplayError(ValueError):
    pass

def _fail(message: Any) -> None:
    raise StatusReplayError(str(message))

def _owner(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail("ownership_id must be a lowercase ASCII identifier")
    return value

def _session_digest(session: Mapping[str, Any]) -> str:
    payload = {key: session[key] for key in ("schema_version", "ownership_id", "base_plan", "events")}
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise StatusReplayError("session contains non-finite or non-JSON data") from error
    return "sha256:" + hashlib.sha256(encoded).hexdigest()

def _copy_plan(base: Mapping[str, Any], packages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "controller_id": base["controller_id"], "writer_cap": base["writer_cap"], "packages": copy.deepcopy(packages)}

def _validate_base(plan_value: Any) -> dict[str, Any]:
    try:
        base = canonical_plan(plan_value)
    except Exception as error:
        raise StatusReplayError(f"invalid base plan: {error}") from error
    if any(package["status"] not in {"PENDING", "ACCEPTED", "RECLAIMED"} for package in base["packages"]):
        _fail("base plan may not contain live package statuses")
    return base

def _validate_session(session: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(session, Mapping) or set(session) != _SESSION_FIELDS:
        _fail("session has invalid fields")
    if type(session["schema_version"]) is not int or session["schema_version"] != SCHEMA_VERSION:
        _fail("invalid session schema_version")
    owner = _owner(session["ownership_id"])
    base = _validate_base(session["base_plan"])
    events = session["events"]
    if not isinstance(events, list):
        _fail("session events must be a list")
    supplied = session["session_fingerprint"]
    if not isinstance(supplied, str) or not _DIGEST.fullmatch(supplied):
        _fail("invalid session fingerprint")
    probe = {"schema_version": 1, "ownership_id": owner, "base_plan": base, "events": copy.deepcopy(events)}
    if _session_digest(probe) != supplied:
        _fail("session fingerprint does not match")
    return base, copy.deepcopy(events)

def _event(value: Any, owner: str, expected_sequence: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("event must be an object")
    if not set(value).issubset(_EVENT_FIELDS | {"failure_evidence_digest", "repair"}):
        _fail("event has unknown fields")
    for key in ("sequence", "kind", "package_id", "ownership_id"):
        if key not in value:
            _fail(f"event missing {key}")
    sequence = value["sequence"]
    if type(sequence) is not int or sequence != expected_sequence:
        _fail("event sequence is invalid")
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in {"START", "HANDOFF", "ACCEPT", "FAIL", "REPAIR", "RECLAIM"}:
        _fail("event kind is invalid")
    package_id = value["package_id"]
    if not isinstance(package_id, str) or not IDENTIFIER.fullmatch(package_id):
        _fail("event package_id is invalid")
    if value["ownership_id"] != owner:
        _fail("event ownership does not match session")
    required = set(_EVENT_FIELDS)
    if kind == "FAIL":
        required |= {"failure_evidence_digest", "repair"}
    elif kind in {"REPAIR", "RECLAIM"}:
        required.add("failure_evidence_digest")
    if set(value) != required:
        _fail("event fields are invalid for kind")
    result = {"sequence": sequence, "kind": kind, "package_id": package_id, "ownership_id": owner}
    if kind in {"FAIL", "REPAIR", "RECLAIM"}:
        digest = value["failure_evidence_digest"]
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            _fail("failure evidence digest is invalid")
        result["failure_evidence_digest"] = digest
    if kind == "FAIL":
        try:
            result["repair"] = _repair(value["repair"], "event.repair")
        except Exception as error:
            raise StatusReplayError(f"invalid repair: {error}") from error
    return result

def _apply(event: dict[str, Any], packages: list[dict[str, Any]], writer_cap: int, budgets: dict[str, dict[str, Any]], seen: set[str], active: dict[str, str], consumed: set[str]) -> None:
    by_id = {package["package_id"]: package for package in packages}
    package_id = event["package_id"]
    if package_id not in by_id:
        _fail("event references unknown package")
    package = by_id[package_id]
    kind = event["kind"]
    if kind == "START":
        if package["status"] != "PENDING" or package["executor"] != "LUNA":
            _fail("package cannot start")
        if any(by_id[dependency]["status"] not in TERMINAL_DEPENDENCY_STATUSES for dependency in package["dependencies"]):
            _fail("dependencies are not terminal")
        if sum(item["status"] == "RUNNING" for item in packages) >= writer_cap:
            _fail("writer cap exceeded")
        package["status"] = "RUNNING"
    elif kind == "HANDOFF":
        if package["status"] != "RUNNING":
            _fail("package is not running")
        package["status"] = "HANDOFF"
    elif kind == "ACCEPT":
        if package["status"] != "HANDOFF":
            _fail("package is not awaiting acceptance")
        package["status"] = "ACCEPTED"
    elif kind == "FAIL":
        if package["status"] != "HANDOFF":
            _fail("package is not awaiting failure decision")
        digest = event["failure_evidence_digest"]
        if digest in seen:
            _fail("failure evidence must be new")
        repair = event["repair"]
        if not repair["new_evidence"] or repair["next_cost_weight"] <= 0 or repair["next_cost_weight"] > repair["remaining_cost_weight"] or repair["marginal_net_substitution"] <= 0:
            _fail("repair is not eligible")
        previous = budgets.get(package_id)
        if previous is None:
            if repair["attempts_used"] != 0:
                _fail("first failure must report zero attempts")
            budgets[package_id] = {"attempts_max": repair["attempts_max"], "remaining": repair["remaining_cost_weight"], "used": 0}
        else:
            if repair["attempts_used"] != previous["used"] or repair["attempts_max"] != previous["attempts_max"] or not math.isclose(repair["remaining_cost_weight"], previous["remaining"], rel_tol=1e-9, abs_tol=1e-9):
                _fail("repair budget was reset")
        package["status"] = "FAILED"
        package["repair"] = repair
        seen.add(digest)
        active[package_id] = digest
    elif kind in {"REPAIR", "RECLAIM"}:
        if package["status"] != "FAILED" or active.get(package_id) != event["failure_evidence_digest"] or event["failure_evidence_digest"] in consumed:
            _fail("failure evidence is not the latest unused evidence")
        digest = event["failure_evidence_digest"]
        if kind == "REPAIR":
            repair = package["repair"]
            if repair["attempts_used"] >= repair["attempts_max"] or repair["next_cost_weight"] <= 0 or repair["next_cost_weight"] > repair["remaining_cost_weight"] or repair["marginal_net_substitution"] <= 0 or not repair["new_evidence"]:
                _fail("repair is not eligible")
            budget = budgets[package_id]
            budget["used"] += 1
            budget["remaining"] -= repair["next_cost_weight"]
            package["status"] = "RUNNING"
            package["repair"] = None
        else:
            package["status"] = "RECLAIMED"
            package["repair"] = None
        consumed.add(digest)
        active.pop(package_id, None)

def _replay(session: Any, extra: Any = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]], set[str], dict[str, str], set[str], list[dict[str, Any]]]:
    base, events = _validate_session(session)
    owner = session["ownership_id"]
    packages = copy.deepcopy(base["packages"])
    budgets: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    active: dict[str, str] = {}
    consumed: set[str] = set()
    normalized_events: list[dict[str, Any]] = []
    for index, raw in enumerate(events, 1):
        event = _event(raw, owner, index)
        _apply(event, packages, base["writer_cap"], budgets, seen, active, consumed)
        normalized_events.append(event)
    if extra is not None:
        event = _event(extra, owner, len(events) + 1)
        _apply(event, packages, base["writer_cap"], budgets, seen, active, consumed)
        normalized_events.append(event)
    return base, packages, budgets, seen, active, consumed, normalized_events

def freeze(plan: Mapping[str, Any], ownership_id: str) -> dict[str, Any]:
    owner = _owner(ownership_id)
    base = _validate_base(plan)
    session = {"schema_version": 1, "ownership_id": owner, "base_plan": base, "events": []}
    session["session_fingerprint"] = _session_digest(session)
    return copy.deepcopy(session)

def transition(session: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    base, packages, _, _, _, _, events = _replay(session, event)
    result = {"schema_version": 1, "ownership_id": session["ownership_id"], "base_plan": copy.deepcopy(base), "events": events}
    result["session_fingerprint"] = _session_digest(result)
    return copy.deepcopy(result)

def project(session: Mapping[str, Any]) -> dict[str, Any]:
    base, packages, _, _, _, _, events = _replay(session)
    current = canonical_plan(_copy_plan(base, packages))
    try:
        frontier = plan(current)
    except Exception as error:
        raise StatusReplayError(f"cannot project session: {error}") from error
    return {"schema_version": 1, "plan": current, "frontier": frontier, "next_sequence": len(events) + 1, "session_fingerprint": session["session_fingerprint"]}

__all__ = ["SCHEMA_VERSION", "StatusReplayError", "freeze", "transition", "project"]

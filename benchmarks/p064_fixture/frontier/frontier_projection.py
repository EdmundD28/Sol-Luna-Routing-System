from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

try:
    from .frontier_schema import FrontierError, RESULT_FIELDS, SCHEMA_VERSION, TERMINAL_DEPENDENCY_STATUSES
except ImportError:
    import os
    import sys
    _directory = os.path.dirname(__file__)
    if _directory not in sys.path:
        sys.path.insert(0, _directory)
    from frontier_schema import FrontierError, RESULT_FIELDS, SCHEMA_VERSION, TERMINAL_DEPENDENCY_STATUSES

def _repair_is_eligible(package: Mapping[str, Any]) -> bool:
    repair = package["repair"]
    return bool(package["executor"] == "LUNA" and package["status"] == "FAILED" and repair["new_evidence"] and repair["attempts_used"] < repair["attempts_max"] and repair["next_cost_weight"] > 0 and repair["next_cost_weight"] <= repair["remaining_cost_weight"] and repair["marginal_net_substitution"] > 0)

def project_normalized(normalized: Mapping[str, Any]) -> dict[str, Any]:
    packages = normalized["packages"]
    package_by_id = {package["package_id"]: package for package in packages}
    def dependency_ready(package: Mapping[str, Any]) -> bool:
        return all(package_by_id[dependency]["status"] in TERMINAL_DEPENDENCY_STATUSES for dependency in package["dependencies"])
    sol_ready: list[str] = []
    blocked: dict[str, list[str]] = {}
    eligible_luna: list[dict[str, Any]] = []
    for package in packages:
        if package["status"] != "PENDING":
            continue
        ready = dependency_ready(package)
        if package["executor"] == "SOL":
            if ready:
                sol_ready.append(package["package_id"])
            else:
                blocked[package["package_id"]] = ["dependency-not-terminal"]
            continue
        reasons = []
        if not ready:
            reasons.append("dependency-not-terminal")
        if package["net_substitution"] <= 0:
            reasons.append("nonpositive-net-substitution")
        if reasons:
            blocked[package["package_id"]] = sorted(reasons)
        else:
            eligible_luna.append(package)
    running_luna = sorted(package["package_id"] for package in packages if package["status"] == "RUNNING")
    review = sorted(package["package_id"] for package in packages if package["status"] == "HANDOFF")
    repair = sorted(package["package_id"] for package in packages if _repair_is_eligible(package))
    luna_envelope = None
    if not repair and len(running_luna) < normalized["writer_cap"] and eligible_luna:
        domains: dict[str, list[dict[str, Any]]] = {}
        for package in eligible_luna:
            domains.setdefault(package["domain_id"], []).append(package)
        rows = []
        for domain_id, domain_packages in domains.items():
            stable = sorted(domain_packages, key=lambda item: item["package_id"])
            total_net = math.fsum(item["net_substitution"] for item in stable)
            total_seconds = math.fsum(item["expected_seconds"] for item in stable)
            if not math.isfinite(total_net) or not math.isfinite(total_seconds):
                raise FrontierError("Luna envelope totals must remain finite")
            rows.append((domain_id, stable, total_net, sum(bool(item["critical_path"]) for item in stable), total_seconds))
        _, domain_packages, total_net, _, total_seconds = min(rows, key=lambda row: (-row[2], -row[3], row[4], row[0]))
        ordered = sorted(domain_packages, key=lambda item: (-int(item["critical_path"]), -item["net_substitution"], item["expected_seconds"], item["package_id"]))
        luna_envelope = {"domain_id": ordered[0]["domain_id"], "package_ids": [package["package_id"] for package in ordered], "total_net_substitution": total_net, "total_expected_seconds": total_seconds}
    result = {"schema_version": SCHEMA_VERSION, "status": "DONE" if all(package["status"] in TERMINAL_DEPENDENCY_STATUSES for package in packages) else "ACTIVE", "plan_fingerprint": normalized["plan_fingerprint"], "luna_envelope": luna_envelope, "sol_ready_package_ids": sorted(sol_ready), "review_package_ids": review, "repair_package_ids": repair, "blocked_package_reasons": {package_id: blocked[package_id] for package_id in sorted(blocked)}, "running_luna_package_ids": running_luna, "tail_wait_allowed": bool(running_luna and luna_envelope is None and not sol_ready and not review and not repair), "automatic_execution_allowed": False}
    if set(result) != RESULT_FIELDS:
        raise FrontierError("planner result schema drifted")
    return result

__all__ = ["project_normalized"]

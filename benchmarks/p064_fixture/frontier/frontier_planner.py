#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

if __package__ in {None, ""}:
    _directory = os.path.dirname(__file__)
    if _directory not in sys.path:
        sys.path.insert(0, _directory)
    from frontier_schema import EXECUTORS, FINGERPRINT, IDENTIFIER, PACKAGE_FIELDS, REPAIR_FIELDS, RESULT_FIELDS, SCHEMA_VERSION, STATUSES, TERMINAL_DEPENDENCY_STATUSES, TOP_FIELDS, TOP_REQUIRED_FIELDS, FrontierError, normalize_plan
    from frontier_projection import project_normalized
else:
    from .frontier_schema import EXECUTORS, FINGERPRINT, IDENTIFIER, PACKAGE_FIELDS, REPAIR_FIELDS, RESULT_FIELDS, SCHEMA_VERSION, STATUSES, TERMINAL_DEPENDENCY_STATUSES, TOP_FIELDS, TOP_REQUIRED_FIELDS, FrontierError, normalize_plan
    from .frontier_projection import project_normalized

def template() -> dict:
    return {"schema_version": 1, "controller_id": "sol-controller", "writer_cap": 1, "packages": [{"package_id": "core-a", "executor": "LUNA", "domain_id": "routing", "dependencies": [], "path_scopes": ["src/core-a"], "acceptance_ids": ["accept-core-a"], "baseline_sol_weight": 8.0, "predicted_executor_weight": 2.0, "incremental_sol_weight": 1.0, "expected_seconds": 120.0, "critical_path": True, "status": "PENDING", "repair": None}]}

def plan(source: dict) -> dict:
    return project_normalized(normalize_plan(source))

__all__ = ["SCHEMA_VERSION", "IDENTIFIER", "FINGERPRINT", "TOP_FIELDS", "TOP_REQUIRED_FIELDS", "PACKAGE_FIELDS", "REPAIR_FIELDS", "EXECUTORS", "STATUSES", "TERMINAL_DEPENDENCY_STATUSES", "RESULT_FIELDS", "FrontierError", "template", "plan"]

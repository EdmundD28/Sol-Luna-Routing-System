from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "closure_contract.py"
SPEC = importlib.util.spec_from_file_location("closure_contract_projection", SCRIPT)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class ClosureProjectionTests(unittest.TestCase):
    @staticmethod
    def digest(n: int) -> str:
        return "sha256:" + format(n, "064x")

    def contract(self) -> dict:
        return {
            "schema_version": 1,
            "envelope": {
                "controller_id": "sol-controller",
                "luna_executor_id": "luna-executor",
                "candidate_start_digest": self.digest(0),
                "repair_budget": {"max_attempts": 2, "max_cost_weight": 2.0},
                "luna_units": [
                    {"unit_id": "core-unit", "path_scopes": ["src"], "acceptance_ids": ["accept-core"], "baseline_weight": 3.0},
                    {"unit_id": "test-unit", "path_scopes": ["tests"], "acceptance_ids": ["accept-tests"], "baseline_weight": 2.0},
                ],
                "sol_lane_units": [
                    {"unit_id": "docs-lane", "path_scopes": ["docs"], "acceptance_ids": ["accept-docs"]},
                ],
            },
            "events": [
                {"sequence": 1, "event": "DISPATCH", "actor_id": "sol-controller", "candidate_digest": self.digest(0)},
            ],
        }

    def handoff(self) -> dict:
        return {
            "sequence": 2,
            "event": "LUNA_HANDOFF",
            "actor_id": "luna-executor",
            "candidate_digest": self.digest(1),
            "changed_paths": ["src/main.py", "tests/test_main.py"],
        }

    def failure(self, *, sequence: int = 3, candidate: int = 1, evidence: int = 5, acceptance_ids: list[str] | None = None) -> dict:
        return {
            "sequence": sequence,
            "event": "SOL_ACCEPTANCE_FAIL",
            "actor_id": "sol-controller",
            "candidate_digest": self.digest(candidate),
            "acceptance_ids": acceptance_ids or ["accept-core"],
            "changed_paths": [],
            "workspace_before_digest": self.digest(evidence + 10),
            "workspace_after_digest": self.digest(evidence + 10),
            "failure_evidence_digest": self.digest(evidence),
        }

    def test_dispatch_projection_is_deterministic_and_does_not_mutate(self) -> None:
        source = self.contract()
        before = copy.deepcopy(source)
        first = CONTRACT.project(source)
        second = CONTRACT.project(source)

        self.assertEqual(source, before)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "IN_PROGRESS")
        self.assertEqual(first["state"], "DISPATCHED")
        self.assertEqual(first["current_candidate_digest"], self.digest(0))
        self.assertEqual(first["next_events"], ["LUNA_HANDOFF", "SOL_PARALLEL_PROGRESS"])
        self.assertEqual(first["remaining_repair_attempts"], 2)
        self.assertEqual(first["remaining_repair_cost_weight"], 2.0)
        self.assertFalse(first["automatic_execution_allowed"])

        without_sol_lane = copy.deepcopy(source)
        without_sol_lane["envelope"]["sol_lane_units"] = []
        self.assertEqual(CONTRACT.project(without_sol_lane)["next_events"], ["LUNA_HANDOFF"])

        source["contract_fingerprint"] = first["contract_fingerprint"]
        self.assertEqual(CONTRACT.project(source)["contract_fingerprint"], first["contract_fingerprint"])
        source["contract_fingerprint"] = self.digest(9)
        with self.assertRaisesRegex(CONTRACT.ContractError, "fingerprint"):
            CONTRACT.project(source)

    def test_handoff_and_closed_contract_projection(self) -> None:
        source = self.contract()
        source["events"].append(self.handoff())
        awaiting = CONTRACT.project(source)
        self.assertEqual(awaiting["state"], "AWAITING_ACCEPTANCE")
        self.assertEqual(
            awaiting["next_events"],
            ["SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS", "SOL_PARALLEL_PROGRESS"],
        )

        source["events"].extend([
            {
                "sequence": 3,
                "event": "SOL_ACCEPTANCE_PASS",
                "actor_id": "sol-controller",
                "candidate_digest": self.digest(1),
                "acceptance_ids": ["accept-core", "accept-tests"],
                "changed_paths": [],
                "workspace_before_digest": self.digest(2),
                "workspace_after_digest": self.digest(2),
                "result_digest": self.digest(3),
            },
        ])
        accepted = CONTRACT.project(source)
        self.assertEqual(accepted["state"], "ACCEPTED_CANDIDATE")
        self.assertEqual(accepted["accepted_luna_unit_ids"], ["core-unit", "test-unit"])
        self.assertEqual(accepted["next_events"], ["CLOSE"])

        source["events"].append({
            "sequence": 4,
            "event": "CLOSE",
            "actor_id": "sol-controller",
            "candidate_digest": self.digest(1),
            "unit_dispositions": [
                {"unit_id": "test-unit", "status": "accepted"},
                {"unit_id": "core-unit", "status": "accepted"},
            ],
        })
        closed = CONTRACT.project(source)
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(closed["state"], "CLOSED")
        self.assertEqual(closed["next_events"], [])
        self.assertEqual(CONTRACT.assess(source)["status"], "ACCEPTED")

    def test_failed_acceptance_and_open_repair_are_exact(self) -> None:
        source = self.contract()
        source["events"].extend([self.handoff(), self.failure()])
        failed = CONTRACT.project(source)
        self.assertEqual(failed["state"], "FAILED")
        self.assertEqual(failed["failure_evidence_digest"], self.digest(5))
        self.assertEqual(failed["affected_luna_unit_ids"], ["core-unit"])
        self.assertEqual(failed["next_events"], ["OPEN_LUNA_REPAIR", "SOL_RECLAIM"])

        source["events"].append({
            "sequence": 4,
            "event": "OPEN_LUNA_REPAIR",
            "actor_id": "sol-controller",
            "candidate_digest": self.digest(1),
            "failure_evidence_digest": self.digest(5),
            "target_unit_ids": ["core-unit"],
            "repair_cost_weight": 0.5,
            "marginal_net_substitution": 1.0,
        })
        repairing = CONTRACT.project(source)
        self.assertEqual(repairing["state"], "REPAIR_OPEN")
        self.assertEqual(repairing["open_repair_target_unit_ids"], ["core-unit"])
        self.assertEqual(repairing["next_events"], ["LUNA_REPAIR_HANDOFF"])

        source["events"][-1]["candidate_digest"] = self.digest(8)
        with self.assertRaisesRegex(CONTRACT.ContractError, "current failed candidate"):
            CONTRACT.project(source)

    def test_parallel_progress_rejected_after_failure(self) -> None:
        source = self.contract()
        source["events"].extend([self.handoff(), self.failure(), {
            "sequence": 4,
            "event": "SOL_PARALLEL_PROGRESS",
            "actor_id": "sol-controller",
            "candidate_digest": self.digest(1),
            "changed_paths": ["docs/progress.md"],
            "workspace_before_digest": self.digest(6),
            "workspace_after_digest": self.digest(7),
            "progress_digest": self.digest(8),
        }])
        with self.assertRaisesRegex(CONTRACT.ContractError, "awaits handoff or acceptance"):
            CONTRACT.project(source)

    def test_exhausted_budget_and_tolerance_residue(self) -> None:
        source = self.contract()
        source["envelope"]["repair_budget"] = {"max_attempts": 1, "max_cost_weight": 0.3}
        source["events"].extend([self.handoff(), self.failure(), {
            "sequence": 4,
            "event": "OPEN_LUNA_REPAIR",
            "actor_id": "sol-controller",
            "candidate_digest": self.digest(1),
            "failure_evidence_digest": self.digest(5),
            "target_unit_ids": ["core-unit"],
            "repair_cost_weight": 0.30000000000000004,
            "marginal_net_substitution": 1.0,
        }])
        repairing = CONTRACT.project(source)
        self.assertEqual(repairing["remaining_repair_attempts"], 0)
        self.assertEqual(repairing["remaining_repair_cost_weight"], 0.0)

        source["events"].extend([
            {
                "sequence": 5,
                "event": "LUNA_REPAIR_HANDOFF",
                "actor_id": "luna-executor",
                "candidate_digest": self.digest(7),
                "target_unit_ids": ["core-unit"],
                "changed_paths": ["src/fix.py"],
            },
            self.failure(sequence=6, candidate=7, evidence=9),
        ])
        failed = CONTRACT.project(source)
        self.assertEqual(failed["next_events"], ["SOL_RECLAIM"])
        self.assertGreaterEqual(failed["remaining_repair_cost_weight"], 0.0)

    def test_partial_reclaim_projection(self) -> None:
        source = self.contract()
        source["events"].extend([self.handoff(), self.failure(), {
            "sequence": 4,
            "event": "SOL_RECLAIM",
            "actor_id": "sol-controller",
            "candidate_digest": self.digest(7),
            "unit_ids": ["core-unit"],
            "changed_paths": ["src/reclaim.py"],
            "reason_digest": self.digest(6),
        }])
        reclaimed = CONTRACT.project(source)
        self.assertEqual(reclaimed["state"], "RECLAIMED")
        self.assertEqual(reclaimed["reclaimed_luna_unit_ids"], ["core-unit"])
        self.assertEqual(reclaimed["next_events"], ["SOL_ACCEPTANCE_FAIL", "SOL_ACCEPTANCE_PASS"])

    def test_project_cli_and_complete_validator_boundary(self) -> None:
        source = self.contract()
        with self.assertRaisesRegex(CONTRACT.ContractError, "not closed"):
            CONTRACT.validate(source)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "prefix.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            completed = subprocess.run(
                [__import__("sys").executable, str(SCRIPT), "project", "--input", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["state"], "DISPATCHED")


if __name__ == "__main__":
    unittest.main()

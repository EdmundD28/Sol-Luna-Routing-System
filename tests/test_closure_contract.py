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
SPEC = importlib.util.spec_from_file_location("closure_contract", SCRIPT)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class ClosureContractTests(unittest.TestCase):
    z = "sha256:" + "0" * 64

    def contract(self, *, two_units: bool = False) -> dict:
        units = [{"unit_id": "core-unit", "path_scopes": ["src"], "acceptance_ids": ["accept-core"], "baseline_weight": 3.0}]
        if two_units:
            units.append({"unit_id": "test-unit", "path_scopes": ["tests"], "acceptance_ids": ["accept-tests"], "baseline_weight": 2.0})
        events = [
            {"sequence": 1, "event": "DISPATCH", "actor_id": "sol-controller", "candidate_digest": self.z},
            {"sequence": 2, "event": "LUNA_HANDOFF", "actor_id": "luna-executor", "candidate_digest": self.digest(1), "changed_paths": ["src/main.py"]},
        ]
        if two_units:
            events[1]["changed_paths"] = ["src/main.py", "tests/test_main.py"]
        events.extend([
            {"sequence": 3, "event": "SOL_ACCEPTANCE_PASS", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": [u["acceptance_ids"][0] for u in units], "changed_paths": [], "workspace_before_digest": self.digest(2), "workspace_after_digest": self.digest(2), "result_digest": self.digest(3)},
            {"sequence": 4, "event": "CLOSE", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "unit_dispositions": [{"unit_id": u["unit_id"], "status": "accepted"} for u in units]},
        ])
        return {"schema_version": 1, "envelope": {"controller_id": "sol-controller", "luna_executor_id": "luna-executor", "candidate_start_digest": self.z, "repair_budget": {"max_attempts": 2, "max_cost_weight": 2.0}, "luna_units": units, "sol_lane_units": [{"unit_id": "docs-lane", "path_scopes": ["docs"], "acceptance_ids": ["accept-docs"]}]}, "events": events}

    @staticmethod
    def digest(n: int) -> str:
        return "sha256:" + format(n, "x") * 64

    def test_clean_template_and_no_repair(self) -> None:
        source = CONTRACT.template()
        self.assertEqual(CONTRACT.assess(source)["status"], "ACCEPTED")
        self.assertRegex(source["contract_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(CONTRACT.validate(source)["contract_fingerprint"], source["contract_fingerprint"])

    def test_two_round_same_luna_repair(self) -> None:
        c = self.contract()
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "failure_evidence_digest": self.digest(5), "target_unit_ids": ["core-unit"], "repair_cost_weight": 0.5, "marginal_net_substitution": 1.0},
            {"sequence": 5, "event": "LUNA_REPAIR_HANDOFF", "actor_id": "luna-executor", "candidate_digest": self.digest(7), "target_unit_ids": ["core-unit"], "changed_paths": ["src/fix.py"]},
            {"sequence": 6, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(7), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(8), "workspace_after_digest": self.digest(8), "failure_evidence_digest": self.digest(9)},
            {"sequence": 7, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(7), "failure_evidence_digest": self.digest(9), "target_unit_ids": ["core-unit"], "repair_cost_weight": 0.5, "marginal_net_substitution": 1.0},
            {"sequence": 8, "event": "LUNA_REPAIR_HANDOFF", "actor_id": "luna-executor", "candidate_digest": self.digest(11), "target_unit_ids": ["core-unit"], "changed_paths": ["src/fix2.py"]},
            {"sequence": 9, "event": "SOL_ACCEPTANCE_PASS", "actor_id": "sol-controller", "candidate_digest": self.digest(11), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(12), "workspace_after_digest": self.digest(12), "result_digest": self.digest(13)},
            {"sequence": 10, "event": "CLOSE", "actor_id": "sol-controller", "candidate_digest": self.digest(11), "unit_dispositions": [{"unit_id": "core-unit", "status": "accepted"}]},
        ]
        c["contract_fingerprint"] = CONTRACT.contract_fingerprint(c)
        result = CONTRACT.assess(c)
        self.assertEqual(result["repair_attempts"], 2)
        self.assertEqual(result["repair_cost_weight"], 1.0)

    def test_budget_and_evidence_and_unchanged_candidate_rejected(self) -> None:
        c = self.contract()
        c["events"] = c["events"][:2] + [{"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)}, {"sequence": 4, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "failure_evidence_digest": self.digest(6), "target_unit_ids": ["core-unit"], "repair_cost_weight": 1.0, "marginal_net_substitution": 1.0}]
        with self.assertRaisesRegex(CONTRACT.ContractError, "latest unused"):
            CONTRACT.assess(c)
        c = self.contract()
        c["events"] = c["events"][:2] + [{"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)}, {"sequence": 4, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "failure_evidence_digest": self.digest(5), "target_unit_ids": ["core-unit"], "repair_cost_weight": 1.0, "marginal_net_substitution": 1.0}, {"sequence": 5, "event": "LUNA_REPAIR_HANDOFF", "actor_id": "luna-executor", "candidate_digest": self.digest(1), "target_unit_ids": ["core-unit"], "changed_paths": ["src/fix.py"]}]
        with self.assertRaisesRegex(CONTRACT.ContractError, "candidate_digest"):
            CONTRACT.assess(c)

    def test_third_attempt_cost_and_nonpositive_marginal_rejected(self) -> None:
        c = self.contract()
        c["envelope"]["repair_budget"] = {"max_attempts": 1, "max_cost_weight": 0.5}
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "failure_evidence_digest": self.digest(5), "target_unit_ids": ["core-unit"], "repair_cost_weight": 1.0, "marginal_net_substitution": 1.0},
        ]
        with self.assertRaisesRegex(CONTRACT.ContractError, "cost budget"):
            CONTRACT.assess(c)
        c = self.contract()
        c["envelope"]["repair_budget"]["max_attempts"] = 1
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "failure_evidence_digest": self.digest(6), "target_unit_ids": ["core-unit"], "repair_cost_weight": 0.5, "marginal_net_substitution": 0.0},
        ]
        with self.assertRaisesRegex(CONTRACT.ContractError, "finite positive"):
            CONTRACT.assess(c)

        c = self.contract()
        c["envelope"]["repair_budget"]["max_attempts"] = 1
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(5), "failure_evidence_digest": self.digest(5), "target_unit_ids": ["core-unit"], "repair_cost_weight": 0.5, "marginal_net_substitution": 1.0},
            {"sequence": 5, "event": "LUNA_REPAIR_HANDOFF", "actor_id": "luna-executor", "candidate_digest": self.digest(7), "target_unit_ids": ["core-unit"], "changed_paths": ["src/fix.py"]},
            {"sequence": 6, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(7), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(8), "workspace_after_digest": self.digest(8), "failure_evidence_digest": self.digest(9)},
            {"sequence": 7, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(7), "failure_evidence_digest": self.digest(9), "target_unit_ids": ["core-unit"], "repair_cost_weight": 0.5, "marginal_net_substitution": 1.0},
        ]
        with self.assertRaisesRegex(CONTRACT.ContractError, "attempt budget"):
            CONTRACT.assess(c)

    def test_read_only_sol_and_path_guards(self) -> None:
        c = self.contract()
        c["events"][2]["changed_paths"] = ["src/sol-edit.py"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "read-only"):
            CONTRACT.assess(c)
        c = self.contract()
        c["envelope"]["sol_lane_units"][0]["path_scopes"] = ["src"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "overlap"):
            CONTRACT.assess(c)
        c = self.contract()
        c["events"].insert(1, {"sequence": 2, "event": "SOL_PARALLEL_PROGRESS", "actor_id": "sol-controller", "candidate_digest": self.z, "changed_paths": ["src/bad.py"], "workspace_before_digest": self.digest(2), "workspace_after_digest": self.digest(2), "progress_digest": self.digest(3)})
        for i, event in enumerate(c["events"], 1):
            event["sequence"] = i
        with self.assertRaisesRegex(CONTRACT.ContractError, "sol_lane"):
            CONTRACT.assess(c)
        c = self.contract()
        c["events"].insert(1, {"sequence": 2, "event": "SOL_PARALLEL_PROGRESS", "actor_id": "sol-controller", "candidate_digest": self.z, "changed_paths": ["docs/progress.md"], "workspace_before_digest": self.digest(2), "workspace_after_digest": self.digest(2), "progress_digest": self.digest(3)})
        for i, event in enumerate(c["events"], 1):
            event["sequence"] = i
        with self.assertRaisesRegex(CONTRACT.ContractError, "actual workspace change"):
            CONTRACT.assess(c)
        c = self.contract()
        c["events"][1]["changed_paths"] = ["src\\bad.py"]
        with self.assertRaises(CONTRACT.ContractError):
            CONTRACT.assess(c)
        c = self.contract()
        c["envelope"]["luna_units"][0]["path_scopes"] = ["src", "src/sub"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "overlap"):
            CONTRACT.assess(c)

    def test_delivery_and_repair_targets_are_bound_to_responsibility_units(self) -> None:
        c = self.contract(two_units=True)
        c["events"][1]["changed_paths"] = ["src/main.py"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "cover every delegated Luna unit"):
            CONTRACT.assess(c)

        c = self.contract(two_units=True)
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "OPEN_LUNA_REPAIR", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "failure_evidence_digest": self.digest(5), "target_unit_ids": ["test-unit"], "repair_cost_weight": 0.5, "marginal_net_substitution": 1.0},
        ]
        with self.assertRaisesRegex(CONTRACT.ContractError, "bound to the failed acceptance"):
            CONTRACT.assess(c)

    def test_failure_evidence_cannot_be_reused_after_reclaim(self) -> None:
        c = self.contract(two_units=True)
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "SOL_RECLAIM", "actor_id": "sol-controller", "candidate_digest": self.digest(14), "unit_ids": ["core-unit"], "changed_paths": ["src/reclaim.py"], "reason_digest": self.digest(6)},
            {"sequence": 5, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(14), "acceptance_ids": ["accept-tests"], "changed_paths": [], "workspace_before_digest": self.digest(7), "workspace_after_digest": self.digest(7), "failure_evidence_digest": self.digest(5)},
        ]
        with self.assertRaisesRegex(CONTRACT.ContractError, "new for each failed candidate"):
            CONTRACT.assess(c)

    def test_close_requires_terminal_dispositions(self) -> None:
        c = self.contract()
        c["events"] = c["events"][:-1]
        with self.assertRaisesRegex(CONTRACT.ContractError, "not closed"):
            CONTRACT.assess(c)
        c = self.contract()
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "SOL_RECLAIM", "actor_id": "sol-controller", "candidate_digest": self.digest(14), "unit_ids": ["core-unit"], "changed_paths": ["src/reclaim.py"], "reason_digest": self.digest(6)},
            {"sequence": 5, "event": "CLOSE", "actor_id": "sol-controller", "candidate_digest": self.digest(14), "unit_dispositions": [{"unit_id": "core-unit", "status": "reclaimed"}]},
        ]
        with self.assertRaisesRegex(CONTRACT.ContractError, "independent acceptance pass"):
            CONTRACT.assess(c)

    def test_partial_reclaim_shadows_only_one_weight(self) -> None:
        c = self.contract(two_units=True)
        c["events"] = c["events"][:2] + [
            {"sequence": 3, "event": "SOL_ACCEPTANCE_FAIL", "actor_id": "sol-controller", "candidate_digest": self.digest(1), "acceptance_ids": ["accept-core", "accept-tests"], "changed_paths": [], "workspace_before_digest": self.digest(4), "workspace_after_digest": self.digest(4), "failure_evidence_digest": self.digest(5)},
            {"sequence": 4, "event": "SOL_RECLAIM", "actor_id": "sol-controller", "candidate_digest": self.digest(14), "unit_ids": ["core-unit"], "changed_paths": ["src/reclaim.py"], "reason_digest": self.digest(6)},
            {"sequence": 5, "event": "SOL_ACCEPTANCE_PASS", "actor_id": "sol-controller", "candidate_digest": self.digest(14), "acceptance_ids": ["accept-tests"], "changed_paths": [], "workspace_before_digest": self.digest(7), "workspace_after_digest": self.digest(7), "result_digest": self.digest(8)},
            {"sequence": 6, "event": "CLOSE", "actor_id": "sol-controller", "candidate_digest": self.digest(14), "unit_dispositions": [{"unit_id": "core-unit", "status": "reclaimed"}, {"unit_id": "test-unit", "status": "accepted"}]},
        ]
        result = CONTRACT.assess(c)
        self.assertEqual(result["accepted_luna_baseline_weight"], 2.0)
        self.assertEqual(result["shadowed_luna_baseline_weight"], 3.0)

    def test_close_unknown_duplicate_nan_and_cli(self) -> None:
        c = self.contract()
        c["events"][-1]["unit_dispositions"] = []
        with self.assertRaises(CONTRACT.ContractError):
            CONTRACT.assess(c)
        c = self.contract()
        c["unexpected"] = True
        with self.assertRaises(CONTRACT.ContractError):
            CONTRACT.assess(c)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            for text in ('{"schema_version":1,"schema_version":1}', '{"schema_version":NaN}'):
                path.write_text(text, encoding="utf-8")
                completed = subprocess.run([__import__("sys").executable, str(SCRIPT), "assess", "--input", str(path)], capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(len(completed.stderr.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()

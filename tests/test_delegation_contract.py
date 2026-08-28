from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "delegation_contract.py"
SPEC = importlib.util.spec_from_file_location("delegation_contract", SCRIPT)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class DelegationContractTests(unittest.TestCase):
    digest = "sha256:" + "1" * 64

    def _contract(self) -> dict:
        result = {
            "schema_version": 1,
            "route": "SOL_LUNA",
            "task_digest": self.digest,
            "allocation_digest": "sha256:" + "0" * 64,
            "executor_id": "luna-one",
            "worker_context_id": "context-one",
            "envelope": {
                "write_scope": ["src", "tests"],
                "acceptance_ids": ["accept-core", "accept-tests"],
                "replacement_scope": ["repo_read", "implementation", "targeted_test", "closeout"],
                "units": [
                    {
                        "unit_id": "tests-work",
                        "depends_on": ["core-work"],
                        "changed_paths": ["tests/test_core.py"],
                        "replacement_actions": [
                            {"action_id": "run-tests", "kind": "targeted_test"},
                        ],
                    },
                    {
                        "unit_id": "core-work",
                        "depends_on": [],
                        "changed_paths": ["src/core.py"],
                        "replacement_actions": [
                            {"action_id": "read-core", "kind": "repo_read"},
                            {"action_id": "implement-core", "kind": "implementation"},
                            {"action_id": "close-core", "kind": "closeout"},
                        ],
                    },
                ],
            },
            "handoff": {
                "candidate_digest": self.digest,
                "changed_paths": ["src/core.py", "tests/test_core.py"],
                "acceptance_results": [
                    {
                        "acceptance_id": "accept-core",
                        "candidate_digest": self.digest,
                        "command_digest": "sha256:" + "3" * 64,
                        "result_digest": "sha256:" + "4" * 64,
                        "exit_code": 0,
                        "deterministic": True,
                    },
                    {
                        "acceptance_id": "accept-tests",
                        "candidate_digest": self.digest,
                        "command_digest": "sha256:" + "5" * 64,
                        "result_digest": "sha256:" + "6" * 64,
                        "exit_code": 0,
                        "deterministic": True,
                    },
                ],
                "closeout_complete": True,
                "residual_risks": [],
            },
            "sol_verification": {
                "candidate_digest": self.digest,
                "independent_acceptance_digest": "sha256:" + "7" * 64,
                "independent_acceptance_passed": True,
                "accepted_unit_ids": ["core-work", "tests-work"],
                "replays": [],
            },
        }
        result["allocation_digest"] = CONTRACT.allocation_fingerprint(result)
        return result

    def _assess(self, candidate: dict | None = None) -> dict:
        return CONTRACT.assess(candidate or self._contract())

    def test_accepts_multiple_units_in_dependency_order_independent_input(self) -> None:
        result = self._assess()
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(result["unit_count"], 2)
        self.assertEqual(result["handoff_count"], 1)
        self.assertEqual(result["context_reload_count"], 1)
        self.assertEqual(result["replacement_action_count"], 4)
        self.assertEqual(result["replacement_kind_count"], 4)
        self.assertEqual(result["avoided_sol_action_count"], 4)
        self.assertEqual(result["sol_shadow_action_count"], 0)
        self.assertEqual(result["avoided_sol_kind_count"], 4)
        self.assertEqual(result["sol_shadow_kind_count"], 0)
        self.assertEqual(result["substitution_fraction"], 1.0)
        self.assertEqual(result["verification_reuse_fraction"], 1.0)

    def test_replay_actions_reduce_substitution_metrics(self) -> None:
        candidate = self._contract()
        candidate["sol_verification"]["replays"] = [
            {"action_id": "implement-core", "reason": "discrepancy"},
            {"action_id": "run-tests", "reason": "nondeterminism"},
        ]
        result = self._assess(candidate)
        self.assertEqual(result["avoided_sol_action_count"], 2)
        self.assertEqual(result["sol_shadow_action_count"], 2)
        self.assertEqual(result["avoided_sol_kind_count"], 2)
        self.assertEqual(result["sol_shadow_kind_count"], 2)
        self.assertEqual(result["substitution_fraction"], 0.5)
        self.assertEqual(result["verification_reuse_fraction"], 0.5)
        self.assertEqual(
            [item["action_id"] for item in result["replayed_actions"]],
            ["implement-core", "run-tests"],
        )

    def test_substitution_is_conservative_per_frozen_kind(self) -> None:
        candidate = self._contract()
        candidate["envelope"]["units"][1]["replacement_actions"].append(
            {"action_id": "read-extra", "kind": "repo_read"}
        )
        result = self._assess(candidate)
        self.assertEqual(result["replacement_action_count"], 5)
        self.assertEqual(result["replacement_kind_count"], 4)
        self.assertEqual(result["substitution_fraction"], 1.0)
        candidate["sol_verification"]["replays"] = [
            {"action_id": "read-core", "reason": "discrepancy"}
        ]
        result = self._assess(candidate)
        self.assertEqual(result["sol_shadow_kind_count"], 1)
        self.assertEqual(result["avoided_sol_kind_count"], 3)
        self.assertEqual(result["substitution_fraction"], 0.75)

    def test_allocation_digest_binds_only_frozen_outer_fields(self) -> None:
        for field, value in (
            ("schema_version", 2),
            ("route", "SOL_ONLY"),
            ("task_digest", "sha256:" + "8" * 64),
            ("executor_id", "luna-two"),
            ("worker_context_id", "context-two"),
        ):
            candidate = self._contract()
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(CONTRACT.ContractError):
                self._assess(candidate)
        for field, value in (
            ("write_scope", ["src", "docs"]),
            ("acceptance_ids", ["accept-core", "accept-other"]),
            ("replacement_scope", ["repo_read", "implementation", "targeted_test"]),
        ):
            candidate = self._contract()
            candidate["envelope"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(CONTRACT.ContractError, "allocation_digest"):
                self._assess(candidate)
        candidate = self._contract()
        candidate["envelope"]["units"] = list(reversed(candidate["envelope"]["units"]))
        self.assertEqual(self._assess(candidate)["status"], "ACCEPTED")
        candidate["envelope"]["units"][0]["replacement_actions"].append(
            {"action_id": "read-internal", "kind": "repo_read"}
        )
        self.assertEqual(self._assess(candidate)["status"], "ACCEPTED")

    def test_replacement_scope_is_nonempty_unique_and_complete(self) -> None:
        for value in ([], ["repo_read", "repo_read"], ["repo_read", "unknown"]):
            candidate = self._contract()
            candidate["envelope"]["replacement_scope"] = value
            with self.subTest(value=value), self.assertRaises(CONTRACT.ContractError):
                self._assess(candidate)
        candidate = self._contract()
        candidate["envelope"]["replacement_scope"] = ["repo_read", "implementation", "targeted_test"]
        candidate["allocation_digest"] = CONTRACT.allocation_fingerprint(candidate)
        with self.assertRaisesRegex(CONTRACT.ContractError, "cover replacement_scope"):
            self._assess(candidate)

    def test_more_units_do_not_automatically_increase_substitution(self) -> None:
        candidate = self._contract()
        candidate["envelope"]["units"].append({
            "unit_id": "docs-work", "depends_on": [], "changed_paths": [],
            "replacement_actions": [{"action_id": "read-docs", "kind": "repo_read"}],
        })
        candidate["sol_verification"]["accepted_unit_ids"].append("docs-work")
        result = self._assess(candidate)
        self.assertEqual(result["substitution_fraction"], 1.0)
        self.assertEqual(result["replacement_action_count"], 5)

    def test_zero_actions_fail(self) -> None:
        candidate = self._contract()
        for unit in candidate["envelope"]["units"]:
            unit["replacement_actions"] = []
        with self.assertRaisesRegex(CONTRACT.ContractError, "at least one"):
            self._assess(candidate)

    def test_duplicate_action_ids_fail(self) -> None:
        candidate = self._contract()
        candidate["envelope"]["units"][0]["replacement_actions"][0]["action_id"] = "read-core"
        with self.assertRaisesRegex(CONTRACT.ContractError, "duplicate action_id"):
            self._assess(candidate)

    def test_candidate_mismatch_and_stale_acceptance_fail(self) -> None:
        for field in ("handoff", "sol_verification"):
            candidate = self._contract()
            candidate[field]["candidate_digest"] = "sha256:" + "8" * 64
            with self.subTest(field=field), self.assertRaises(CONTRACT.ContractError):
                self._assess(candidate)
        candidate = self._contract()
        candidate["handoff"]["acceptance_results"][0]["candidate_digest"] = "sha256:" + "8" * 64
        with self.assertRaisesRegex(CONTRACT.ContractError, "stale"):
            self._assess(candidate)

    def test_missing_duplicate_and_unknown_acceptance_fail(self) -> None:
        candidate = self._contract()
        candidate["handoff"]["acceptance_results"] = candidate["handoff"]["acceptance_results"][:1]
        with self.assertRaisesRegex(CONTRACT.ContractError, "exactly once"):
            self._assess(candidate)
        candidate = self._contract()
        candidate["handoff"]["acceptance_results"].append(copy.deepcopy(candidate["handoff"]["acceptance_results"][0]))
        with self.assertRaisesRegex(CONTRACT.ContractError, "more than once"):
            self._assess(candidate)
        candidate = self._contract()
        candidate["handoff"]["acceptance_results"][0]["acceptance_id"] = "unknown"
        with self.assertRaisesRegex(CONTRACT.ContractError, "unknown acceptance"):
            self._assess(candidate)

    def test_nonzero_exit_and_nondeterministic_acceptance_fail(self) -> None:
        for field, value in (("exit_code", 7), ("deterministic", False)):
            candidate = self._contract()
            candidate["handoff"]["acceptance_results"][0][field] = value
            with self.subTest(field=field), self.assertRaises(CONTRACT.ContractError):
                self._assess(candidate)

    def test_envelope_and_changed_path_union_are_strict(self) -> None:
        candidate = self._contract()
        candidate["envelope"]["units"][0]["changed_paths"] = ["outside/file.py"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "exceed envelope"):
            self._assess(candidate)
        candidate = self._contract()
        candidate["handoff"]["changed_paths"] = ["src/core.py"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "union"):
            self._assess(candidate)

    def test_missing_dependency_and_cycle_fail(self) -> None:
        candidate = self._contract()
        candidate["envelope"]["units"][0]["depends_on"] = ["missing"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "unknown dependencies"):
            self._assess(candidate)
        candidate = self._contract()
        candidate["envelope"]["units"][0]["depends_on"] = ["core-work"]
        candidate["envelope"]["units"][1]["depends_on"] = ["tests-work"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "cycle"):
            self._assess(candidate)

    def test_closeout_independent_acceptance_and_accepted_units_are_gates(self) -> None:
        candidate = self._contract()
        candidate["handoff"]["closeout_complete"] = False
        with self.assertRaises(CONTRACT.ContractError):
            self._assess(candidate)
        candidate = self._contract()
        candidate["sol_verification"]["independent_acceptance_passed"] = False
        with self.assertRaises(CONTRACT.ContractError):
            self._assess(candidate)
        candidate = self._contract()
        candidate["sol_verification"]["accepted_unit_ids"] = ["core-work"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "every unit"):
            self._assess(candidate)

    def test_replays_must_be_unique_delivered_and_reasoned(self) -> None:
        for replay in (
            {"action_id": "missing", "reason": "discrepancy"},
            {"action_id": "read-core", "reason": "other"},
            {"action_id": "read-core", "reason": "discrepancy"},
        ):
            candidate = self._contract()
            candidate["sol_verification"]["replays"] = [replay, replay.copy()] if replay["action_id"] == "read-core" and replay["reason"] == "discrepancy" else [replay]
            with self.subTest(replay=replay), self.assertRaises(CONTRACT.ContractError):
                self._assess(candidate)

    def test_unknown_fields_types_and_path_forms_fail(self) -> None:
        candidate = self._contract()
        candidate["unexpected"] = True
        with self.assertRaises(CONTRACT.ContractError):
            self._assess(candidate)
        for bad_path in (
            "src\\core.py", "/etc/passwd", "src/../secret", ".", "src/./core.py",
            "src//core.py", "src/", "src/.ssh/key", "CON.txt", "docs/PRN.md",
            "src/file.", "src/name ", "com1.log", "LPT9.txt", "src:core.py",
        ):
            candidate = self._contract()
            candidate["envelope"]["units"][1]["changed_paths"] = [bad_path]
            with self.subTest(bad_path=bad_path), self.assertRaises(CONTRACT.ContractError):
                self._assess(candidate)
        candidate = self._contract()
        candidate["executor_id"] = []
        with self.assertRaises(CONTRACT.ContractError):
            self._assess(candidate)
        candidate = self._contract()
        candidate["envelope"]["write_scope"] = ["src", "SRC"]
        with self.assertRaises(CONTRACT.ContractError):
            self._assess(candidate)
        candidate = self._contract()
        candidate["envelope"]["write_scope"] = ["src", "SRC/core.py"]
        with self.assertRaises(CONTRACT.ContractError):
            self._assess(candidate)
        candidate = self._contract()
        candidate["envelope"]["write_scope"] = ["SRC", "tests"]
        candidate["allocation_digest"] = CONTRACT.allocation_fingerprint(candidate)
        self.assertEqual(self._assess(candidate)["status"], "ACCEPTED")
        candidate = self._contract()
        candidate[1] = True
        with self.assertRaisesRegex(CONTRACT.ContractError, "keys must be strings"):
            self._assess(candidate)

    def test_cli_template_and_malformed_json_are_single_line_errors(self) -> None:
        template = subprocess.run(
            [sys.executable, str(SCRIPT), "template"], check=False, capture_output=True, text=True
        )
        self.assertEqual(template.returncode, 0, template.stderr)
        template_payload = json.loads(template.stdout)
        self.assertEqual(template_payload["schema_version"], 1)
        self.assertEqual(
            template_payload["allocation_digest"], CONTRACT.allocation_fingerprint(template_payload)
        )
        self.assertEqual(CONTRACT.assess(template_payload)["status"], "ACCEPTED")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            for payload in ('{"schema_version":1,"schema_version":1}', '{"schema_version":NaN}'):
                path.write_text(payload, encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), "assess", "--input", str(path)],
                    check=False, capture_output=True, text=True,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertEqual(len(completed.stderr.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()

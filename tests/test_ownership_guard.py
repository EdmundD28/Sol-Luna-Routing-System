from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "ownership_guard.py"
SPEC = importlib.util.spec_from_file_location("ownership_guard", SCRIPT)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class OwnershipGuardTests(unittest.TestCase):
    def _plan_v2(self) -> dict:
        return {
            "schema_version": 2,
            "route": "SOL_LUNA",
            "frozen": True,
            "executors": [
                {"executor_id": "sol-main", "actor": "SOL"},
                {"executor_id": "luna-one", "actor": "LUNA"},
            ],
            "work_units": [
                {"unit_id": "core-work", "executor_id": "sol-main", "paths": ["src/core.py"]},
                {"unit_id": "ui-work", "executor_id": "luna-one", "paths": ["src/ui.py"]},
            ],
            "acceptances": [
                {
                    "acceptance_id": "core-tests",
                    "unit_id": "core-work",
                    "executor_id": "sol-main",
                    "paths": ["tests/test_core.py"],
                },
                {
                    "acceptance_id": "ui-tests",
                    "unit_id": "ui-work",
                    "executor_id": "luna-one",
                    "paths": ["tests/test_ui.py"],
                },
            ],
            "partitions": [
                {
                    "partition_id": "sol-partition",
                    "executor_id": "sol-main",
                    "unit_ids": ["core-work"],
                    "acceptance_ids": ["core-tests"],
                    "paths": ["src/core.py", "tests/test_core.py"],
                },
                {
                    "partition_id": "luna-partition",
                    "executor_id": "luna-one",
                    "unit_ids": ["ui-work"],
                    "acceptance_ids": ["ui-tests"],
                    "paths": ["src/ui.py", "tests/test_ui.py"],
                },
            ],
        }

    def test_disjoint_packages_may_write_in_parallel(self) -> None:
        result = GUARD.check_plan(
            {
                "schema_version": 1,
                "packages": [
                    {"package_id": "api-work", "write_scope": ["src/api"]},
                    {"package_id": "ui-work", "write_scope": ["src/ui"]},
                ],
            }
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["parallel_writes_allowed"])

    def test_prefix_overlap_is_rejected_before_dispatch(self) -> None:
        result = GUARD.check_plan(
            {
                "schema_version": 1,
                "packages": [
                    {"package_id": "broad", "write_scope": ["src"]},
                    {"package_id": "narrow", "write_scope": ["src/api"]},
                ],
            }
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["parallel_writes_allowed"])

    def test_changed_paths_outside_scope_block_acceptance(self) -> None:
        result = GUARD.check_changes(
            {
                "schema_version": 1,
                "package_id": "api-work",
                "owned_paths": ["src/api"],
                "changed_paths": ["src/api/handler.py", "src/shared.py"],
            }
        )
        self.assertEqual(result["scope_violations"], ["src/shared.py"])
        self.assertFalse(result["acceptance_allowed"])

    def test_frozen_handoff_rejects_later_changes_without_repair(self) -> None:
        result = GUARD.check_changes(
            {
                "schema_version": 1,
                "package_id": "api-work",
                "owned_paths": ["src/api"],
                "changed_paths": ["src/api/handler.py"],
                "handoff_frozen": True,
                "repair_authorized": False,
            }
        )
        self.assertEqual(result["status"], "FAIL")
        repaired = GUARD.check_changes(
            {
                "schema_version": 1,
                "package_id": "api-work",
                "owned_paths": ["src/api"],
                "changed_paths": ["src/api/handler.py"],
                "handoff_frozen": True,
                "repair_authorized": True,
            }
        )
        self.assertEqual(repaired["status"], "PASS")

    def test_absolute_and_traversal_paths_are_rejected(self) -> None:
        for unsafe in ("C:\\private\\file.py", "/etc/passwd", "src/../secret", "src/\nfile.py"):
            with self.subTest(unsafe=unsafe), self.assertRaises(GUARD.OwnershipError):
                GUARD.check_changes(
                    {
                        "schema_version": 1,
                        "package_id": "api-work",
                        "owned_paths": [unsafe],
                        "changed_paths": [],
                    }
                )

    def test_schema_one_preserves_legacy_path_normalization(self) -> None:
        result = GUARD.check_changes(
            {
                "schema_version": 1,
                "package_id": "api-work",
                "owned_paths": ["src\\api/"],
                "changed_paths": ["src\\api\\handler.py"],
            }
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["changed_paths"], ["src/api/handler.py"])
        plan = GUARD.check_plan(
            {
                "schema_version": 1,
                "packages": [{"package_id": "api-work", "write_scope": ["src\\api/"]}],
            }
        )
        self.assertEqual(plan["status"], "PASS")
        self.assertEqual(plan["packages"][0]["write_scope"], ["src/api"])

    def test_schema_two_rejects_cross_executor_duplicate_paths(self) -> None:
        candidate = self._plan_v2()
        candidate["work_units"][1]["paths"] = ["src/core.py"]
        candidate["partitions"][1]["paths"] = ["src/core.py", "tests/test_ui.py"]
        with self.assertRaisesRegex(GUARD.OwnershipError, "duplicate"):
            GUARD.check_plan(candidate)

    def test_schema_two_rejects_cross_executor_prefix_overlap(self) -> None:
        candidate = self._plan_v2()
        candidate["work_units"][1]["paths"] = ["src"]
        candidate["partitions"][1]["paths"] = ["src", "tests/test_ui.py"]
        with self.assertRaisesRegex(GUARD.OwnershipError, "prefix-overlapping"):
            GUARD.check_plan(candidate)

    def test_schema_two_allows_same_executor_multiple_disjoint_paths(self) -> None:
        candidate = self._plan_v2()
        candidate["work_units"][0]["paths"] = ["src/core.py", "src/core_helpers.py"]
        candidate["partitions"][0]["paths"] = [
            "src/core.py", "src/core_helpers.py", "tests/test_core.py"
        ]
        result = GUARD.check_plan(candidate)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["parallel_writes_allowed"])

    def test_schema_two_allows_same_executor_duplicate_across_unit_and_acceptance(self) -> None:
        candidate = self._plan_v2()
        candidate["acceptances"][0]["paths"] = ["src/core.py"]
        candidate["partitions"][0]["paths"] = ["src/core.py"]
        result = GUARD.check_plan(candidate)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["parallel_writes_allowed"])

    def test_schema_two_rejects_duplicate_paths_across_same_executor_work_units(self) -> None:
        candidate = self._plan_v2()
        candidate["work_units"][1]["executor_id"] = "sol-main"
        candidate["work_units"][1]["paths"] = ["src/core.py"]
        candidate["acceptances"][1]["executor_id"] = "sol-main"
        candidate["partitions"][1]["executor_id"] = "sol-main"
        candidate["partitions"][1]["paths"] = ["src/core.py", "tests/test_ui.py"]
        with self.assertRaisesRegex(GUARD.OwnershipError, "duplicate"):
            GUARD.check_plan(candidate)

    def test_schema_two_rejects_noncanonical_repository_paths(self) -> None:
        for unsafe in (
            "src\\file.py", "src//file.py", "src/", "src/../secret", ".", "src/./file.py",
            "src/\nfile.py", "/etc/passwd", "C:/private/file.py",
        ):
            candidate = self._plan_v2()
            candidate["work_units"][0]["paths"] = [unsafe]
            with self.subTest(unsafe=unsafe), self.assertRaises(GUARD.OwnershipError):
                GUARD.check_plan(candidate)

    def test_schema_two_rejects_trailing_slash_and_backslash_paths(self) -> None:
        for unsafe in ("src/", "src\\file.py"):
            candidate = self._plan_v2()
            candidate["work_units"][0]["paths"] = [unsafe]
            with self.subTest(unsafe=unsafe), self.assertRaises(GUARD.OwnershipError):
                GUARD.check_plan(candidate)

    def test_schema_two_rejects_wrong_types_and_split_acceptance_partition(self) -> None:
        for field, value in (("frozen", 1), ("executors", {}), ("work_units", "units")):
            candidate = self._plan_v2()
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(GUARD.OwnershipError):
                GUARD.check_plan(candidate)

        candidate = self._plan_v2()
        candidate["work_units"][1]["executor_id"] = "sol-main"
        candidate["acceptances"][1]["executor_id"] = "sol-main"
        candidate["partitions"][1]["executor_id"] = "sol-main"
        candidate["partitions"][0]["acceptance_ids"] = ["ui-tests"]
        candidate["partitions"][0]["paths"] = ["src/core.py", "tests/test_ui.py"]
        candidate["partitions"][1]["acceptance_ids"] = ["core-tests"]
        candidate["partitions"][1]["paths"] = ["src/ui.py", "tests/test_core.py"]
        with self.assertRaises(GUARD.OwnershipError):
            GUARD.check_plan(candidate)

    def test_schema_two_rejects_sensitive_private_path(self) -> None:
        candidate = self._plan_v2()
        candidate["work_units"][0]["paths"] = ["src/credentials/token.json"]
        candidate["partitions"][0]["paths"] = ["src/credentials/token.json", "tests/test_core.py"]
        with self.assertRaisesRegex(GUARD.OwnershipError, "sensitive private path"):
            GUARD.check_plan(candidate)

    def test_schema_two_normalizes_complete_frozen_partitions(self) -> None:
        result = GUARD.check_plan(self._plan_v2())
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["parallel_writes_allowed"])
        self.assertRegex(result["partition_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            [item["executor_id"] for item in result["plan"]["executors"]],
            ["luna-one", "sol-main"],
        )

    def test_schema_two_digest_is_order_independent_but_ownership_sensitive(self) -> None:
        plan = self._plan_v2()
        reordered = deepcopy(plan)
        for field in ("executors", "work_units", "acceptances", "partitions"):
            reordered[field].reverse()
        for partition in reordered["partitions"]:
            partition["paths"].reverse()
        self.assertEqual(GUARD.partition_digest(plan), GUARD.partition_digest(reordered))

        changed = deepcopy(plan)
        changed["work_units"][1]["paths"] = ["src/view.py"]
        changed["partitions"][1]["paths"] = ["src/view.py", "tests/test_ui.py"]
        self.assertNotEqual(GUARD.partition_digest(plan), GUARD.partition_digest(changed))

    def test_schema_two_rejects_malformed_declared_partition_digest(self) -> None:
        for declared in (
            "sha256:" + "A" * 64,
            "sha256:" + "0" * 63,
            "sha256:" + "0" * 65,
            "sha512:" + "0" * 64,
        ):
            candidate = self._plan_v2()
            candidate["partition_digest"] = declared
            with self.subTest(declared=declared), self.assertRaisesRegex(
                GUARD.OwnershipError, "partition_digest"
            ):
                GUARD.check_plan(candidate)

    def test_schema_two_rejects_incomplete_or_cross_executor_ownership(self) -> None:
        for mutate in ("missing-unit", "wrong-acceptance", "bad-cover"):
            candidate = deepcopy(self._plan_v2())
            if mutate == "missing-unit":
                candidate["partitions"][1]["unit_ids"] = ["core-work"]
            elif mutate == "wrong-acceptance":
                candidate["acceptances"][1]["executor_id"] = "sol-main"
            else:
                candidate["partitions"][1]["paths"] = ["src/ui.py"]
            with self.subTest(mutate=mutate), self.assertRaises(GUARD.OwnershipError):
                GUARD.check_plan(candidate)

    def test_schema_two_reports_cross_object_path_conflicts(self) -> None:
        candidate = deepcopy(self._plan_v2())
        candidate["acceptances"][1]["paths"] = ["src/ui.py/acceptance"]
        candidate["partitions"][1]["paths"] = ["src/ui.py", "src/ui.py/acceptance"]
        with self.assertRaisesRegex(GUARD.OwnershipError, "prefix-overlapping"):
            GUARD.check_plan(candidate)

    def _changes_v2(self, plan: dict | None = None) -> tuple[dict, dict]:
        plan = deepcopy(plan or self._plan_v2())
        checked = GUARD.check_plan(plan)
        changes = {
            "schema_version": 2,
            "partition_digest": checked["partition_digest"],
            "partition_id": "sol-partition",
            "changed_paths": ["src/core.py"],
            "handoff_frozen": False,
            "repair_authorized": False,
        }
        return changes, plan

    def test_schema_two_changes_use_frozen_plan_ownership(self) -> None:
        changes, plan = self._changes_v2()
        result = GUARD.check_changes(changes, plan)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["partition_id"], "sol-partition")
        self.assertTrue(result["acceptance_allowed"])
        self.assertEqual(result["violations"], [])

    def test_schema_two_changes_reject_scope_and_unknown_partition(self) -> None:
        changes, plan = self._changes_v2()
        changes["changed_paths"] = ["src/ui.py"]
        result = GUARD.check_changes(changes, plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["scope_violations"], ["src/ui.py"])
        self.assertEqual(result["violations"], ["scope_violation"])
        changes["partition_id"] = "missing-partition"
        unknown = GUARD.check_changes(changes, plan)
        self.assertEqual(unknown["status"], "FAIL")
        self.assertEqual(unknown["violations"], ["scope_violation", "unknown_partition"])

    def test_schema_two_changes_reject_digest_and_owned_paths(self) -> None:
        changes, plan = self._changes_v2()
        changes["partition_digest"] = "sha256:" + "0" * 64
        mismatch = GUARD.check_changes(changes, plan)
        self.assertEqual(mismatch["status"], "FAIL")
        self.assertEqual(mismatch["violations"], ["partition_digest_mismatch"])
        changes, plan = self._changes_v2()
        changes["owned_paths"] = ["src"]
        with self.assertRaises(GUARD.OwnershipError):
            GUARD.check_changes(changes, plan)

    def test_schema_two_changes_require_plan_and_strict_paths(self) -> None:
        changes, plan = self._changes_v2()
        with self.assertRaises(GUARD.OwnershipError):
            GUARD.check_changes(changes)
        invalid_plan = deepcopy(plan)
        invalid_plan["frozen"] = False
        with self.assertRaises(GUARD.OwnershipError):
            GUARD.check_changes(changes, invalid_plan)
        for unsafe in ("src\\core.py", "src//core.py", "src/../core.py"):
            changes, plan = self._changes_v2()
            changes["changed_paths"] = [unsafe]
            with self.subTest(unsafe=unsafe), self.assertRaises(GUARD.OwnershipError):
                GUARD.check_changes(changes, plan)

    def test_schema_two_changes_handoff_repair_authorization(self) -> None:
        changes, plan = self._changes_v2()
        changes["handoff_frozen"] = True
        frozen = GUARD.check_changes(changes, plan)
        self.assertEqual(frozen["status"], "FAIL")
        self.assertEqual(frozen["violations"], ["handoff_frozen_without_repair"])
        changes["repair_authorized"] = True
        self.assertEqual(GUARD.check_changes(changes, plan)["status"], "PASS")

    def test_schema_two_changes_cli_success_and_failure_exit_codes(self) -> None:
        changes, plan = self._changes_v2()
        with tempfile.TemporaryDirectory() as temp:
            changes_path = Path(temp) / "changes.json"
            plan_path = Path(temp) / "plan.json"
            changes_path.write_text(json.dumps(changes), encoding="utf-8")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), "check-changes", "--input", str(changes_path), "--plan", str(plan_path)]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)
            changes["changed_paths"] = ["src/ui.py"]
            changes_path.write_text(json.dumps(changes), encoding="utf-8")
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 3)
            self.assertNotIn("Traceback", completed.stderr)

    def test_schema_two_route_actor_rules_do_not_fix_allocation_shape(self) -> None:
        plan = self._plan_v2()
        plan["executors"].append({"executor_id": "luna-two", "actor": "LUNA"})
        self.assertEqual(GUARD.check_plan(plan)["status"], "PASS")

        sol_only = deepcopy(self._plan_v2())
        sol_only["route"] = "SOL_ONLY"
        with self.assertRaisesRegex(GUARD.OwnershipError, "LUNA executor"):
            GUARD.check_plan(sol_only)

    def test_cli_rejects_duplicate_keys_and_non_finite_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            for payload in (
                '{"schema_version":2,"schema_version":2}',
                '{"schema_version":NaN}',
            ):
                path.write_text(payload, encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), "check-plan", "--input", str(path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("Traceback", completed.stderr)
            path.write_bytes(b"\xff\xfe")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "check-plan", "--input", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()

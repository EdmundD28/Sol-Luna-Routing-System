from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "ownership_guard.py"
SPEC = importlib.util.spec_from_file_location("ownership_guard", SCRIPT)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class OwnershipGuardTests(unittest.TestCase):
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
        for unsafe in ("C:\\private\\file.py", "/etc/passwd", "src/../secret"):
            with self.subTest(unsafe=unsafe), self.assertRaises(GUARD.OwnershipError):
                GUARD.check_changes(
                    {
                        "schema_version": 1,
                        "package_id": "api-work",
                        "owned_paths": [unsafe],
                        "changed_paths": [],
                    }
                )


if __name__ == "__main__":
    unittest.main()

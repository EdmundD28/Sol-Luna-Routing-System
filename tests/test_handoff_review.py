from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review.py"
SPEC = importlib.util.spec_from_file_location("handoff_review_test_module", SCRIPT)
assert SPEC and SPEC.loader
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)

ZERO = "sha256:" + "0" * 64
ONE = "sha256:" + "1" * 64


def handoff(handoff_id: str, package_id: str, path: str, **changes):
    item = {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "executor_id": "luna-medium",
        "depends_on": [],
        "writable_paths": [path],
        "candidate_digest": ZERO,
        "status": "READY",
        "blocker_kind": None,
        "blocker_digest": None,
        "acceptance_passed": True,
        "risk": "low",
        "shared_interface": False,
        "repair_count": 0,
        "review_depth": "TARGETED",
    }
    item.update(changes)
    return item


class HandoffReviewTests(unittest.TestCase):
    def test_template_compiles_and_is_fresh(self):
        source = REVIEW.template()
        snapshot = REVIEW.compile_portfolio(source)
        self.assertEqual(snapshot["review_handoff_ids"], ["handoff-core"])
        source["handoffs"][0]["depends_on"].append("mutated")
        self.assertEqual(REVIEW.template()["handoffs"][0]["depends_on"], [])

    def test_topology_and_normalization(self):
        source = {
            "schema_version": 1,
            "portfolio_id": "release-alpha",
            "handoffs": [
                handoff("z", "pkg-z", "src/z.py", depends_on=["pkg-a"]),
                handoff("a", "pkg-a", "src/a.py"),
            ],
        }
        snapshot = REVIEW.compile_portfolio(source)
        self.assertEqual([item["handoff_id"] for item in snapshot["handoffs"]], ["a", "z"])
        self.assertEqual(snapshot["topological_order"], ["a", "z"])

    def test_dependency_states_and_review_depth(self):
        hold = handoff("hold", "pkg-hold", "src/hold.py", status="HOLD", blocker_kind="open-risk", blocker_digest=ONE, acceptance_passed=False, review_depth="DEEP")
        dependent = handoff("dependent", "pkg-dependent", "src/dependent.py", depends_on=["pkg-hold"])
        source = {"schema_version": 1, "portfolio_id": "p", "handoffs": [hold, dependent]}
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio(source)
        dependent.update(status="HOLD", blocker_kind="open-risk", blocker_digest=ONE, acceptance_passed=False, review_depth="DEEP")
        snapshot = REVIEW.compile_portfolio(source)
        self.assertEqual(snapshot["partitions"]["hold"], ["dependent", "hold"])

    def test_global_path_overlap_and_invalid_contract(self):
        source = {"schema_version": 1, "portfolio_id": "p", "handoffs": [handoff("a", "a", "src/a.py")]}
        for path in ("/absolute", "C:file.py", "src/../x.py", "src/CON.txt", "src/file:stream", "src/file "):
            candidate = copy.deepcopy(source)
            candidate["handoffs"][0]["writable_paths"] = [path]
            with self.subTest(path=path), self.assertRaises(REVIEW.ReviewError):
                REVIEW.compile_portfolio(candidate)
        candidate = copy.deepcopy(source)
        candidate["handoffs"].append(handoff("b", "b", "SRC/a.py/more"))
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio(candidate)

    def test_windows_device_name_with_trailing_space_is_rejected(self):
        source = {"schema_version": 1, "portfolio_id": "p", "handoffs": [handoff("a", "a", "src/a.py")]}
        source["handoffs"][0]["writable_paths"] = ["src/CON .txt"]
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio(source)

    def test_compare_changes_progressions_and_transitive_impact(self):
        before_source = {"schema_version": 1, "portfolio_id": "p", "handoffs": [handoff("a", "a", "src/a.py")]}
        before_source["handoffs"].append(handoff("b", "b", "src/b.py", depends_on=["a"]))
        after_source = copy.deepcopy(before_source)
        after_source["handoffs"][0]["candidate_digest"] = ONE
        before = REVIEW.compile_portfolio(before_source)
        after = REVIEW.compile_portfolio(after_source)
        result = REVIEW.compare(before, after)
        self.assertEqual(result["changed_handoff_ids"], ["a"])
        self.assertEqual(result["affected_review_handoff_ids"], ["a", "b"])

    def test_compare_rejects_tampered_derived_fields(self):
        snapshot = REVIEW.compile_portfolio(REVIEW.template())
        snapshot["review_handoff_ids"] = []
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compare(snapshot, snapshot)


if __name__ == "__main__":
    unittest.main()

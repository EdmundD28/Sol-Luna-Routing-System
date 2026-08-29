from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / ".agents" / "skills" / "sol-luna" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import handoff_review as review


def digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def handoff(
    handoff_id: str,
    package_id: str,
    *,
    depends_on: list[str] | None = None,
    path: str | None = None,
    status: str = "READY",
    blocker_kind: str | None = None,
    blocker_digest: str | None = None,
    acceptance_passed: bool | None = None,
    risk: str = "low",
    shared_interface: bool = False,
    repair_count: int = 0,
    review_depth: str = "TARGETED",
) -> dict:
    if acceptance_passed is None:
        acceptance_passed = status == "READY"
    return {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "executor_id": "luna-medium",
        "depends_on": [] if depends_on is None else depends_on,
        "writable_paths": [path or f"src/{package_id}.py"],
        "candidate_digest": digest(handoff_id),
        "status": status,
        "blocker_kind": blocker_kind,
        "blocker_digest": blocker_digest,
        "acceptance_passed": acceptance_passed,
        "risk": risk,
        "shared_interface": shared_interface,
        "repair_count": repair_count,
        "review_depth": review_depth,
    }


class HandoffReviewTests(unittest.TestCase):
    def test_compile_is_normalized_and_does_not_mutate_input(self) -> None:
        source = {
            "schema_version": 1,
            "portfolio_id": "release-alpha",
            "handoffs": [
                handoff("handoff-z", "z", depends_on=["a"]),
                handoff("handoff-a", "a"),
            ],
        }
        source_before = copy.deepcopy(source)
        snapshot = review.compile_portfolio(source)
        self.assertEqual(source, source_before)
        self.assertEqual(["handoff-a", "handoff-z"], [h["handoff_id"] for h in snapshot["handoffs"]])
        self.assertEqual(["handoff-a", "handoff-z"], snapshot["topological_order"])
        self.assertEqual({"ready": ["handoff-a", "handoff-z"], "hold": [], "blocked": []}, snapshot["partitions"])
        self.assertEqual({"luna-medium": ["handoff-a", "handoff-z"]}, snapshot["executors"])
        self.assertEqual(snapshot, review.compile_portfolio(copy.deepcopy(source)))
        self.assertTrue(snapshot["snapshot_fingerprint"].startswith("sha256:"))

    def test_compare_reports_changes_state_and_transitive_dependents(self) -> None:
        before_source = {
            "schema_version": 1,
            "portfolio_id": "release-alpha",
            "handoffs": [handoff("handoff-a", "a"), handoff("handoff-b", "b", depends_on=["a"])],
        }
        after_source = copy.deepcopy(before_source)
        after_source["handoffs"][0]["candidate_digest"] = digest("new")
        after_source["handoffs"][0]["status"] = "HOLD"
        after_source["handoffs"][0]["acceptance_passed"] = False
        after_source["handoffs"][0]["blocker_kind"] = "open-risk"
        after_source["handoffs"][0]["blocker_digest"] = digest("risk")
        after_source["handoffs"][0]["review_depth"] = "DEEP"
        # A dependent of HOLD is allowed to remain READY only when it does not
        # depend on that state; this one must be changed to HOLD for validity.
        after_source["handoffs"][1]["status"] = "HOLD"
        after_source["handoffs"][1]["acceptance_passed"] = False
        after_source["handoffs"][1]["blocker_kind"] = "validation-failure"
        after_source["handoffs"][1]["blocker_digest"] = digest("failure")
        after_source["handoffs"][1]["review_depth"] = "DEEP"
        result = review.compare(review.compile_portfolio(before_source), review.compile_portfolio(after_source))
        self.assertEqual(["handoff-a", "handoff-b"], result["changed_handoff_ids"])
        self.assertEqual(["handoff-a", "handoff-b"], result["state_regressions"])
        self.assertEqual([], result["state_progressions"])
        self.assertEqual(["handoff-a", "handoff-b"], result["affected_review_handoff_ids"])

    def test_dependency_states_and_cycles_are_rejected(self) -> None:
        blocked = handoff(
            "handoff-a",
            "a",
            status="BLOCKED",
            blocker_kind="missing-input",
            blocker_digest=digest("missing"),
            review_depth="DEEP",
        )
        ready_dependent = handoff("handoff-b", "b", depends_on=["a"])
        source = {"schema_version": 1, "portfolio_id": "release-alpha", "handoffs": [blocked, ready_dependent]}
        with self.assertRaises(review.ReviewError):
            review.compile_portfolio(source)

        cycle_a = handoff("handoff-a", "a", depends_on=["b"])
        cycle_b = handoff("handoff-b", "b", depends_on=["a"])
        with self.assertRaises(review.ReviewError):
            review.compile_portfolio({"schema_version": 1, "portfolio_id": "release-alpha", "handoffs": [cycle_a, cycle_b]})

    def test_path_contract_is_case_insensitive_and_strict(self) -> None:
        for invalid in ["/absolute.py", "C:relative.py", "src\\core.py", "src/../core.py", "src/con.txt", "src/CON .txt", "src/file:stream", "src/name. "]:
            with self.subTest(invalid=invalid), self.assertRaises(review.ReviewError):
                review.compile_portfolio(
                    {"schema_version": 1, "portfolio_id": "release-alpha", "handoffs": [handoff("handoff-a", "a", path=invalid)]}
                )
        overlapping = [
            handoff("handoff-a", "a", path="src"),
            handoff("handoff-b", "b", path="SRC/core.py"),
        ]
        with self.assertRaises(review.ReviewError):
            review.compile_portfolio({"schema_version": 1, "portfolio_id": "release-alpha", "handoffs": overlapping})

    def test_snapshot_derived_fields_are_verified(self) -> None:
        source = {"schema_version": 1, "portfolio_id": "release-alpha", "handoffs": [handoff("handoff-a", "a")]}
        snapshot = review.compile_portfolio(source)
        snapshot["review_handoff_ids"] = []
        with self.assertRaises(review.ReviewError):
            review.compare(snapshot, review.compile_portfolio(source))


if __name__ == "__main__":
    unittest.main()

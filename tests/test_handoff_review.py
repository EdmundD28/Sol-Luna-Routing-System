from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review.py"
SPEC = importlib.util.spec_from_file_location("handoff_review", SCRIPT)
assert SPEC and SPEC.loader
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)

DIGEST = "sha256:" + "1" * 64


def handoff(
    handoff_id: str,
    package_id: str,
    path: str,
    *,
    depends_on: list[str] | None = None,
    status: str = "READY",
    risk: str = "low",
) -> dict:
    non_ready = status != "READY"
    blocker_kind = None
    if status == "HOLD":
        blocker_kind = "open-risk"
    elif status == "BLOCKED":
        blocker_kind = "missing-input"
    return {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "executor_id": "luna-medium",
        "depends_on": depends_on or [],
        "writable_paths": [path],
        "candidate_digest": DIGEST,
        "status": status,
        "blocker_kind": blocker_kind,
        "blocker_digest": DIGEST if non_ready else None,
        "acceptance_passed": not non_ready,
        "risk": risk,
        "shared_interface": False,
        "repair_count": 0,
        "review_depth": "DEEP" if non_ready else ("STANDARD" if risk == "medium" else "TARGETED"),
    }


class HandoffReviewTests(unittest.TestCase):
    def test_template_compiles_deterministically_without_mutation(self) -> None:
        source = REVIEW.template()
        before = copy.deepcopy(source)
        compiled = REVIEW.compile_portfolio(source)
        self.assertEqual(source, before)
        self.assertEqual(compiled["topological_order"], ["handoff-core"])
        self.assertEqual(compiled["partitions"]["ready"], ["handoff-core"])
        self.assertEqual(compiled["review_handoff_ids"], ["handoff-core"])
        self.assertRegex(compiled["snapshot_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(compiled, REVIEW.compile_portfolio(copy.deepcopy(source)))

    def test_normalization_topology_partitions_and_executors(self) -> None:
        core = handoff("handoff-z", "core", "src/z.py")
        api = handoff("handoff-a", "api", "src/a.py", depends_on=["core"], risk="medium")
        source = {"schema_version": 1, "portfolio_id": "release", "handoffs": [core, api]}
        result = REVIEW.compile_portfolio(source)
        self.assertEqual([x["handoff_id"] for x in result["handoffs"]], ["handoff-a", "handoff-z"])
        self.assertEqual(result["topological_order"], ["handoff-z", "handoff-a"])
        self.assertEqual(result["executors"], {"luna-medium": ["handoff-a", "handoff-z"]})

    def test_exact_fields_types_and_depth(self) -> None:
        cases = [
            lambda x: x.update(extra=True),
            lambda x: x.pop("portfolio_id"),
            lambda x: x.update(schema_version=True),
            lambda x: x.update(portfolio_id="bad--id"),
            lambda x: x["handoffs"][0].update(repair_count=True),
            lambda x: x["handoffs"][0].update(review_depth="DEEP"),
            lambda x: x["handoffs"][0].update(candidate_digest="sha256:" + "A" * 64),
        ]
        for mutate in cases:
            candidate = REVIEW.template()
            mutate(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(REVIEW.ReviewError):
                REVIEW.compile_portfolio(candidate)

    def test_status_rules_and_dependency_propagation(self) -> None:
        blocked = handoff("handoff-a", "a", "a.py", status="BLOCKED")
        downstream = handoff("handoff-b", "b", "b.py", depends_on=["a"])
        source = {"schema_version": 1, "portfolio_id": "release", "handoffs": [blocked, downstream]}
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio(source)
        downstream.update(
            status="BLOCKED",
            blocker_kind="external-state",
            blocker_digest=DIGEST,
            acceptance_passed=False,
            review_depth="DEEP",
        )
        self.assertEqual(REVIEW.compile_portfolio(source)["partitions"]["blocked"], ["handoff-a", "handoff-b"])

    def test_graph_unknown_self_and_cycle(self) -> None:
        source = REVIEW.template()
        source["handoffs"][0]["depends_on"] = ["missing"]
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio(source)
        source["handoffs"][0]["depends_on"] = ["core"]
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio(source)
        a = handoff("handoff-a", "a", "a.py", depends_on=["b"])
        b = handoff("handoff-b", "b", "b.py", depends_on=["a"])
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio({"schema_version": 1, "portfolio_id": "release", "handoffs": [a, b]})

    def test_unsafe_and_overlapping_paths(self) -> None:
        unsafe = [
            "/root/file", "C:/file", "C:file", "a\\b", "a//b", "a/./b", "a/../b",
            "a/CON.txt", "a/CON .txt", "a/COM¹.log", "a/name:stream", "a/file.",
            "a/file ", "a/\x00b", "a/\ud800",
        ]
        for path in unsafe:
            source = REVIEW.template()
            source["handoffs"][0]["writable_paths"] = [path]
            with self.subTest(path=path), self.assertRaises(REVIEW.ReviewError):
                REVIEW.compile_portfolio(source)
        first = handoff("handoff-a", "a", "Src/Core")
        second = handoff("handoff-b", "b", "src/core/file.py")
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.compile_portfolio({"schema_version": 1, "portfolio_id": "release", "handoffs": [first, second]})

    def test_compare_changes_state_and_transitive_dependents(self) -> None:
        a = handoff("handoff-a", "a", "a.py")
        b = handoff("handoff-b", "b", "b.py", depends_on=["a"])
        c = handoff("handoff-c", "c", "c.py", depends_on=["b"])
        before = REVIEW.compile_portfolio({"schema_version": 1, "portfolio_id": "release", "handoffs": [a, b, c]})
        changed = copy.deepcopy(a)
        changed["candidate_digest"] = "sha256:" + "2" * 64
        after = REVIEW.compile_portfolio({"schema_version": 1, "portfolio_id": "release", "handoffs": [changed, b, c]})
        result = REVIEW.compare(before, after)
        self.assertEqual(result["changed_handoff_ids"], ["handoff-a"])
        self.assertEqual(result["affected_review_handoff_ids"], ["handoff-a", "handoff-b", "handoff-c"])

    def test_compare_rejects_tampered_derived_fields_and_fingerprint(self) -> None:
        snapshot = REVIEW.compile_portfolio(REVIEW.template())
        for key, mutate in (
            ("partition", lambda x: x["partitions"]["ready"].clear()),
            ("fingerprint", lambda x: x.update(snapshot_fingerprint=DIGEST)),
            ("order", lambda x: x["topological_order"].clear()),
        ):
            candidate = copy.deepcopy(snapshot)
            mutate(candidate)
            with self.subTest(key=key), self.assertRaises(REVIEW.ReviewError):
                REVIEW.compare(candidate, snapshot)


if __name__ == "__main__":
    unittest.main()

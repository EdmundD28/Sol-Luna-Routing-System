import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / ".agents"
    / "skills"
    / "sol-luna"
    / "scripts"
    / "handoff_review.py"
)
SPEC = importlib.util.spec_from_file_location("handoff_review", MODULE_PATH)
handoff_review = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(handoff_review)


def ready(handoff_id="handoff-core", package_id="core", **changes):
    value = {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "executor_id": "luna-medium",
        "depends_on": [],
        "writable_paths": [f"src/{package_id}.py"],
        "candidate_digest": "sha256:" + "1" * 64,
        "status": "READY",
        "blocker_kind": None,
        "blocker_digest": None,
        "acceptance_passed": True,
        "risk": "low",
        "shared_interface": False,
        "repair_count": 0,
        "review_depth": "TARGETED",
    }
    value.update(changes)
    return value


def portfolio(*handoffs):
    return {"schema_version": 1, "portfolio_id": "release-alpha", "handoffs": list(handoffs)}


class CompilePortfolioTests(unittest.TestCase):
    def test_template_compiles_without_mutation_and_has_exact_fingerprint(self):
        source = handoff_review.template()
        original = copy.deepcopy(source)
        result = handoff_review.compile_portfolio(source)
        self.assertEqual(source, original)
        self.assertEqual(result["review_handoff_ids"], ["handoff-core"])
        without_fingerprint = dict(result)
        fingerprint = without_fingerprint.pop("snapshot_fingerprint")
        canonical = json.dumps(
            without_fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(fingerprint, "sha256:" + hashlib.sha256(canonical).hexdigest())

    def test_normalizes_arrays_and_uses_handoff_id_for_stable_topology(self):
        source = portfolio(
            ready("handoff-z", "base", writable_paths=["z/two.py", "z/one.py"]),
            ready("handoff-a", "leaf", depends_on=["base"]),
            ready("handoff-b", "independent", executor_id="luna-high"),
        )
        result = handoff_review.compile_portfolio(source)
        self.assertEqual([item["handoff_id"] for item in result["handoffs"]], ["handoff-a", "handoff-b", "handoff-z"])
        self.assertEqual(result["topological_order"], ["handoff-b", "handoff-z", "handoff-a"])
        self.assertEqual(result["handoffs"][2]["writable_paths"], ["z/one.py", "z/two.py"])
        self.assertEqual(result["executors"]["luna-medium"], ["handoff-a", "handoff-z"])

    def test_status_partitions_and_derived_depth(self):
        hold = ready(
            "handoff-hold",
            "hold",
            status="HOLD",
            acceptance_passed=False,
            blocker_kind="open-risk",
            blocker_digest="sha256:" + "2" * 64,
            review_depth="DEEP",
        )
        blocked = ready(
            "handoff-blocked",
            "blocked",
            status="BLOCKED",
            acceptance_passed=False,
            blocker_kind="missing-input",
            blocker_digest="sha256:" + "3" * 64,
            review_depth="DEEP",
        )
        result = handoff_review.compile_portfolio(portfolio(hold, blocked))
        self.assertEqual(result["partitions"], {"ready": [], "hold": ["handoff-hold"], "blocked": ["handoff-blocked"]})
        self.assertEqual(result["review_handoff_ids"], [])

    def test_rejects_exact_field_type_digest_and_depth_errors(self):
        cases = []
        extra = ready()
        extra["extra"] = 1
        cases.append(extra)
        cases.append(ready(candidate_digest="SHA256:" + "0" * 64))
        cases.append(ready(status=[]))
        cases.append(ready(repair_count=True))
        cases.append(ready(risk="medium", review_depth="TARGETED"))
        cases.append(ready(status="HOLD", acceptance_passed=False))
        for handoff in cases:
            with self.subTest(handoff=handoff):
                with self.assertRaises(handoff_review.ReviewError):
                    handoff_review.compile_portfolio(portfolio(handoff))
        wrong_schema = portfolio(ready())
        wrong_schema["schema_version"] = 1.0
        with self.assertRaises(handoff_review.ReviewError):
            handoff_review.compile_portfolio(wrong_schema)

    def test_rejects_unsafe_and_overlapping_paths(self):
        invalid_paths = [
            "",
            "/rooted",
            "C:drive-relative",
            "a\\b.py",
            "a//b.py",
            "a/../b.py",
            "a/CON.txt",
            "a/COM¹.log",
            "a/file.py.",
            "a/name:stream",
            "a/\x01.py",
            "a/\x85.py",
            "a/\ud800.py",
        ]
        for path in invalid_paths:
            with self.subTest(path=repr(path)):
                with self.assertRaises(handoff_review.ReviewError):
                    handoff_review.compile_portfolio(portfolio(ready(writable_paths=[path])))
        with self.assertRaises(handoff_review.ReviewError):
            handoff_review.compile_portfolio(
                portfolio(
                    ready("handoff-a", "a", writable_paths=["Src/Core"]),
                    ready("handoff-b", "b", writable_paths=["src/core/file.py"]),
                )
            )

    def test_rejects_missing_self_duplicate_and_cyclic_dependencies(self):
        bad_sets = [
            [ready(depends_on=["missing"])],
            [ready(depends_on=["core"])],
            [ready(depends_on=["other", "other"]), ready("handoff-other", "other")],
            [ready("handoff-a", "a", depends_on=["b"]), ready("handoff-b", "b", depends_on=["a"])],
        ]
        for handoffs in bad_sets:
            with self.subTest(handoffs=handoffs):
                with self.assertRaises(handoff_review.ReviewError):
                    handoff_review.compile_portfolio(portfolio(*handoffs))

    def test_rejects_invalid_dependency_status_propagation(self):
        blocked = ready(
            "handoff-blocked",
            "blocked",
            status="BLOCKED",
            acceptance_passed=False,
            blocker_kind="external-state",
            blocker_digest="sha256:" + "4" * 64,
            review_depth="DEEP",
        )
        hold = ready(
            "handoff-hold",
            "hold",
            status="HOLD",
            acceptance_passed=False,
            blocker_kind="validation-failure",
            blocker_digest="sha256:" + "5" * 64,
            review_depth="DEEP",
        )
        for parent in (blocked, hold):
            child = ready("handoff-child", "child", depends_on=[parent["package_id"]])
            with self.subTest(status=parent["status"]):
                with self.assertRaises(handoff_review.ReviewError):
                    handoff_review.compile_portfolio(portfolio(parent, child))


class CompareTests(unittest.TestCase):
    def test_compare_reports_changes_state_and_transitive_dependents(self):
        before = handoff_review.compile_portfolio(
            portfolio(
                ready("handoff-core", "core"),
                ready("handoff-api", "api", depends_on=["core"]),
                ready("handoff-ui", "ui", depends_on=["api"]),
                ready("handoff-old", "old"),
            )
        )
        changed_core = ready(
            "handoff-core",
            "core",
            status="HOLD",
            acceptance_passed=False,
            blocker_kind="validation-failure",
            blocker_digest="sha256:" + "6" * 64,
            review_depth="DEEP",
        )
        held_api = ready(
            "handoff-api",
            "api",
            depends_on=["core"],
            status="HOLD",
            acceptance_passed=False,
            blocker_kind="open-risk",
            blocker_digest="sha256:" + "7" * 64,
            review_depth="DEEP",
        )
        held_ui = ready(
            "handoff-ui",
            "ui",
            depends_on=["api"],
            status="HOLD",
            acceptance_passed=False,
            blocker_kind="open-risk",
            blocker_digest="sha256:" + "8" * 64,
            review_depth="DEEP",
        )
        after = handoff_review.compile_portfolio(
            portfolio(changed_core, held_api, held_ui, ready("handoff-new", "new"))
        )
        result = handoff_review.compare(before, after)
        self.assertEqual(result["added_handoff_ids"], ["handoff-new"])
        self.assertEqual(result["removed_handoff_ids"], ["handoff-old"])
        self.assertEqual(result["changed_handoff_ids"], ["handoff-api", "handoff-core", "handoff-ui"])
        self.assertEqual(result["state_regressions"], ["handoff-api", "handoff-core", "handoff-ui"])
        self.assertEqual(result["state_progressions"], [])
        self.assertEqual(
            result["affected_review_handoff_ids"],
            ["handoff-api", "handoff-core", "handoff-new", "handoff-ui"],
        )

    def test_compare_rejects_tampering_and_portfolio_mismatch(self):
        snapshot = handoff_review.compile_portfolio(portfolio(ready()))
        tampered = copy.deepcopy(snapshot)
        tampered["partitions"]["ready"] = []
        with self.assertRaises(handoff_review.ReviewError):
            handoff_review.compare(snapshot, tampered)
        other = handoff_review.compile_portfolio(
            {"schema_version": 1, "portfolio_id": "release-beta", "handoffs": [ready()]}
        )
        with self.assertRaises(handoff_review.ReviewError):
            handoff_review.compare(snapshot, other)


if __name__ == "__main__":
    unittest.main()

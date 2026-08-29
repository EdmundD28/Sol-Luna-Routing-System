from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review.py"
SPEC = importlib.util.spec_from_file_location("sol_luna_handoff_review_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review
SPEC.loader.exec_module(review)


ZERO = "sha256:" + "0" * 64
ONE = "sha256:" + "1" * 64
TWO = "sha256:" + "2" * 64


def handoff(
    handoff_id: str,
    package_id: str,
    *,
    executor_id: str = "luna-high",
    depends_on: list[str] | None = None,
    writable_paths: list[str] | None = None,
    candidate_digest: str = ZERO,
    status: str = "READY",
    blocker_kind: str | None = None,
    blocker_digest: str | None = None,
    acceptance_passed: bool = True,
    risk: str = "low",
    shared_interface: bool = False,
    repair_count: int = 0,
    review_depth: str = "TARGETED",
) -> dict:
    return {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "executor_id": executor_id,
        "depends_on": [] if depends_on is None else depends_on,
        "writable_paths": [f"src/{package_id}.py"] if writable_paths is None else writable_paths,
        "candidate_digest": candidate_digest,
        "status": status,
        "blocker_kind": blocker_kind,
        "blocker_digest": blocker_digest,
        "acceptance_passed": acceptance_passed,
        "risk": risk,
        "shared_interface": shared_interface,
        "repair_count": repair_count,
        "review_depth": review_depth,
    }


def portfolio(*handoffs: dict, portfolio_id: str = "release-alpha") -> dict:
    return {
        "schema_version": 1,
        "portfolio_id": portfolio_id,
        "handoffs": list(handoffs),
    }


def hold(item: dict, *, kind: str = "validation-failure") -> dict:
    item.update(
        status="HOLD",
        blocker_kind=kind,
        blocker_digest=ONE,
        acceptance_passed=False,
        review_depth="DEEP",
    )
    return item


def blocked(item: dict, *, kind: str = "missing-input") -> dict:
    item.update(
        status="BLOCKED",
        blocker_kind=kind,
        blocker_digest=ONE,
        acceptance_passed=False,
        review_depth="DEEP",
    )
    return item


class CompilePortfolioTests(unittest.TestCase):
    def assert_rejected(self, source: dict) -> None:
        with self.assertRaises(review.ReviewError):
            review.compile_portfolio(source)

    def test_template_is_fresh_valid_and_compilation_does_not_mutate(self) -> None:
        first = review.template()
        second = review.template()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["handoffs"], second["handoffs"])
        original = copy.deepcopy(first)
        snapshot = review.compile_portfolio(first)
        self.assertEqual(first, original)
        self.assertEqual(snapshot["partitions"], {"ready": ["handoff-core"], "hold": [], "blocked": []})
        self.assertEqual(snapshot["review_handoff_ids"], ["handoff-core"])

    def test_normalizes_lists_and_uses_handoff_id_tie_breaking(self) -> None:
        source = portfolio(
            handoff("handoff-z", "root-z", writable_paths=["z/two.py", "z/one.py"]),
            handoff("handoff-a", "root-a"),
            handoff(
                "handoff-middle",
                "middle",
                depends_on=["root-z", "root-a"],
            ),
        )
        snapshot = review.compile_portfolio(source)
        self.assertEqual(
            [item["handoff_id"] for item in snapshot["handoffs"]],
            ["handoff-a", "handoff-middle", "handoff-z"],
        )
        self.assertEqual(snapshot["topological_order"], ["handoff-a", "handoff-z", "handoff-middle"])
        middle = snapshot["handoffs"][1]
        self.assertEqual(middle["depends_on"], ["root-a", "root-z"])
        self.assertEqual(snapshot["handoffs"][2]["writable_paths"], ["z/one.py", "z/two.py"])

    def test_fingerprint_is_canonical_complete_snapshot_without_itself(self) -> None:
        snapshot = review.compile_portfolio(review.template())
        payload = dict(snapshot)
        observed = payload.pop("snapshot_fingerprint")
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(observed, "sha256:" + hashlib.sha256(serialized).hexdigest())

    def test_exact_fields_identifiers_schema_and_capacity(self) -> None:
        cases = []
        extra = review.template()
        extra["extra"] = 1
        cases.append(extra)
        missing = review.template()
        del missing["portfolio_id"]
        cases.append(missing)
        bad_handoff = review.template()
        bad_handoff["handoffs"][0]["extra"] = 1
        cases.append(bad_handoff)
        for value in [True, 1.0, 2]:
            bad_schema = review.template()
            bad_schema["schema_version"] = value
            cases.append(bad_schema)
        for identifier in ["", "Upper", "two--hyphens", "trailing-", "a" * 65, "under_score"]:
            bad_identifier = review.template()
            bad_identifier["portfolio_id"] = identifier
            cases.append(bad_identifier)
        cases.append(portfolio())
        too_many = review.template()
        too_many["handoffs"] = [
            handoff(f"handoff-{index}", f"package-{index}") for index in range(33)
        ]
        cases.append(too_many)
        for case in cases:
            with self.subTest(case=case):
                self.assert_rejected(case)

    def test_status_evidence_and_derived_review_depth(self) -> None:
        valid = [
            handoff("ready-low", "ready-low"),
            handoff("ready-medium", "ready-medium", risk="medium", review_depth="STANDARD"),
            handoff("ready-high", "ready-high", risk="high", review_depth="DEEP"),
            handoff("ready-shared", "ready-shared", shared_interface=True, review_depth="DEEP"),
            handoff("ready-repair", "ready-repair", repair_count=1, review_depth="DEEP"),
            hold(handoff("hold", "hold")),
            blocked(handoff("blocked", "blocked")),
        ]
        snapshot = review.compile_portfolio(portfolio(*valid))
        self.assertEqual(snapshot["partitions"]["ready"], sorted(item["handoff_id"] for item in valid[:5]))
        self.assertEqual(snapshot["partitions"]["hold"], ["hold"])
        self.assertEqual(snapshot["partitions"]["blocked"], ["blocked"])

        invalid = []
        bad_ready = handoff("bad-ready", "bad-ready", acceptance_passed=False)
        invalid.append(bad_ready)
        bad_hold = hold(handoff("bad-hold", "bad-hold"), kind="missing-input")
        invalid.append(bad_hold)
        bad_blocked = blocked(handoff("bad-blocked", "bad-blocked"), kind="open-risk")
        invalid.append(bad_blocked)
        bad_depth = handoff("bad-depth", "bad-depth", risk="medium")
        invalid.append(bad_depth)
        for count in [True, -1, 4, 1.0]:
            invalid.append(handoff("bad-count", "bad-count", repair_count=count))
        for item in invalid:
            with self.subTest(item=item):
                self.assert_rejected(portfolio(item))

    def test_dependency_existence_cycles_and_state_propagation(self) -> None:
        unknown = portfolio(handoff("child", "child", depends_on=["missing"]))
        self.assert_rejected(unknown)
        self_dependency = portfolio(handoff("self", "self", depends_on=["self"]))
        self.assert_rejected(self_dependency)
        cycle = portfolio(
            handoff("one", "one", depends_on=["two"]),
            handoff("two", "two", depends_on=["one"]),
        )
        self.assert_rejected(cycle)

        blocked_chain = portfolio(
            blocked(handoff("root", "root")),
            hold(handoff("middle", "middle", depends_on=["root"])),
        )
        self.assert_rejected(blocked_chain)
        hold_chain = portfolio(
            hold(handoff("root", "root")),
            handoff("middle", "middle", depends_on=["root"]),
        )
        self.assert_rejected(hold_chain)
        valid_blocked_chain = portfolio(
            blocked(handoff("root", "root")),
            blocked(handoff("middle", "middle", depends_on=["root"])),
            blocked(handoff("leaf", "leaf", depends_on=["middle"])),
        )
        self.assertEqual(
            review.compile_portfolio(valid_blocked_chain)["partitions"]["blocked"],
            ["leaf", "middle", "root"],
        )

    def test_unique_handoff_and_package_ids(self) -> None:
        self.assert_rejected(portfolio(handoff("same", "one"), handoff("same", "two")))
        self.assert_rejected(portfolio(handoff("one", "same"), handoff("two", "same")))

    def test_rejects_unsafe_paths_and_global_case_insensitive_overlap(self) -> None:
        unsafe = [
            "",
            "/absolute",
            "C:relative",
            "C:/absolute",
            "../escape",
            "safe/../escape",
            "safe//file",
            "safe\\file",
            "safe/file:stream",
            "safe/trailing.",
            "safe/trailing ",
            "CON",
            "safe/com1.txt",
            "safe/LPT².log",
            "safe/\x00file",
            "safe/\ud800file",
        ]
        for path in unsafe:
            with self.subTest(path=path):
                self.assert_rejected(portfolio(handoff("bad", "bad", writable_paths=[path])))

        overlaps = [
            portfolio(handoff("one", "one", writable_paths=["src/A.py", "src/a.py"])),
            portfolio(
                handoff("one", "one", writable_paths=["src/core"]),
                handoff("two", "two", writable_paths=["SRC/core/main.py"]),
            ),
        ]
        for source in overlaps:
            self.assert_rejected(source)

    def test_executor_and_partition_outputs_are_sorted(self) -> None:
        snapshot = review.compile_portfolio(
            portfolio(
                handoff("z", "z", executor_id="z-executor"),
                handoff("a", "a", executor_id="a-executor"),
                handoff("m", "m", executor_id="z-executor"),
            )
        )
        self.assertEqual(list(snapshot["executors"]), ["a-executor", "z-executor"])
        self.assertEqual(snapshot["executors"]["z-executor"], ["m", "z"])


class CompareTests(unittest.TestCase):
    def test_compare_validates_both_snapshots_and_portfolio_identity(self) -> None:
        snapshot = review.compile_portfolio(review.template())
        for field, replacement in [
            ("snapshot_fingerprint", ONE),
            ("topological_order", []),
            ("review_handoff_ids", []),
            ("partitions", {"ready": [], "hold": [], "blocked": []}),
        ]:
            damaged = copy.deepcopy(snapshot)
            damaged[field] = replacement
            with self.subTest(field=field), self.assertRaises(review.ReviewError):
                review.compare(damaged, snapshot)

        other = review.compile_portfolio(portfolio(handoff("core", "core"), portfolio_id="other"))
        with self.assertRaises(review.ReviewError):
            review.compare(snapshot, other)

    def test_compare_reports_changes_state_direction_and_transitive_dependents(self) -> None:
        before_source = portfolio(
            handoff("root", "root", candidate_digest=ZERO),
            handoff("middle", "middle", depends_on=["root"]),
            handoff("leaf", "leaf", depends_on=["middle"]),
            handoff("removed", "removed"),
        )
        after_source = portfolio(
            hold(handoff("root", "root", candidate_digest=ONE)),
            hold(handoff("middle", "middle", depends_on=["root"])),
            hold(handoff("leaf", "leaf", depends_on=["middle"])),
            handoff("added", "added"),
        )
        before = review.compile_portfolio(before_source)
        after = review.compile_portfolio(after_source)
        result = review.compare(before, after)
        self.assertEqual(result["added_handoff_ids"], ["added"])
        self.assertEqual(result["removed_handoff_ids"], ["removed"])
        self.assertEqual(result["changed_handoff_ids"], ["leaf", "middle", "root"])
        self.assertEqual(result["state_regressions"], ["leaf", "middle", "root"])
        self.assertEqual(result["state_progressions"], [])
        self.assertEqual(result["affected_review_handoff_ids"], ["added", "leaf", "middle", "root"])

    def test_compare_marks_unchanged_transitive_dependents_as_affected(self) -> None:
        before = review.compile_portfolio(
            portfolio(
                handoff("root", "root", candidate_digest=ZERO),
                handoff("middle", "middle", depends_on=["root"]),
                handoff("leaf", "leaf", depends_on=["middle"]),
            )
        )
        after = review.compile_portfolio(
            portfolio(
                handoff("root", "root", candidate_digest=TWO),
                handoff("middle", "middle", depends_on=["root"]),
                handoff("leaf", "leaf", depends_on=["middle"]),
            )
        )
        result = review.compare(before, after)
        self.assertEqual(result["changed_handoff_ids"], ["root"])
        self.assertEqual(result["affected_review_handoff_ids"], ["leaf", "middle", "root"])

    def test_compare_progression_and_input_non_mutation(self) -> None:
        before = review.compile_portfolio(portfolio(blocked(handoff("core", "core"))))
        after = review.compile_portfolio(portfolio(handoff("core", "core", candidate_digest=ONE)))
        before_copy = copy.deepcopy(before)
        after_copy = copy.deepcopy(after)
        result = review.compare(before, after)
        self.assertEqual(result["state_progressions"], ["core"])
        self.assertEqual(result["state_regressions"], [])
        self.assertEqual(before, before_copy)
        self.assertEqual(after, after_copy)


if __name__ == "__main__":
    unittest.main()

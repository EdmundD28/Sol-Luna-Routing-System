from __future__ import annotations

import copy
import unittest

from opsworkbench.errors import WorkbenchError
from opsworkbench.schedule import Job, SchedulePlan, build_schedule, validate_graph


def job(identifier: str, *, depends_on=(), resources=(), disabled=False) -> dict:
    return {"id": identifier, "depends_on": list(depends_on), "resources": list(resources), "disabled": disabled}


class ScheduleAcceptance(unittest.TestCase):
    def error(self, code, path, operation):
        with self.assertRaises(WorkbenchError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.path, path)

    def test_A020_validate_graph_normalizes_sorted_collections(self):
        parsed = validate_graph([job("build", depends_on=("lint", "fetch"), resources=("gpu", "disk")), job("fetch"), job("lint")])
        self.assertEqual(parsed[0], Job("build", ("fetch", "lint"), ("disk", "gpu"), False))

    def test_A021_validate_graph_rejects_unknown_fields_and_bad_ids(self):
        self.error("UNKNOWN_FIELD", ("jobs", 0, "extra"), lambda: validate_graph([{**job("x"), "extra": 1}]))
        for value in ("", 2, None):
            with self.subTest(value=value):
                with self.assertRaises(WorkbenchError):
                    validate_graph([job(value)])

    def test_A022_validate_graph_rejects_duplicate_job_ids(self):
        self.error("DUPLICATE_JOB", ("jobs", 1, "id"), lambda: validate_graph([job("x"), job("x")]))

    def test_A023_validate_graph_rejects_duplicate_dependencies_and_resources(self):
        for raw in (job("x", depends_on=("a", "a")), job("x", resources=("gpu", "gpu"))):
            with self.subTest(raw=raw):
                with self.assertRaises(WorkbenchError):
                    validate_graph([raw, job("a")])

    def test_A024_validate_graph_rejects_unknown_dependency_at_exact_path(self):
        self.error("UNKNOWN_DEPENDENCY", ("jobs", "x", "depends_on", "missing"), lambda: validate_graph([job("x", depends_on=("missing",))]))

    def test_A025_validate_graph_rejects_self_dependency(self):
        self.error("SELF_DEPENDENCY", ("jobs", "x", "depends_on", "x"), lambda: validate_graph([job("x", depends_on=("x",))]))

    def test_A026_validate_graph_rejects_cycle_with_stable_members(self):
        with self.assertRaises(WorkbenchError) as caught:
            validate_graph([job("z", depends_on=("a",)), job("a", depends_on=("z",)), job("tail", depends_on=("z",))])
        self.assertEqual(caught.exception.code, "DEPENDENCY_CYCLE")
        self.assertEqual(caught.exception.details["members"], ("a", "z"))

    def test_A027_empty_schedule_is_empty(self):
        self.assertEqual(build_schedule([], 4), SchedulePlan((), ()))

    def test_A028_lexical_ready_jobs_fill_waves_to_cap(self):
        plan = build_schedule([job("d", depends_on=("a",)), job("c"), job("b"), job("a")], 2)
        self.assertEqual(plan.waves, (("a", "b"), ("c", "d")))

    def test_A029_dependencies_never_share_or_precede_their_parent_wave(self):
        plan = build_schedule([job("deploy", depends_on=("test",)), job("test", depends_on=("build",)), job("build")], 3)
        self.assertEqual(plan.waves, (("build",), ("test",), ("deploy",)))

    def test_A030_resource_conflicts_are_deferred_lexically(self):
        plan = build_schedule([job("a", resources=("gpu",)), job("b", resources=("gpu",)), job("c", resources=("cpu",))], 3)
        self.assertEqual(plan.waves, (("a", "c"), ("b",)))

    def test_A031_multiple_resources_block_any_overlap(self):
        plan = build_schedule([job("a", resources=("disk", "gpu")), job("b", resources=("gpu", "net")), job("c", resources=("cpu",))], 3)
        self.assertEqual(plan.waves, (("a", "c"), ("b",)))

    def test_A032_disabled_jobs_and_transitive_dependents_are_blocked(self):
        plan = build_schedule([job("seed", disabled=True), job("mid", depends_on=("seed",)), job("tail", depends_on=("mid",)), job("free")], 4)
        self.assertEqual(plan.blocked, ("mid", "seed", "tail"))
        self.assertEqual(plan.waves, (("free",),))

    def test_A033_dependency_on_blocked_job_does_not_block_unrelated_jobs(self):
        plan = build_schedule([job("off", disabled=True), job("needs", depends_on=("off",)), job("a"), job("b", depends_on=("a",))], 2)
        self.assertEqual(plan.blocked, ("needs", "off"))
        self.assertEqual(plan.waves, (("a",), ("b",)))

    def test_A034_max_parallel_rejects_bool_zero_negative_and_non_int(self):
        for value in (True, 0, -1, 1.5, "2"):
            with self.subTest(value=value):
                self.error("INVALID_LIMIT", ("max_parallel",), lambda value=value: build_schedule([], value))

    def test_A035_schedule_is_deterministic_under_input_permutation(self):
        raw = [job("c"), job("a"), job("b", depends_on=("a",))]
        self.assertEqual(build_schedule(raw, 2), build_schedule(list(reversed(raw)), 2))

    def test_A036_unicode_and_large_job_sets_preserve_lexical_order(self):
        raw = [job("雪"), job("月"), job("a")]
        self.assertEqual(build_schedule(raw, 3).waves, (("a", "月", "雪"),))

    def test_A037_schedule_does_not_mutate_or_alias_input(self):
        raw = [job("b", depends_on=("a",), resources=("gpu",)), job("a")]
        snapshot = copy.deepcopy(raw)
        plan = build_schedule(raw, 2)
        self.assertEqual(raw, snapshot)
        raw[0]["depends_on"].append("x")
        self.assertEqual(plan.waves, (("a",), ("b",)))

    def test_A038_models_and_nested_sequences_are_frozen(self):
        plan = build_schedule([job("a")], 1)
        with self.assertRaises(Exception):
            plan.waves += (("b",),)
        with self.assertRaises(Exception):
            plan.waves[0] += ("b",)

    def test_A067_large_leaf_portfolio_keeps_deterministic_semantics(self):
        raw_jobs = [job(f"job-{index:03d}") for index in range(80)]
        plan = build_schedule(list(reversed(raw_jobs)), 7)
        expected = tuple(tuple(f"job-{index:03d}" for index in range(start, min(start + 7, 80))) for start in range(0, 80, 7))
        self.assertEqual(plan.waves, expected)
        flattened = tuple(identifier for wave in plan.waves for identifier in wave)
        self.assertEqual(flattened, tuple(f"job-{index:03d}" for index in range(80)))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import copy
import dataclasses
import sys
import unittest
from pathlib import Path


def records():
    return [
        {"id": "fetch", "deps": [], "resources": ["net"], "cost": 2},
        {"id": "parse", "deps": ["fetch"], "resources": ["cpu"], "cost": 3},
        {"id": "lint", "deps": ["fetch"], "resources": ["cpu"], "cost": 1},
        {"id": "compile", "deps": ["parse"], "resources": ["cpu", "disk"], "cost": 5},
        {"id": "docs", "deps": ["parse"], "resources": ["disk"], "cost": 2},
        {"id": "package", "deps": ["compile", "docs"], "resources": ["disk"], "cost": 4},
    ]


class PlannerAcceptance(unittest.TestCase):
    def test_public_exports(self):
        expected = {
            "BuildPlanError", "TaskSpec", "BuildPlan", "normalize_tasks", "topological_order",
            "dependents_map", "impacted_tasks", "schedule_batches", "critical_path",
            "plan_build", "explain_plan",
        }
        self.assertTrue(expected.issubset(set(dir(buildkit))))

    def test_frozen_dataclasses_and_normalization(self):
        source = records()
        before = copy.deepcopy(source)
        normalized = buildkit.normalize_tasks(source)
        self.assertEqual(tuple(task.task_id for task in normalized), ("compile", "docs", "fetch", "lint", "package", "parse"))
        self.assertEqual(normalized[0].deps, ("parse",))
        self.assertEqual(normalized[0].resources, frozenset({"cpu", "disk"}))
        self.assertEqual(source, before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            normalized[0].cost = 99

    def test_empty_graph_and_empty_plan_identity(self):
        self.assertEqual(buildkit.normalize_tasks([]), ())
        self.assertEqual(buildkit.topological_order([]), ())
        self.assertEqual(buildkit.dependents_map([]), {})
        self.assertEqual(buildkit.impacted_tasks([], []), ())
        self.assertEqual(buildkit.schedule_batches([], [], 1), ())
        self.assertEqual(buildkit.critical_path([], []), ((), 0))
        plan = buildkit.plan_build([], [], 1)
        self.assertEqual(plan, buildkit.BuildPlan((), (), (), (), 0, 0))

    def test_record_shape_and_identifier_validation(self):
        invalid = [
            "bad", {"id": "a", "deps": [], "resources": [], "cost": 1},
            [{"id": "A", "deps": [], "resources": [], "cost": 1}],
            [{"id": "a", "deps": [], "resources": ["BAD"], "cost": 1}],
            [{"id": "a", "deps": [], "resources": [], "cost": True}],
            [{"id": "a", "deps": [], "resources": [], "cost": 0}],
            [{"id": "a", "deps": [], "resources": [], "cost": 1, "extra": 2}],
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                buildkit.normalize_tasks(value)

    def test_identifier_boundaries_and_resource_containers(self):
        maximum = "a" * 32
        normalized = buildkit.normalize_tasks([
            {"id": maximum, "deps": (), "resources": {"cpu", "disk"}, "cost": 1},
        ])
        self.assertEqual(normalized[0].task_id, maximum)
        self.assertEqual(normalized[0].resources, frozenset({"cpu", "disk"}))
        normalized = buildkit.normalize_tasks([
            {"id": "a", "deps": (), "resources": frozenset({"cpu"}), "cost": 1},
        ])
        self.assertEqual(normalized[0].resources, frozenset({"cpu"}))
        with self.assertRaises(ValueError):
            buildkit.normalize_tasks([
                {"id": "a" * 33, "deps": (), "resources": (), "cost": 1},
            ])

    def test_duplicate_task_dependency_and_resource_rejected(self):
        cases = [
            [
                {"id": "a", "deps": [], "resources": [], "cost": 1},
                {"id": "a", "deps": [], "resources": [], "cost": 1},
            ],
            [
                {"id": "a", "deps": [], "resources": [], "cost": 1},
                {"id": "b", "deps": ["a", "a"], "resources": [], "cost": 1},
            ],
            [{"id": "a", "deps": [], "resources": ["cpu", "cpu"], "cost": 1}],
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                buildkit.normalize_tasks(value)

    def test_missing_self_and_cycle_use_build_plan_error(self):
        cases = [
            [{"id": "a", "deps": ["missing"], "resources": [], "cost": 1}],
            [{"id": "a", "deps": ["a"], "resources": [], "cost": 1}],
            [
                {"id": "a", "deps": ["b"], "resources": [], "cost": 1},
                {"id": "b", "deps": ["a"], "resources": [], "cost": 1},
            ],
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(buildkit.BuildPlanError):
                buildkit.normalize_tasks(value)

    def test_topological_order_uses_lexicographic_ready_queue(self):
        self.assertEqual(buildkit.topological_order(records()), ("fetch", "lint", "parse", "compile", "docs", "package"))
        self.assertEqual(buildkit.topological_order(list(reversed(records()))), ("fetch", "lint", "parse", "compile", "docs", "package"))

    def test_normalized_tasks_are_accepted_by_graph_apis(self):
        normalized = buildkit.normalize_tasks(records())
        self.assertEqual(buildkit.topological_order(normalized)[0], "fetch")
        self.assertEqual(buildkit.dependents_map(normalized)["parse"], ("compile", "docs"))

    def test_dependents_map_contains_every_task(self):
        self.assertEqual(
            buildkit.dependents_map(records()),
            {
                "compile": ("package",), "docs": ("package",), "fetch": ("lint", "parse"),
                "lint": (), "package": (), "parse": ("compile", "docs"),
            },
        )

    def test_impact_empty_identity_and_transitive_closure(self):
        self.assertEqual(buildkit.impacted_tasks(records(), []), ())
        self.assertEqual(buildkit.impacted_tasks(records(), ["parse"]), ("parse", "compile", "docs", "package"))
        self.assertEqual(buildkit.impacted_tasks(records(), ["lint"]), ("lint",))

    def test_impact_uses_exact_changed_errors(self):
        with self.assertRaises(TypeError):
            buildkit.impacted_tasks(records(), "parse")
        with self.assertRaises(ValueError):
            buildkit.impacted_tasks(records(), ["parse", "parse"])
        with self.assertRaises(buildkit.BuildPlanError):
            buildkit.impacted_tasks(records(), ["missing"])

    def test_batches_empty_and_max_parallel_validation(self):
        self.assertEqual(buildkit.schedule_batches(records(), [], 2), ())
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                buildkit.schedule_batches(records(), ["parse"], value)

    def test_batches_respect_dependencies_and_capacity(self):
        selected = [task["id"] for task in records()]
        self.assertEqual(
            buildkit.schedule_batches(records(), selected, 2),
            (("fetch",), ("lint",), ("parse",), ("compile",), ("docs",), ("package",)),
        )
        self.assertTrue(all(len(batch) <= 2 for batch in buildkit.schedule_batches(records(), selected, 2)))

    def test_batches_treat_outside_dependencies_as_satisfied(self):
        self.assertEqual(buildkit.schedule_batches(records(), ["compile", "docs", "package"], 2), (("compile",), ("docs",), ("package",)))

    def test_batches_use_exact_selected_errors(self):
        with self.assertRaises(TypeError):
            buildkit.schedule_batches(records(), "parse", 2)
        with self.assertRaises(ValueError):
            buildkit.schedule_batches(records(), ["parse", "parse"], 2)
        with self.assertRaises(buildkit.BuildPlanError):
            buildkit.schedule_batches(records(), ["missing"], 2)

    def test_resource_conflicts_defer_without_starvation(self):
        tasks = [
            {"id": "a", "deps": [], "resources": ["cpu"], "cost": 1},
            {"id": "b", "deps": [], "resources": ["cpu"], "cost": 1},
            {"id": "c", "deps": [], "resources": ["disk"], "cost": 1},
        ]
        self.assertEqual(buildkit.schedule_batches(tasks, ["a", "b", "c"], 3), (("a", "c"), ("b",)))

    def test_critical_empty_and_single(self):
        self.assertEqual(buildkit.critical_path(records(), []), ((), 0))
        self.assertEqual(buildkit.critical_path(records(), ["parse"]), (("parse",), 3))

    def test_critical_path_cost_and_lexicographic_tie(self):
        self.assertEqual(buildkit.critical_path(records(), [task["id"] for task in records()]), (("fetch", "parse", "compile", "package"), 14))
        tasks = [
            {"id": "a", "deps": [], "resources": [], "cost": 1},
            {"id": "b", "deps": ["a"], "resources": [], "cost": 2},
            {"id": "c", "deps": ["a"], "resources": [], "cost": 2},
        ]
        self.assertEqual(buildkit.critical_path(tasks, ["a", "b", "c"]), (("a", "b"), 3))

    def test_critical_path_uses_exact_selected_errors(self):
        with self.assertRaises(TypeError):
            buildkit.critical_path(records(), "parse")
        with self.assertRaises(ValueError):
            buildkit.critical_path(records(), ["parse", "parse"])
        with self.assertRaises(buildkit.BuildPlanError):
            buildkit.critical_path(records(), ["missing"])

    def test_plan_build_complete_result(self):
        plan = buildkit.plan_build(records(), ["parse"], 2)
        self.assertEqual(plan.changed, ("parse",))
        self.assertEqual(plan.impacted, ("parse", "compile", "docs", "package"))
        self.assertEqual(plan.batches, (("parse",), ("compile",), ("docs",), ("package",)))
        self.assertEqual((plan.critical_path, plan.critical_cost, plan.total_cost), (("parse", "compile", "package"), 12, 14))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.total_cost = 0

    def test_plan_build_preserves_inputs(self):
        source = records()
        changed = ["parse"]
        before = (copy.deepcopy(source), copy.deepcopy(changed))
        buildkit.plan_build(source, changed, 2)
        self.assertEqual((source, changed), before)

    def test_explain_plan_exact_lines(self):
        plan = buildkit.plan_build(records(), ["parse"], 2)
        self.assertEqual(
            buildkit.explain_plan(plan),
            (
                "changed=parse", "impacted=parse,compile,docs,package", "batch[1]=parse",
                "batch[2]=compile", "batch[3]=docs", "batch[4]=package",
                "critical=parse,compile,package:12", "total_cost=14",
            ),
        )

    def test_explain_empty_and_wrong_type(self):
        self.assertEqual(buildkit.explain_plan(buildkit.plan_build([], [], 1)), ("changed=-", "impacted=-", "critical=-:0", "total_cost=0"))
        with self.assertRaises(TypeError):
            buildkit.explain_plan({})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args, rest = parser.parse_known_args()
    package_parent = Path(args.root).resolve() / "benchmarks" / "p061"
    sys.path.insert(0, str(package_parent))
    import buildkit
    unittest.main(argv=[sys.argv[0], *rest])

from __future__ import annotations

import copy
import unittest

from opsworkbench.errors import WorkbenchError
from opsworkbench.patches import build_patch_graph, plan_patch_waves, validate_patch


def patch(identifier, file="a.py", start=0, end=1, replacement="x", dependencies=()):
    return {"patch_id": identifier, "file": file, "start": start, "end": end, "replacement": replacement, "depends_on": list(dependencies)}


class PatchAcceptance(unittest.TestCase):
    def error(self, code, path, operation):
        with self.assertRaises(WorkbenchError) as caught:
            operation()
        self.assertEqual((caught.exception.code, caught.exception.path), (code, path))

    def test_A088_validation_accepts_unicode_and_large_offsets_and_is_frozen(self):
        parsed = validate_patch(patch("雪", file="月.py", start=10**50, end=10**50, replacement="π"), ("patches", 0))
        self.assertEqual((parsed.patch_id, parsed.file, parsed.start, parsed.replacement), ("雪", "月.py", 10**50, "π"))
        with self.assertRaises(Exception):
            parsed.start = 0

    def test_A089_validation_rejects_unknown_bool_negative_and_reverse_ranges(self):
        self.error("UNKNOWN_FIELD", ("patches", 1, "extra"), lambda: validate_patch({**patch("x"), "extra": 1}, ("patches", 1)))
        for raw, field in ((patch("x", start=True), "start"), (patch("x", start=-1), "start"), (patch("x", start=2, end=1), "end")):
            with self.subTest(raw=raw):
                self.error("INVALID_FIELD", ("patches", 0, field), lambda raw=raw: validate_patch(raw, ("patches", 0)))

    def test_A090_positive_ranges_overlap_only_with_strict_intersection(self):
        self.error("PATCH_OVERLAP", ("patches", "b", "range"), lambda: build_patch_graph([patch("a", start=0, end=3), patch("b", start=2, end=4)]))
        graph = build_patch_graph([patch("a", start=0, end=2), patch("b", start=2, end=4)])
        self.assertEqual(len(graph.nodes), 2)
        with self.assertRaises(Exception):
            graph.nodes += ()

    def test_A091_zero_width_rules_distinguish_same_boundary_and_edges(self):
        self.error("PATCH_DUPLICATE_BOUNDARY", ("patches", "b", "range"), lambda: build_patch_graph([patch("a", start=2, end=2), patch("b", start=2, end=2)]))
        build_patch_graph([patch("a", start=0, end=2), patch("b", start=2, end=2)])
        self.error("PATCH_OVERLAP", ("patches", "b", "range"), lambda: build_patch_graph([patch("a", start=0, end=3), patch("b", start=2, end=2)]))

    def test_A092_duplicate_ids_are_idempotent_or_conflicting(self):
        same = patch("a")
        self.assertEqual(len(build_patch_graph([same, copy.deepcopy(same)]).nodes), 1)
        self.error("DUPLICATE_PATCH", ("patches", 1), lambda: build_patch_graph([same, patch("a", replacement="y")]))

    def test_A093_missing_dependency_and_cycle_are_structured(self):
        self.error("MISSING_DEPENDENCY", ("patches", 0, "depends_on", 0), lambda: build_patch_graph([patch("a", dependencies=["missing"])]))
        with self.assertRaises(WorkbenchError) as caught:
            plan_patch_waves([patch("a", dependencies=["b"]), patch("b", dependencies=["a"])])
        self.assertEqual((caught.exception.code, caught.exception.path, caught.exception.details["members"]), ("DEPENDENCY_CYCLE", ("patches", "dependencies"), ("a", "b")))

    def test_A094_different_files_share_a_wave_and_same_file_serializes(self):
        plan = plan_patch_waves([patch("b", file="b.py"), patch("a", file="a.py"), patch("c", file="a.py", start=2, end=3)])
        self.assertEqual(plan.waves, (("a", "b"), ("c",)))
        with self.assertRaises(TypeError):
            plan.waves[0][0] = "x"

    def test_A095_dependencies_force_later_waves_across_files(self):
        plan = plan_patch_waves([patch("b", file="b.py", dependencies=["a"]), patch("a", file="a.py")])
        self.assertEqual(plan.waves, (("a",), ("b",)))

    def test_A096_empty_plan_and_input_order_are_deterministic(self):
        self.assertEqual(plan_patch_waves([]).waves, ())
        left = plan_patch_waves([patch("b", file="b"), patch("a", file="a")])
        right = plan_patch_waves([patch("a", file="a"), patch("b", file="b")])
        self.assertEqual(left, right)

    def test_A097_operations_do_not_mutate_inputs(self):
        raw = [patch("a", replacement="雪"), patch("b", file="b", dependencies=["a"])]
        before = copy.deepcopy(raw)
        build_patch_graph(raw)
        plan_patch_waves(raw)
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()

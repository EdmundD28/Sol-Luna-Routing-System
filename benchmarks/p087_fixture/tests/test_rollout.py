from __future__ import annotations

import copy
import unittest

from common import plain
from opsworkbench.errors import WorkbenchError
from opsworkbench.rollout import assign_rollout, validate_rollout_request, validate_target


def target(identifier, **changes):
    value = {"target_id": identifier, "region": "us", "ring": 0, "eligible": True, "enabled": True, "anti_affinity": None, "depends_on": []}
    value.update(changes)
    return value


def request(**changes):
    value = {"rings": [0], "max_per_wave": 2, "regional_quota": {"us": 2}, "allow_spillover": True}
    value.update(changes)
    return value


class RolloutAcceptance(unittest.TestCase):
    def test_A098_validation_normalizes_and_freezes_request(self):
        parsed = validate_rollout_request(request(rings=[2, 0], regional_quota={"月": 10**50, "us": 1}))
        self.assertEqual(parsed.rings, (0, 2))
        self.assertEqual(plain(parsed.regional_quota), {"us": 1, "月": 10**50})
        with self.assertRaises(TypeError):
            parsed.regional_quota["x"] = 1

    def test_A099_validation_rejects_unknown_bool_duplicate_ring_and_zero_quota(self):
        with self.assertRaises(WorkbenchError) as unknown:
            validate_target({**target("x"), "extra": 1}, ("rollout", "targets", 0))
        self.assertEqual(unknown.exception.path, ("rollout", "targets", 0, "extra"))
        for raw, path in ((request(max_per_wave=True), ("rollout", "request", "max_per_wave")), (request(rings=[0, 0]), ("rollout", "request", "rings", 1)), (request(regional_quota={"us": 0}), ("rollout", "request", "regional_quota", "us"))):
            with self.subTest(raw=raw):
                with self.assertRaises(WorkbenchError) as caught:
                    validate_rollout_request(raw)
                self.assertEqual((caught.exception.code, caught.exception.path), ("INVALID_FIELD", path))

    def test_A100_ring_order_dependencies_and_lexical_members_are_stable(self):
        plan = assign_rollout([target("b", ring=1, depends_on=["a"]), target("a", ring=0), target("c", ring=0)], request(rings=[1, 0]))
        self.assertEqual([(w.ring, w.index, w.target_ids) for w in plan.waves], [(0, 0, ("a", "c")), (1, 0, ("b",))])
        with self.assertRaises(TypeError):
            plan.waves[0].target_ids[0] = "x"
        with self.assertRaises(Exception):
            plan.waves += ()

    def test_A101_disabled_ineligible_and_missing_ring_use_precedence(self):
        plan = assign_rollout([target("a", enabled=False, eligible=False), target("b", eligible=False), target("c", ring=2)], request())
        self.assertEqual([(b.target_id, b.reason) for b in plan.blocked], [("a", "DISABLED"), ("b", "INELIGIBLE"), ("c", "RING_DISABLED")])

    def test_A102_unknown_same_ring_and_blocked_dependencies_are_blocked(self):
        plan = assign_rollout([target("a", depends_on=["missing"]), target("b", depends_on=["c"]), target("c"), target("d", ring=1, depends_on=["a"])], request(rings=[0, 1]))
        self.assertEqual(dict((b.target_id, b.reason) for b in plan.blocked), {"a": "MISSING_DEPENDENCY", "b": "DEPENDENCY_BLOCKED", "d": "DEPENDENCY_BLOCKED"})

    def test_A103_spillover_creates_more_waves_and_none_affinity_never_conflicts(self):
        plan = assign_rollout([target("a"), target("b"), target("c")], request(max_per_wave=1, regional_quota={"us": 1}, allow_spillover=True))
        self.assertEqual([w.target_ids for w in plan.waves], [("a",), ("b",), ("c",)])
        self.assertEqual(plan.blocked, ())

    def test_A104_no_spillover_reports_capacity_quota_and_affinity(self):
        capacity = assign_rollout([target("a"), target("b")], request(max_per_wave=1, regional_quota={"us": 2}, allow_spillover=False))
        self.assertEqual(capacity.blocked[0].reason, "WAVE_CAPACITY")
        quota = assign_rollout([target("a", region="eu")], request(regional_quota={"us": 2}, allow_spillover=False))
        self.assertEqual(quota.blocked[0].reason, "REGIONAL_QUOTA")
        affinity = assign_rollout([target("a", anti_affinity="rack"), target("b", anti_affinity="rack")], request(max_per_wave=3, allow_spillover=False))
        self.assertEqual(affinity.blocked[0].reason, "ANTI_AFFINITY")

    def test_A105_spillover_zero_capacity_terminates_as_regional_quota(self):
        plan = assign_rollout([target("雪", region="eu")], request(regional_quota={"us": 1}, allow_spillover=True))
        self.assertEqual([(b.target_id, b.reason) for b in plan.blocked], [("雪", "REGIONAL_QUOTA")])

    def test_A106_duplicate_targets_are_idempotent_or_conflicting(self):
        same = target("a")
        self.assertEqual(assign_rollout([same, copy.deepcopy(same)], request()).waves[0].target_ids, ("a",))
        with self.assertRaises(WorkbenchError) as caught:
            assign_rollout([same, target("a", region="eu")], request())
        self.assertEqual((caught.exception.code, caught.exception.path), ("DUPLICATE_TARGET", ("rollout", "targets", 1)))

    def test_A107_empty_and_input_alias_safety(self):
        self.assertEqual(assign_rollout([], request()).waves, ())
        raw = [target("a", depends_on=[])]
        before = copy.deepcopy(raw)
        assign_rollout(raw, request())
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()

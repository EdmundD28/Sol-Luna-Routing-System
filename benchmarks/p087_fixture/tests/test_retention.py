from __future__ import annotations

import copy
import unittest

from opsworkbench.errors import WorkbenchError
from opsworkbench.retention import apply_retention, validate_legal_hold, validate_retention_policy, validate_snapshot


def snapshot(identifier, created, **changes):
    value = {"snapshot_id": identifier, "channel": "stable", "created_at": created, "tags": [], "healthy": True, "size_bytes": 10}
    value.update(changes)
    return value


def policy(**changes):
    value = {"keep_last": 1, "max_age": 10, "protected_tags": []}
    value.update(changes)
    return value


class RetentionAcceptance(unittest.TestCase):
    def test_A108_validation_normalizes_tags_and_rejects_bool_integer(self):
        parsed = validate_snapshot(snapshot("雪", 10, tags=["z", "a"]), ("retention", "snapshots", 0))
        self.assertEqual(parsed.tags, ("a", "z"))
        with self.assertRaises(WorkbenchError) as caught:
            validate_snapshot(snapshot("x", True), ("retention", "snapshots", 0))
        self.assertEqual((caught.exception.code, caught.exception.path), ("INVALID_FIELD", ("retention", "snapshots", 0, "created_at")))

    def test_A109_policy_and_hold_validation_reject_unknown_or_empty(self):
        with self.assertRaises(WorkbenchError) as policy_error:
            validate_retention_policy({**policy(), "extra": 1})
        self.assertEqual((policy_error.exception.code, policy_error.exception.path), ("UNKNOWN_FIELD", ("retention", "policy", "extra")))
        with self.assertRaises(WorkbenchError) as hold_error:
            validate_legal_hold({"snapshot_id": "x", "reason": ""})
        self.assertEqual((hold_error.exception.code, hold_error.exception.path), ("INVALID_FIELD", ("retention", "holds", "reason")))

    def test_A110_keep_last_is_per_channel_with_lexical_tie_break(self):
        items = [snapshot("b", 5), snapshot("a", 5), snapshot("beta", 1, channel="beta")]
        plan = apply_retention(items, [], policy(keep_last=1, max_age=0), 20)
        reasons = {d.snapshot_id: (d.action, d.reason) for d in plan.decisions}
        self.assertEqual(reasons, {"a": ("keep", "KEEP_LAST"), "b": ("delete", "AGE_EXCEEDED"), "beta": ("keep", "KEEP_LAST")})
        with self.assertRaises(TypeError):
            plan.decisions[0] = plan.decisions[0]
        with self.assertRaises(Exception):
            plan.decisions += ()

    def test_A111_age_boundary_and_none_age_are_kept(self):
        boundary = apply_retention([snapshot("a", 90), snapshot("b", 100)], [], policy(keep_last=0, max_age=10), 100)
        self.assertEqual([d.reason for d in boundary.decisions], ["WITHIN_AGE", "WITHIN_AGE"])
        unlimited = apply_retention([snapshot("a", 0)], [], policy(keep_last=0, max_age=None), 10**100)
        self.assertEqual(unlimited.decisions[0].reason, "WITHIN_AGE")

    def test_A112_hold_and_protected_tag_precede_other_rules(self):
        items = [snapshot("held", 0), snapshot("tagged", 0, tags=["keep"]), snapshot("new", 100)]
        holds = [{"snapshot_id": "held", "reason": "audit"}]
        plan = apply_retention(items, holds, policy(protected_tags=["keep"]), 100)
        reasons = {d.snapshot_id: d.reason for d in plan.decisions}
        self.assertEqual(reasons["held"], "LEGAL_HOLD")
        self.assertEqual(reasons["tagged"], "PROTECTED_TAG")

    def test_A113_only_healthy_old_snapshot_is_never_deleted(self):
        items = [snapshot("healthy", 0), snapshot("bad", 1, healthy=False), snapshot("newbad", 100, healthy=False)]
        plan = apply_retention(items, [], policy(keep_last=0, max_age=10), 100)
        reasons = {d.snapshot_id: (d.action, d.reason) for d in plan.decisions}
        self.assertEqual(reasons["healthy"], ("keep", "ONLY_HEALTHY"))
        self.assertEqual(reasons["bad"], ("delete", "AGE_EXCEEDED"))

    def test_A114_duplicate_snapshots_and_holds_are_deterministic(self):
        same = snapshot("a", 0)
        self.assertEqual(len(apply_retention([same, copy.deepcopy(same)], [], policy(), 0).decisions), 1)
        with self.assertRaises(WorkbenchError) as duplicate:
            apply_retention([same, snapshot("a", 1)], [], policy(), 0)
        self.assertEqual((duplicate.exception.code, duplicate.exception.path), ("DUPLICATE_SNAPSHOT", ("retention", "snapshots", 1)))
        with self.assertRaises(WorkbenchError) as hold:
            apply_retention([same], [{"snapshot_id": "a", "reason": "one"}, {"snapshot_id": "a", "reason": "two"}], policy(), 0)
        self.assertEqual((hold.exception.code, hold.exception.path), ("DUPLICATE_HOLD", ("retention", "holds", 1)))

    def test_A115_missing_hold_target_is_structured(self):
        with self.assertRaises(WorkbenchError) as caught:
            apply_retention([], [{"snapshot_id": "missing", "reason": "audit"}], policy(), 0)
        self.assertEqual((caught.exception.code, caught.exception.path), ("MISSING_SNAPSHOT", ("retention", "holds", 0, "snapshot_id")))

    def test_A116_decision_order_is_channel_time_id_and_unicode_safe(self):
        items = [snapshot("雪", 2, channel="月"), snapshot("b", 2), snapshot("a", 1)]
        plan = apply_retention(items, [], policy(keep_last=2, max_age=None), 3)
        self.assertEqual([d.snapshot_id for d in plan.decisions], ["a", "b", "雪"])

    def test_A117_empty_and_input_alias_safety(self):
        self.assertEqual(apply_retention([], [], policy(), 0).decisions, ())
        raw = [snapshot("a", 0, tags=["x"])]
        before = copy.deepcopy(raw)
        apply_retention(raw, [], policy(), 0)
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import unittest

from common import plain
from opsworkbench.cache import plan_eviction, resolve_cache, validate_cache_entry, validate_cache_request
from opsworkbench.errors import WorkbenchError


def entry(key, **changes):
    value = {"key": key, "value": {"key": key}, "created_at": 0, "expires_at": 100, "size_bytes": 10, "dependencies": [], "last_access": 0, "pinned": False}
    value.update(changes)
    return value


def request(key="build", **changes):
    value = {"key": key, "now": 10, "allow_prefix": True}
    value.update(changes)
    return value


class CacheAcceptance(unittest.TestCase):
    def error(self, code, path, operation):
        with self.assertRaises(WorkbenchError) as caught:
            operation()
        self.assertEqual((caught.exception.code, caught.exception.path), (code, path))

    def test_A078_validation_freezes_value_and_rejects_bool_integer(self):
        raw = entry("雪", value={"items": [1]})
        parsed = validate_cache_entry(raw, ("cache", 0))
        raw["value"]["items"].append(2)
        self.assertEqual(plain(parsed.value), {"items": [1]})
        with self.assertRaises(TypeError):
            parsed.value["items"][0] = 2
        self.error("INVALID_FIELD", ("cache", 0, "size_bytes"), lambda: validate_cache_entry(entry("x", size_bytes=True), ("cache", 0)))

    def test_A079_exact_hit_precedes_longer_prefix(self):
        hit = resolve_cache([entry("build"), entry("build/linux", value="prefix")], request())
        self.assertEqual((hit.entry.key, hit.match), ("build", "exact"))
        with self.assertRaises(TypeError):
            hit.entry.value["key"] = "changed"

    def test_A080_invalid_exact_falls_back_to_longest_valid_prefix(self):
        entries = [entry("build", expires_at=10), entry("build/a"), entry("build/a/deep", value="deep")]
        hit = resolve_cache(entries, request(now=10))
        self.assertEqual((hit.entry.key, hit.match), ("build/a/deep", "prefix"))

    def test_A081_expiry_boundary_and_disabled_prefix_return_none(self):
        self.assertIsNone(resolve_cache([entry("build", expires_at=10)], request(now=10)))
        self.assertIsNone(resolve_cache([entry("build/x")], request(allow_prefix=False)))

    def test_A082_dependency_invalidation_is_transitive(self):
        entries = [entry("base", expires_at=5), entry("mid", dependencies=["base"]), entry("top", dependencies=["mid"])]
        self.assertIsNone(resolve_cache(entries, request("top", now=10)))

    def test_A083_missing_dependency_cycle_and_duplicate_conflict_are_errors(self):
        self.error("MISSING_DEPENDENCY", ("cache", 0, "dependencies", 0), lambda: resolve_cache([entry("x", dependencies=["missing"])], request("x")))
        with self.assertRaises(WorkbenchError) as cycle:
            resolve_cache([entry("a", dependencies=["b"]), entry("b", dependencies=["a"])], request("a"))
        self.assertEqual((cycle.exception.code, cycle.exception.path, plain(cycle.exception.details)), ("DEPENDENCY_CYCLE", ("cache", "dependencies"), {"members": ["a", "b"]}))
        with self.assertRaises(WorkbenchError) as duplicate:
            resolve_cache([entry("x"), entry("x", size_bytes=11)], request("x"))
        self.assertEqual((duplicate.exception.code, duplicate.exception.path), ("DUPLICATE_CACHE_ENTRY", ("cache", 1)))

    def test_A084_eviction_removes_expired_then_lru_with_lexical_tie(self):
        entries = [entry("expired", expires_at=5, size_bytes=4), entry("b", last_access=1, size_bytes=5), entry("a", last_access=1, size_bytes=5), entry("new", last_access=9, size_bytes=5)]
        plan = plan_eviction(entries, 10, 10)
        self.assertEqual(plan.delete_keys, ("a", "expired"))
        self.assertEqual((plan.retained_keys, plan.bytes_freed), (("b", "new"), 9))
        with self.assertRaises(Exception):
            plan.delete_keys += ("x",)

    def test_A085_pinned_entries_survive_even_expired_and_can_make_budget_impossible(self):
        pinned = [entry("p", pinned=True, expires_at=1, size_bytes=11)]
        self.error("IMPOSSIBLE_BUDGET", (), lambda: plan_eviction(pinned, 10, 20))
        self.assertEqual(plan_eviction(pinned, 11, 20).retained_keys, ("p",))

    def test_A086_empty_cache_and_large_integer_budget_are_supported(self):
        self.assertEqual(plan_eviction([], 10**100, 0).delete_keys, ())
        self.assertIsNone(resolve_cache([], request()))

    def test_A087_request_validation_and_operations_preserve_inputs(self):
        self.error("UNKNOWN_FIELD", ("request", "extra"), lambda: validate_cache_request({**request(), "extra": 1}))
        entries = [entry("build", value={"月": [1]})]
        before = copy.deepcopy(entries)
        resolve_cache(entries, request())
        plan_eviction(entries, 20, 10)
        self.assertEqual(entries, before)


if __name__ == "__main__":
    unittest.main()

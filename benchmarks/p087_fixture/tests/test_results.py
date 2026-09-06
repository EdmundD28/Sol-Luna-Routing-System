from __future__ import annotations

import copy
import math
import unittest

from opsworkbench.errors import WorkbenchError
from opsworkbench.results import CaseResult, Regression, aggregate_results, compare_snapshots, normalize_result


def result(case_id: str, attempt: int = 1, status: str = "pass", duration_ms=1, finished_at: str = "2026-01-01T00:00:00Z") -> dict:
    return {"case_id": case_id, "attempt": attempt, "status": status, "duration_ms": duration_ms, "finished_at": finished_at}


class ResultsAcceptance(unittest.TestCase):
    def error(self, code, path, operation):
        with self.assertRaises(WorkbenchError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.path, path)

    def test_A039_normalize_result_returns_typed_record(self):
        self.assertEqual(normalize_result(result("case")), CaseResult("case", 1, "pass", 1, "2026-01-01T00:00:00Z"))

    def test_A040_normalize_result_rejects_unknown_and_missing_fields(self):
        self.error("UNKNOWN_FIELD", ("results", 2, "extra"), lambda: normalize_result({**result("x"), "extra": 1}, 2))
        raw = result("x")
        del raw["status"]
        self.error("MISSING_FIELD", ("results", 0, "status"), lambda: normalize_result(raw, 0))

    def test_A041_case_id_and_finished_at_are_nonempty_strings(self):
        for raw in (result(""), result("x", finished_at=""), result(3), result("x", finished_at=4)):
            with self.subTest(raw=raw):
                with self.assertRaises(WorkbenchError):
                    normalize_result(raw)

    def test_A042_attempt_is_positive_integer_not_bool(self):
        for value in (True, 0, -1, 1.5, "2"):
            with self.subTest(value=value):
                self.error("INVALID_ATTEMPT", ("results", 0, "attempt"), lambda value=value: normalize_result(result("x", attempt=value)))

    def test_A043_status_is_closed_enum(self):
        for status in ("pass", "fail", "error", "skip"):
            self.assertEqual(normalize_result(result("x", status=status)).status, status)
        self.error("INVALID_STATUS", ("results", 0, "status"), lambda: normalize_result(result("x", status="unknown")))

    def test_A044_duration_is_finite_nonnegative_numeric_not_bool(self):
        for value in (True, -1, math.nan, math.inf, "1"):
            with self.subTest(value=value):
                self.error("INVALID_DURATION", ("results", 0, "duration_ms"), lambda value=value: normalize_result(result("x", duration_ms=value)))
        huge = 10**100
        self.assertEqual(normalize_result(result("x", duration_ms=huge)).duration_ms, huge)

    def test_A045_empty_aggregate_has_complete_zero_counts(self):
        snapshot = aggregate_results([])
        self.assertEqual(snapshot.cases, ())
        self.assertEqual(dict(snapshot.counts), {"pass": 0, "fail": 0, "error": 0, "skip": 0})
        self.assertEqual(snapshot.total_duration_ms, 0)

    def test_A046_aggregate_selects_greatest_attempt(self):
        snapshot = aggregate_results([result("x", 2, "pass", 3), result("x", 1, "fail", 10)])
        self.assertEqual(snapshot.cases, (CaseResult("x", 2, "pass", 3, "2026-01-01T00:00:00Z"),))

    def test_A047_equal_attempt_selects_latest_finished_at(self):
        snapshot = aggregate_results([result("x", 1, "fail", 4, "2026-01-01T00:00:00Z"), result("x", 1, "pass", 2, "2026-01-02T00:00:00Z")])
        self.assertEqual(snapshot.cases[0].status, "pass")

    def test_A048_exact_duplicate_record_is_idempotent(self):
        raw = result("x", 1, "pass", 2)
        self.assertEqual(aggregate_results([raw, copy.deepcopy(raw)]), aggregate_results([raw]))

    def test_A049_conflicting_same_identity_is_rejected(self):
        first = result("x", 1, "pass", 2)
        second = result("x", 1, "fail", 2)
        self.error("DUPLICATE_ATTEMPT", ("results", 1), lambda: aggregate_results([first, second]))

    def test_A050_cases_counts_and_total_use_selected_records_only(self):
        snapshot = aggregate_results([result("b", 1, "fail", 5), result("a", 1, "pass", 2), result("b", 2, "error", 7)])
        self.assertEqual([case.case_id for case in snapshot.cases], ["a", "b"])
        self.assertEqual(dict(snapshot.counts), {"pass": 1, "fail": 0, "error": 1, "skip": 0})
        self.assertEqual(snapshot.total_duration_ms, 9)

    def test_A051_unicode_large_integer_and_fractional_duration_survive(self):
        huge = 10**100
        snapshot = aggregate_results([result("雪", duration_ms=huge), result("月", duration_ms=0.25)])
        self.assertEqual(snapshot.cases[0].duration_ms, 0.25)
        self.assertEqual(snapshot.cases[1].duration_ms, huge)
        self.assertEqual([case.case_id for case in snapshot.cases], ["月", "雪"])
        fractional = aggregate_results([result("a", duration_ms=0.25), result("b", duration_ms=0.5)])
        self.assertEqual(fractional.total_duration_ms, 0.75)

    def test_A052_aggregate_does_not_mutate_or_alias_input(self):
        raw = [result("x")]
        before = copy.deepcopy(raw)
        snapshot = aggregate_results(raw)
        self.assertEqual(raw, before)
        raw[0]["status"] = "error"
        self.assertEqual(snapshot.cases[0].status, "pass")

    def test_A053_compare_returns_only_status_worsening_sorted_by_case(self):
        before = aggregate_results([result("z", status="pass"), result("a", status="skip"), result("same", status="fail")])
        after = aggregate_results([result("z", status="error", duration_ms=4), result("a", status="pass"), result("same", status="fail")])
        self.assertEqual(compare_snapshots(before, after), (Regression("z", "pass", "error", 3),))

    def test_A054_compare_includes_new_fail_or_error_but_not_new_pass_skip(self):
        before = aggregate_results([])
        after = aggregate_results([result("a", status="pass"), result("b", status="skip"), result("c", status="fail"), result("d", status="error")])
        regressions = compare_snapshots(before, after)
        self.assertEqual([(r.case_id, r.before_status, r.after_status) for r in regressions], [("c", None, "fail"), ("d", None, "error")])

    def test_A055_compare_ignores_removed_cases_and_improvements(self):
        before = aggregate_results([result("gone", status="error"), result("better", status="fail")])
        after = aggregate_results([result("better", status="pass")])
        self.assertEqual(compare_snapshots(before, after), ())

    def test_A056_compare_is_deterministic_and_does_not_mutate_snapshots(self):
        before = aggregate_results([result("b"), result("a")])
        after = aggregate_results([result("a", status="fail"), result("b", status="error")])
        original = before.cases
        self.assertEqual(compare_snapshots(before, after), compare_snapshots(before, after))
        self.assertIs(before.cases, original)

    def test_A057_models_and_counts_are_deeply_frozen(self):
        snapshot = aggregate_results([result("x")])
        with self.assertRaises(Exception):
            snapshot.cases += ()
        with self.assertRaises(TypeError):
            snapshot.counts["pass"] = 9


if __name__ == "__main__":
    unittest.main()

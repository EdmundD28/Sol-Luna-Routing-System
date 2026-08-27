from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "allowance_meter.py"
SPEC = importlib.util.spec_from_file_location("allowance_meter", SCRIPT)
assert SPEC and SPEC.loader
METER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METER)


def record(
    route: str,
    *,
    before: float,
    after: float,
    elapsed: float,
    uncertainty: float = 1,
    pair_id: str = "pair-001",
    arm_position: int | None = None,
) -> dict:
    result = METER.template()
    result.update(
        {
            "pair_id": pair_id,
            "route": route,
            "route_revision": "sol-only-control-v1" if route == "SOL_ONLY" else "v0.1.1",
            "arm_position": arm_position or (1 if route == "SOL_ONLY" else 2),
            "elapsed_seconds": elapsed,
            "evidence_digest": "sha256:" + ("1" if route == "SOL_ONLY" else "2") * 64,
        }
    )
    position = result["arm_position"]
    for limit in result["limits"].values():
        limit.update(
            {
                "before_observed_at": (
                    "2026-08-28T00:00:00+10:00" if position == 1 else "2026-08-28T00:10:00+10:00"
                ),
                "after_observed_at": (
                    "2026-08-28T00:10:00+10:00" if position == 1 else "2026-08-28T00:20:00+10:00"
                ),
                "window_reset_at": "2026-08-28T02:52:00+10:00",
                "before_remaining_percent": before,
                "after_remaining_percent": after,
                "reading_uncertainty_percentage_points": uncertainty,
            }
        )
    return result


class AllowanceMeterTests(unittest.TestCase):
    def test_conservative_interval_requires_quality_allowance_and_time(self) -> None:
        result = METER.assess(
            [record("SOL_ONLY", before=100, after=60, elapsed=100), record("SOL_LUNA", before=60, after=55, elapsed=80)],
            minimum_advantage_multiple=5,
            minimum_pairs=2,
        )
        pair = result["pairs"][0]
        self.assertEqual(pair["limits"]["five_hour"]["sol_only"]["minimum_consumption_percentage_points"], 38)
        self.assertEqual(pair["limits"]["five_hour"]["sol_luna"]["maximum_consumption_percentage_points"], 7)
        self.assertGreater(
            pair["limits"]["five_hour"]["advantage"]["conservative_advantage_multiple_lower_bound"],
            5,
        )
        self.assertEqual(pair["status"], "PASS")
        self.assertEqual(result["campaign_status"], "HOLD")
        self.assertIn("insufficient_predeclared_pairs", result["campaign"]["reasons"])
        self.assertFalse(result["automatic_routing_allowed"])

    def test_integer_meter_can_be_too_coarse_to_decide(self) -> None:
        result = METER.assess(
            [record("SOL_ONLY", before=100, after=99, elapsed=100), record("SOL_LUNA", before=99, after=99, elapsed=80)],
            minimum_advantage_multiple=10,
            minimum_pairs=2,
        )
        pair = result["pairs"][0]
        self.assertEqual(
            pair["limits"]["five_hour"]["advantage"]["conservative_advantage_multiple_lower_bound"],
            0,
        )
        self.assertIn("conservative_allowance_advantage_below_floor", pair["reasons"])

    def test_credit_win_does_not_hide_elapsed_regression(self) -> None:
        result = METER.assess(
            [record("SOL_ONLY", before=100, after=60, elapsed=100), record("SOL_LUNA", before=60, after=55, elapsed=101)],
            minimum_advantage_multiple=5,
            minimum_pairs=2,
        )
        pair = result["pairs"][0]
        self.assertTrue(pair["allowance_improved"])
        self.assertFalse(pair["elapsed_improved"])
        self.assertEqual(pair["status"], "HOLD")

    def test_quality_regression_holds_even_when_allowance_and_time_win(self) -> None:
        sol = record("SOL_ONLY", before=100, after=60, elapsed=100)
        luna = record("SOL_LUNA", before=60, after=55, elapsed=80)
        luna["defects"] = 1
        result = METER.assess([sol, luna], minimum_advantage_multiple=5, minimum_pairs=2)
        self.assertIn("quality_gate_failed", result["pairs"][0]["reasons"])

    def test_rejects_reset_or_increasing_allowance(self) -> None:
        source = record("SOL_ONLY", before=10, after=100, elapsed=100)
        with self.assertRaisesRegex(METER.AllowanceError, "reset or inconsistent"):
            METER.validate_record(source)

    def test_rejects_cross_reset_and_naive_timestamps(self) -> None:
        source = record("SOL_ONLY", before=100, after=60, elapsed=100)
        source["limits"]["five_hour"]["after_observed_at"] = "2026-08-28T02:52:00+10:00"
        with self.assertRaisesRegex(METER.AllowanceError, "reset boundary"):
            METER.validate_record(source)
        source = record("SOL_ONLY", before=100, after=60, elapsed=100)
        source["limits"]["five_hour"]["before_observed_at"] = "2026-08-28T00:00:00"
        with self.assertRaisesRegex(METER.AllowanceError, "UTC offset"):
            METER.validate_record(source)

    def test_rejects_unknown_fields_and_token_substitution(self) -> None:
        source = record("SOL_ONLY", before=100, after=60, elapsed=100)
        source["total_tokens"] = 1000
        with self.assertRaisesRegex(METER.AllowanceError, "unsupported fields"):
            METER.validate_record(source)
        source = record("SOL_ONLY", before=100, after=60, elapsed=100)
        source["limits"]["five_hour"]["credit_value"] = 10
        with self.assertRaisesRegex(METER.AllowanceError, "unsupported fields"):
            METER.validate_record(source)

    def test_requires_both_limits_and_clean_shared_pool(self) -> None:
        source = record("SOL_ONLY", before=100, after=60, elapsed=100)
        del source["limits"]["weekly"]
        with self.assertRaisesRegex(METER.AllowanceError, "exactly five_hour and weekly"):
            METER.validate_record(source)
        source = record("SOL_ONLY", before=100, after=60, elapsed=100)
        source["contamination_status"] = "UNKNOWN"
        with self.assertRaisesRegex(METER.AllowanceError, "no other shared usage"):
            METER.validate_record(source)

    def test_rejects_incomparable_batch_size_and_duplicate_arms(self) -> None:
        sol = record("SOL_ONLY", before=100, after=60, elapsed=100)
        luna = record("SOL_LUNA", before=60, after=55, elapsed=80)
        luna["batch_size"] = 2
        with self.assertRaisesRegex(METER.AllowanceError, "batch_size differs"):
            METER.assess([sol, luna], minimum_advantage_multiple=5, minimum_pairs=2)
        luna["batch_size"] = 1
        with self.assertRaisesRegex(METER.AllowanceError, "duplicate"):
            METER.assess([sol, copy.deepcopy(sol), luna], minimum_advantage_multiple=5, minimum_pairs=2)

    def test_requires_same_window_and_allows_excluded_nonoverlapping_referee_gap(self) -> None:
        sol = record("SOL_ONLY", before=100, after=60, elapsed=100)
        luna = record("SOL_LUNA", before=60, after=55, elapsed=80)
        luna["limits"]["five_hour"]["window_id"] = "another-window"
        with self.assertRaisesRegex(METER.AllowanceError, "window_id differs"):
            METER.assess([sol, luna], minimum_advantage_multiple=5, minimum_pairs=2)
        luna = record("SOL_LUNA", before=59, after=54, elapsed=80)
        result = METER.assess([sol, luna], minimum_advantage_multiple=5, minimum_pairs=2)
        self.assertEqual(
            result["pairs"][0]["limits"]["five_hour"][
                "excluded_between_arm_consumption_percentage_points"
            ],
            1,
        )
        luna = record("SOL_LUNA", before=61, after=56, elapsed=80)
        with self.assertRaisesRegex(METER.AllowanceError, "increased between arms"):
            METER.assess([sol, luna], minimum_advantage_multiple=5, minimum_pairs=2)
        luna = record("SOL_LUNA", before=60, after=55, elapsed=80)
        for limit in luna["limits"].values():
            limit["before_observed_at"] = "2026-08-28T00:09:00+10:00"
        with self.assertRaisesRegex(METER.AllowanceError, "times overlap"):
            METER.assess([sol, luna], minimum_advantage_multiple=5, minimum_pairs=2)

    def test_measurement_scope_excludes_referee_work(self) -> None:
        source = record("SOL_ONLY", before=100, after=60, elapsed=100)
        source["measurement_scope"] = "TASK_PLUS_REFEREE"
        with self.assertRaisesRegex(METER.AllowanceError, "exclude referee"):
            METER.validate_record(source)

    def test_four_pair_counterbalanced_campaign_proves_tenfold_lower_bound(self) -> None:
        records = []
        for index in range(4):
            pair_id = f"pair-{index + 1:03d}"
            if index % 2 == 0:
                records.extend(
                    [
                        record("SOL_ONLY", before=100, after=70, elapsed=100, uncertainty=0.5, pair_id=pair_id, arm_position=1),
                        record("SOL_LUNA", before=70, after=69, elapsed=50, uncertainty=0.5, pair_id=pair_id, arm_position=2),
                    ]
                )
            else:
                records.extend(
                    [
                        record("SOL_LUNA", before=100, after=99, elapsed=50, uncertainty=0.5, pair_id=pair_id, arm_position=1),
                        record("SOL_ONLY", before=99, after=69, elapsed=100, uncertainty=0.5, pair_id=pair_id, arm_position=2),
                    ]
                )
        result = METER.assess(records, minimum_advantage_multiple=10, minimum_pairs=4)
        self.assertEqual(result["campaign_status"], "PASS")
        self.assertTrue(result["campaign"]["counterbalanced"])
        self.assertGreater(
            result["campaign"]["limits"]["five_hour"]["advantage"][
                "conservative_advantage_multiple_lower_bound"
            ],
            10,
        )

    def test_rejects_non_finite_and_negative_measurements(self) -> None:
        for value in (float("nan"), float("inf"), -1, True):
            source = record("SOL_ONLY", before=100, after=60, elapsed=100)
            source["elapsed_seconds"] = value
            with self.subTest(value=value), self.assertRaises(METER.AllowanceError):
                METER.validate_record(source)


if __name__ == "__main__":
    unittest.main()

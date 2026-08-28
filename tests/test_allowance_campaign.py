from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "allowance_campaign.py"
SPEC = importlib.util.spec_from_file_location("allowance_campaign", SCRIPT)
assert SPEC and SPEC.loader
CAMPAIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMPAIGN)
DIGEST = "sha256:" + "a" * 64


class AllowanceCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "campaign.jsonl"
        self.origin = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
        CAMPAIGN.initialize(
            self.ledger,
            contract_digest=DIGEST,
            usage_scope_digest="sha256:" + "b" * 64,
            task_family="bounded-feature",
            batch_size=1,
            reading_uncertainty=0.1,
            first_routes="SOL_ONLY,SOL_LUNA,SOL_LUNA,SOL_ONLY,SOL_ONLY",
            starting_commit_sha="a" * 40,
            task_spec_digest="sha256:" + "d" * 64,
            acceptance_suite_digest="sha256:" + "e" * 64,
            target_elapsed_min_seconds=5,
            target_elapsed_max_seconds=30,
            meter_resolution_percentage_points=0.1,
            repair_policy_digest="sha256:" + "f" * 64,
            five_hour_window_id="five-hour-001",
            five_hour_reset_at=(self.origin + timedelta(hours=10)).isoformat(),
            weekly_window_id="weekly-001",
            weekly_reset_at=(self.origin + timedelta(days=2)).isoformat(),
        )
        first_event = json.loads(self.ledger.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(first_event["previous_event_sha256"], "0" * 64)

    def stamp(self, minute: int) -> str:
        return (self.origin + timedelta(minutes=minute)).isoformat()

    def begin(self, route: str, minute: int, five: float, weekly: float) -> dict:
        return CAMPAIGN.begin_arm(
            self.ledger,
            route=route,
            route_revision="v0.1.1",
            observed_at=self.stamp(minute),
            five_hour_remaining_percent=five,
            weekly_remaining_percent=weekly,
            start_evidence_digest=DIGEST,
        )

    def end(self, route: str, minute: int, five: float, weekly: float, elapsed: float = 10) -> dict:
        ended = CAMPAIGN.end_arm(
            self.ledger,
            pair_id=CAMPAIGN.replay(self.ledger)["active"]["pair_id"],
            route=route,
            observed_at=self.stamp(minute),
            five_hour_remaining_percent=five,
            weekly_remaining_percent=weekly,
            end_evidence_digest="sha256:" + "c" * 64,
            elapsed_seconds=elapsed,
            candidate_digest=DIGEST,
        )
        return CAMPAIGN.record_acceptance(
            self.ledger,
            pair_id=ended["pair_id"],
            route=route,
            candidate_digest=DIGEST,
            acceptance_command_digest=DIGEST,
            acceptance_result_digest=DIGEST,
            acceptance_suite_digest="sha256:" + "e" * 64,
            observed_at=self.stamp(minute + 2),
            acceptance_elapsed_seconds=1,
            independent_acceptance="PASSED",
            defects=0,
        )

    def test_full_four_pair_campaign_records_gaps_recovers_and_assesses(self) -> None:
        remaining_five = 100.0
        remaining_weekly = 100.0
        minute = 1
        routes = ["SOL_ONLY", "SOL_LUNA", "SOL_LUNA", "SOL_ONLY", "SOL_ONLY"]
        excluded = 0.0
        for first in routes:
            for route in (first, CAMPAIGN._opposite(first)):
                gap = 0.0 if minute == 1 else 0.2
                remaining_five -= gap
                remaining_weekly -= gap
                started = self.begin(route, minute, remaining_five, remaining_weekly)
                excluded += gap
                self.assertAlmostEqual(
                    started["excluded_since_previous_end_percentage_points"]["five_hour"], gap
                )
                consumption = 8.0 if route == "SOL_ONLY" else 0.5
                remaining_five -= consumption
                remaining_weekly -= consumption
                self.end(route, minute + 1, remaining_five, remaining_weekly, 20 if route == "SOL_ONLY" else 5)
                minute += 3
        status = CAMPAIGN.campaign_status(self.ledger)
        self.assertEqual(status["completed_pairs"], 5)
        self.assertEqual(status["completed_arms"], 10)
        self.assertIsNone(status["active_arm"])
        self.assertIsNone(status["next_route"])
        self.assertAlmostEqual(status["excluded_consumption_percentage_points"]["five_hour"], excluded)
        self.assertEqual(len(CAMPAIGN.replay(self.ledger)["records"]), 10)
        assessment = CAMPAIGN.assess_campaign(
            self.ledger, minimum_advantage_multiple=5, minimum_pairs=5
        )
        self.assertEqual(assessment["campaign_status"], "PASS")
        self.assertEqual(assessment["primary_limit"], "five_hour")
        self.assertEqual(assessment["secondary_limit"], "weekly")

    def test_active_arm_is_recovered_by_status(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        status = CAMPAIGN.campaign_status(self.ledger)
        self.assertEqual(status["active_arm"]["route"], "SOL_ONLY")
        self.assertEqual(status["next_route"], "SOL_LUNA")
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "active"):
            CAMPAIGN.assess_campaign(self.ledger)
        self.end("SOL_ONLY", 2, 90, 99)
        self.assertEqual(CAMPAIGN.campaign_status(self.ledger)["next_route"], "SOL_LUNA")

    def test_wrong_route_and_duplicate_begin_preserve_ledger(self) -> None:
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "next route"):
            self.begin("SOL_LUNA", 1, 100, 100)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.begin("SOL_ONLY", 1, 100, 100)
        active = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "active"):
            self.begin("SOL_ONLY", 2, 99, 99)
        self.assertEqual(self.ledger.read_bytes(), active)

    def test_increasing_reading_and_cross_reset_are_rejected_without_corruption(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        active = self.ledger.read_bytes()
        with self.assertRaises(CAMPAIGN.CampaignError):
            self.end("SOL_ONLY", 2, 101, 99)
        self.assertEqual(self.ledger.read_bytes(), active)
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "reset boundary"):
            CAMPAIGN.end_arm(
                self.ledger,
                pair_id=CAMPAIGN.replay(self.ledger)["active"]["pair_id"],
                route="SOL_ONLY",
                observed_at=(self.origin + timedelta(hours=10)).isoformat(),
                five_hour_remaining_percent=90,
                weekly_remaining_percent=99,
                end_evidence_digest=DIGEST,
                elapsed_seconds=1,
                candidate_digest=DIGEST,
            )
        self.assertEqual(self.ledger.read_bytes(), active)

    def test_between_arm_increase_is_treated_as_reset_or_inconsistency(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        self.end("SOL_ONLY", 2, 90, 99)
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "increased between arms"):
            self.begin("SOL_LUNA", 3, 91, 99)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_corrupt_json_unknown_fields_hash_break_and_tampered_record_fail_replay(self) -> None:
        original = self.ledger.read_bytes()
        self.ledger.write_bytes(b"{broken}\n")
        with self.assertRaises(CAMPAIGN.CampaignError):
            CAMPAIGN.replay(self.ledger)
        self.ledger.write_bytes(original)
        event = json.loads(original.decode().splitlines()[0])
        event["unknown"] = True
        self.ledger.write_bytes(CAMPAIGN.canonical_bytes(event) + b"\n")
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "unsupported"):
            CAMPAIGN.replay(self.ledger)

        self.ledger.write_bytes(original)
        self.begin("SOL_ONLY", 1, 100, 100)
        self.end("SOL_ONLY", 2, 90, 99)
        events = [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()]
        events[-1]["candidate_digest"] = "sha256:" + "9" * 64
        for index in range(1, len(events)):
            events[index]["previous_event_sha256"] = CAMPAIGN._event_previous(
                CAMPAIGN.canonical_bytes(events[index - 1])
            )
        self.ledger.write_bytes(b"\n".join(CAMPAIGN.canonical_bytes(item) for item in events) + b"\n")
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "does not match"):
            CAMPAIGN.replay(self.ledger)

    def test_foreign_lock_is_not_removed(self) -> None:
        lock = Path(str(self.ledger) + ".lock")
        lock.write_text("foreign", encoding="utf-8")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "lock already exists"):
            self.begin("SOL_ONLY", 1, 100, 100)
        self.assertEqual(lock.read_text(encoding="utf-8"), "foreign")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_atomic_replace_failure_preserves_old_ledger_and_cleans_owned_artifacts(self) -> None:
        before = self.ledger.read_bytes()
        with mock.patch.object(CAMPAIGN.os, "replace", side_effect=OSError("forced")):
            with self.assertRaisesRegex(CAMPAIGN.CampaignError, "atomically"):
                self.begin("SOL_ONLY", 1, 100, 100)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse(Path(str(self.ledger) + ".lock").exists())
        self.assertEqual(list(self.ledger.parent.glob(self.ledger.name + ".*.tmp")), [])

    def test_init_refuses_existing_ledger_without_truncation(self) -> None:
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "already exists"):
            CAMPAIGN.initialize(
                self.ledger,
                contract_digest=DIGEST,
                usage_scope_digest=DIGEST,
                task_family="bounded-feature",
                batch_size=1,
                reading_uncertainty=1,
                first_routes="SOL_ONLY,SOL_LUNA",
                five_hour_window_id="five-hour-001",
                five_hour_reset_at=self.stamp(100),
                weekly_window_id="weekly-001",
                weekly_reset_at=self.stamp(200),
            )
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_production_assessment_rejects_less_than_five_pairs(self) -> None:
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "at least 5"):
            CAMPAIGN.assess_campaign(self.ledger, minimum_pairs=4)

    def test_production_assessment_rejects_placeholder_identity(self) -> None:
        state = CAMPAIGN.replay(self.ledger)
        state["config"] = dict(state["config"])
        state["config"]["starting_commit_sha"] = "0" * 40
        with mock.patch.object(CAMPAIGN, "replay", return_value=state), self.assertRaisesRegex(
            CAMPAIGN.CampaignError, "non-placeholder"
        ):
            CAMPAIGN.assess_campaign(self.ledger, minimum_pairs=5)

    def test_frozen_configuration_is_inherited_by_completed_records(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        record = self.end("SOL_ONLY", 2, 90, 99, elapsed=20)
        self.assertEqual(record["starting_commit_sha"], "a" * 40)
        self.assertEqual(record["task_spec_digest"], "sha256:" + "d" * 64)
        self.assertEqual(record["sol_only_topology"], "single-controller-no-workers")
        self.assertEqual(record["worker_count"], 0)
        self.assertEqual(record["top_level_run_count"], 1)

    def test_meter_resolution_rejects_false_precision_without_writing(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "integer multiple"):
            self.end("SOL_ONLY", 2, 90.05, 99, elapsed=20)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_init_freezes_custom_luna_worker_pool_and_emits_it(self) -> None:
        ledger = Path(self.temp.name) / "multi-worker.jsonl"
        CAMPAIGN.initialize(
            ledger,
            contract_digest=DIGEST,
            usage_scope_digest=DIGEST,
            task_family="bounded-feature",
            batch_size=1,
            reading_uncertainty=0.1,
            first_routes="SOL_ONLY,SOL_LUNA",
            five_hour_window_id="five-hour-001",
            five_hour_reset_at=(self.origin + timedelta(hours=10)).isoformat(),
            weekly_window_id="weekly-001",
            weekly_reset_at=(self.origin + timedelta(days=2)).isoformat(),
            sol_only_topology="sol-controller-v2",
            sol_luna_topology="controller-with-luna-pool-v2",
            sol_luna_worker_count=3,
            sol_luna_active_luna_writer_count=2,
            target_elapsed_min_seconds=5,
            target_elapsed_max_seconds=30,
        )
        event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(event["sol_luna_worker_count"], 3)
        self.assertEqual(event["sol_luna_active_luna_writer_count"], 2)
        result = CAMPAIGN.begin_arm(
            ledger,
            route="SOL_ONLY",
            route_revision="v0.1.1",
            observed_at=self.stamp(1),
            five_hour_remaining_percent=100,
            weekly_remaining_percent=100,
            start_evidence_digest=DIGEST,
        )
        self.assertEqual(result["route"], "SOL_ONLY")
        ended = CAMPAIGN.end_arm(
            ledger,
            pair_id="pair-001",
            route="SOL_ONLY",
            observed_at=self.stamp(2),
            five_hour_remaining_percent=90,
            weekly_remaining_percent=90,
            end_evidence_digest=DIGEST,
            elapsed_seconds=10,
            candidate_digest=DIGEST,
        )
        CAMPAIGN.record_acceptance(
            ledger,
            pair_id=ended["pair_id"],
            route="SOL_ONLY",
            candidate_digest=DIGEST,
            acceptance_command_digest=DIGEST,
            acceptance_result_digest=DIGEST,
            acceptance_suite_digest="sha256:" + "0" * 64,
            observed_at=self.stamp(2.5),
            acceptance_elapsed_seconds=1,
            independent_acceptance="PASSED",
            defects=0,
        )
        CAMPAIGN.begin_arm(
            ledger,
            route="SOL_LUNA",
            route_revision="v0.1.1",
            observed_at=self.stamp(3),
            five_hour_remaining_percent=90,
            weekly_remaining_percent=90,
            start_evidence_digest=DIGEST,
        )
        ended = CAMPAIGN.end_arm(
            ledger,
            pair_id="pair-001",
            route="SOL_LUNA",
            observed_at=self.stamp(4),
            five_hour_remaining_percent=89,
            weekly_remaining_percent=89,
            end_evidence_digest=DIGEST,
            elapsed_seconds=10,
            candidate_digest=DIGEST,
        )
        record = CAMPAIGN.record_acceptance(
            ledger,
            pair_id=ended["pair_id"],
            route="SOL_LUNA",
            candidate_digest=DIGEST,
            acceptance_command_digest=DIGEST,
            acceptance_result_digest=DIGEST,
            acceptance_suite_digest="sha256:" + "0" * 64,
            observed_at=self.stamp(4.5),
            acceptance_elapsed_seconds=1,
            independent_acceptance="PASSED",
            defects=0,
        )
        self.assertEqual(record["worker_count"], 3)
        self.assertEqual(record["active_luna_writer_count"], 2)

    def test_init_rejects_invalid_custom_luna_topology(self) -> None:
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "cannot exceed"):
            CAMPAIGN.initialize(
                Path(self.temp.name) / "invalid-topology.jsonl",
                contract_digest=DIGEST,
                usage_scope_digest=DIGEST,
                task_family="bounded-feature",
                batch_size=1,
                reading_uncertainty=0.1,
                first_routes="SOL_ONLY,SOL_LUNA",
                five_hour_window_id="five-hour-001",
                five_hour_reset_at=(self.origin + timedelta(hours=10)).isoformat(),
                weekly_window_id="weekly-001",
                weekly_reset_at=(self.origin + timedelta(days=2)).isoformat(),
                sol_luna_worker_count=1,
                sol_luna_active_luna_writer_count=2,
            )

    def _end_pending(self) -> dict:
        self.begin("SOL_ONLY", 1, 100, 100)
        return CAMPAIGN.end_arm(
            self.ledger,
            pair_id="pair-001",
            route="SOL_ONLY",
            observed_at=self.stamp(2),
            five_hour_remaining_percent=90,
            weekly_remaining_percent=90,
            end_evidence_digest=DIGEST,
            elapsed_seconds=10,
            candidate_digest=DIGEST,
        )

    def test_assessment_requires_independent_acceptance_event(self) -> None:
        self._end_pending()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "acceptance event"):
            CAMPAIGN.assess_campaign(self.ledger, minimum_pairs=5)
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "next route"):
            self.begin("SOL_LUNA", 3, 90, 90)

    def test_acceptance_candidate_mismatch_preserves_ledger(self) -> None:
        ended = self._end_pending()
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "candidate_digest"):
            CAMPAIGN.record_acceptance(
                self.ledger,
                pair_id=ended["pair_id"], route="SOL_ONLY",
                candidate_digest="sha256:" + "9" * 64,
                acceptance_command_digest=DIGEST,
                acceptance_result_digest=DIGEST,
                acceptance_suite_digest="sha256:" + "e" * 64,
                observed_at=self.stamp(3), acceptance_elapsed_seconds=1,
                independent_acceptance="PASSED", defects=0,
            )
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_acceptance_suite_and_result_digest_are_strict(self) -> None:
        ended = self._end_pending()
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "lowercase sha256"):
            CAMPAIGN.record_acceptance(
                self.ledger,
                pair_id=ended["pair_id"], route="SOL_ONLY", candidate_digest=DIGEST,
                acceptance_command_digest=DIGEST,
                acceptance_result_digest="not-a-digest",
                acceptance_suite_digest="sha256:" + "e" * 64,
                observed_at=self.stamp(3), acceptance_elapsed_seconds=1,
                independent_acceptance="PASSED", defects=0,
            )
        self.assertEqual(self.ledger.read_bytes(), before)
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "differs from campaign"):
            CAMPAIGN.record_acceptance(
                self.ledger,
                pair_id=ended["pair_id"], route="SOL_ONLY", candidate_digest=DIGEST,
                acceptance_command_digest=DIGEST, acceptance_result_digest=DIGEST,
                acceptance_suite_digest="sha256:" + "9" * 64,
                observed_at=self.stamp(3), acceptance_elapsed_seconds=1,
                independent_acceptance="PASSED", defects=0,
            )
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_acceptance_before_route_end_is_rejected(self) -> None:
        ended = self._end_pending()
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "after route interval end"):
            CAMPAIGN.record_acceptance(
                self.ledger,
                pair_id=ended["pair_id"], route="SOL_ONLY", candidate_digest=DIGEST,
                acceptance_command_digest=DIGEST, acceptance_result_digest=DIGEST,
                acceptance_suite_digest="sha256:" + "e" * 64,
                observed_at=self.stamp(1.5), acceptance_elapsed_seconds=1,
                independent_acceptance="PASSED", defects=0,
            )
        self.assertEqual(self.ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
